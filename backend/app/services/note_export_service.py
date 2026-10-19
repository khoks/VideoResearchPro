"""Notes export — JSON-LD (W3C Web Annotation) and Markdown (S-8.5.3).

Two streams, both per tenant, both in constant memory like the dataset
exports in ``dataset_service``:

- ``stream_notes_jsonld`` — one annotation per line in the W3C Web
  Annotation shape under the ``anno.jsonld`` context, chronological. This is
  the lossless one: ``parse_note_jsonld`` is its exact inverse and the
  round-trip test holds every column to it, deletions included (a withdrawn
  note is still the user's; Readwise's ``includeDeleted`` is the precedent).
  It is also the GDPR Article 20 "structured, commonly used, machine-readable"
  copy of user-provided data.
- ``stream_notes_markdown`` — a readable document grouped by target type and
  target, every note dated, every column present in an HTML comment so
  nothing is lost even here.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.note import Note
from app.services import note_service
from app.services.note_service import ResolvedTarget

JSONLD_CONTEXT = "http://www.w3.org/ns/anno.jsonld"
EXPORT_VERSION = 1
GENERATOR = {"type": "Software", "name": "Pratidhvani"}

_TYPE_ORDER = (
    "document",
    "knowledge_artifact",
    "job",
    "qa_exchange",
    "library_qa_exchange",
    "qa_history_exchange",
    "channel",
)
_TYPE_HEADINGS = {
    "document": "Sources",
    "knowledge_artifact": "Knowledge reports",
    "job": "Research runs",
    "qa_exchange": "Q&A answers",
    "library_qa_exchange": "Library Q&A answers",
    "qa_history_exchange": "Q&A history answers",
    "channel": "Channels",
}

_BATCH = 200


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    a = _aware(dt)
    return a.isoformat() if a else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------


def note_to_jsonld(note: Note, target: ResolvedTarget | None) -> dict[str, Any]:
    """The W3C Web Annotation shape plus a ``pratidhvani`` block with the raw
    target keys. Every stored column appears exactly once."""
    selector = note_service.load_selector(note.selector_json)
    target_doc: dict[str, Any] = {
        "id": f"urn:pratidhvani:{note.target_type}:{note.target_id}",
        "type": note.target_type,
    }
    if target and target.label:
        target_doc["label"] = target.label
    if selector:
        target_doc["selector"] = selector
    doc: dict[str, Any] = {
        "@context": JSONLD_CONTEXT,
        "id": f"urn:uuid:{note.id}",
        "type": "Annotation",
        "motivation": note.motivation,
        "created": _iso(note.created_at),
        "modified": _iso(note.updated_at),
        "generator": GENERATOR,
        "body": {"type": "TextualBody", "value": note.body_md, "format": "text/markdown"},
        "target": target_doc,
        # Not in the W3C vocabulary; processors ignore unknown keys, exports keep it.
        "deleted": _iso(note.deleted_at),
        "pratidhvani": {
            "version": EXPORT_VERSION,
            "target_type": note.target_type,
            "target_id": note.target_id,
            "target_video_id": target.video_id if target else None,
        },
    }
    return doc


def serialize_note_jsonld(note: Note, target: ResolvedTarget | None) -> str:
    return json.dumps(note_to_jsonld(note, target), ensure_ascii=False)


def parse_note_jsonld(line: str) -> dict[str, Any]:
    """Inverse of ``serialize_note_jsonld``: the stored columns, typed.

    Raises ``ValueError`` on anything that is not one of our annotations.
    """
    doc = json.loads(line)
    if not isinstance(doc, dict) or doc.get("type") != "Annotation":
        raise ValueError("not a Web Annotation")
    raw = doc.get("pratidhvani") or {}
    note_id = str(doc.get("id", ""))
    if not note_id.startswith("urn:uuid:"):
        raise ValueError("annotation id is not a urn:uuid")
    target = doc.get("target") or {}
    body = doc.get("body") or {}
    selector = target.get("selector")
    return {
        "id": note_id[len("urn:uuid:"):],
        "target_type": raw.get("target_type") or target.get("type"),
        "target_id": raw.get("target_id"),
        "body_md": body.get("value", ""),
        "motivation": doc.get("motivation", "commenting"),
        "selector": selector if isinstance(selector, dict) else None,
        "created_at": _parse_iso(doc.get("created")),
        "updated_at": _parse_iso(doc.get("modified")),
        "deleted_at": _parse_iso(doc.get("deleted")),
    }


def note_to_columns(note: Note) -> dict[str, Any]:
    """The same dict ``parse_note_jsonld`` returns, read from the row — so a
    test can assert ``parse(serialize(row)) == columns(row)``."""
    return {
        "id": note.id,
        "target_type": note.target_type,
        "target_id": note.target_id,
        "body_md": note.body_md,
        "motivation": note.motivation,
        "selector": note_service.load_selector(note.selector_json),
        "created_at": _aware(note.created_at),
        "updated_at": _aware(note.updated_at),
        "deleted_at": _aware(note.deleted_at),
    }


def _batched(notes: Iterator[Note], size: int) -> Iterator[list[Note]]:
    batch: list[Note] = []
    for n in notes:
        batch.append(n)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def stream_notes_jsonld(
    db: Session, tenant_id: str, *, include_deleted: bool = True
) -> Iterator[str]:
    """One JSON-LD annotation per line, oldest first. Labels are resolved per
    batch of 200 so memory stays O(batch)."""
    notes = note_service.iter_notes(db, tenant_id, include_deleted=include_deleted)
    for batch in _batched(notes, _BATCH):
        targets = note_service.describe_targets(db, batch)
        for n in batch:
            yield serialize_note_jsonld(n, targets.get((n.target_type, n.target_id))) + "\n"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _fmt_human(dt: datetime | None) -> str:
    a = _aware(dt)
    return a.strftime("%Y-%m-%d %H:%M UTC") if a else ""


def _selector_line(selector: dict | None) -> str | None:
    if not selector:
        return None
    parts: list[str] = []
    secs = selector.get("start_seconds")
    if isinstance(secs, (int, float)):
        parts.append(f"at {int(secs // 60)}:{int(secs % 60):02d}")
    if selector.get("exact"):
        parts.append(f"“{selector['exact']}”")
    return " · ".join(parts) if parts else None


def _note_markdown(note: Note) -> Iterator[str]:
    selector = note_service.load_selector(note.selector_json)
    heading = f"#### {_fmt_human(note.created_at)}"
    if note.deleted_at is not None:
        heading += f" (withdrawn {_fmt_human(note.deleted_at)})"
    yield heading + "\n"
    yield (
        f"<!-- note {note.id} · {note.motivation} · created {_iso(note.created_at)}"
        f" · updated {_iso(note.updated_at)}"
        + (f" · deleted {_iso(note.deleted_at)}" if note.deleted_at else "")
        + (f" · selector {json.dumps(selector, ensure_ascii=False)}" if selector else "")
        + " -->\n"
    )
    anchor = _selector_line(selector)
    if anchor:
        yield f"*{anchor}*\n\n"
    yield note.body_md.rstrip("\n") + "\n\n"


def stream_notes_markdown(
    db: Session, tenant_id: str, *, include_deleted: bool = True
) -> Iterator[str]:
    """A Markdown document grouped by target type, then target, notes oldest
    first within a target. Streams group by group; one small label lookup per
    target."""
    total, withdrawn = _counts(db, tenant_id, include_deleted)
    yield "# Your notes\n\n"
    yield (
        f"Exported from Pratidhvani on {_fmt_human(datetime.now(timezone.utc))} · "
        f"{total} note{'s' if total != 1 else ''}"
        + (f" ({withdrawn} withdrawn)" if withdrawn else "")
        + "\n\n"
    )
    if total == 0:
        yield "Nothing written yet.\n"
        return

    # One pass per target type, in the order the notes page groups them. Only
    # the current (type, target) group is buffered, never the whole export.
    for target_type in _TYPE_ORDER:
        query = db.query(Note).filter(
            Note.tenant_id == tenant_id, Note.target_type == target_type
        )
        if not include_deleted:
            query = query.filter(Note.deleted_at.is_(None))
        rows = query.order_by(Note.target_id, Note.created_at, Note.id).yield_per(_BATCH)

        heading_done = False
        group: list[Note] = []
        for n in rows:
            if group and n.target_id != group[0].target_id:
                yield from _group_markdown(db, group)
                group = []
            if not heading_done:
                yield f"## {_TYPE_HEADINGS[target_type]}\n\n"
                heading_done = True
            group.append(n)
        if group:
            yield from _group_markdown(db, group)


def _group_markdown(db: Session, group: list[Note]) -> Iterator[str]:
    first = group[0]
    targets = note_service.describe_targets(db, group)
    resolved = targets.get((first.target_type, first.target_id))
    label = resolved.label if resolved and resolved.label else "(target no longer available)"
    yield f"### {label}\n"
    yield f"`{first.target_type}:{first.target_id}`\n\n"
    for n in group:
        yield from _note_markdown(n)


def _counts(db: Session, tenant_id: str, include_deleted: bool) -> tuple[int, int]:
    from sqlalchemy import func

    base = db.query(func.count(Note.id)).filter(Note.tenant_id == tenant_id)
    live = base.filter(Note.deleted_at.is_(None)).scalar() or 0
    if not include_deleted:
        return int(live), 0
    total = base.scalar() or 0
    return int(total), int(total) - int(live)

"""Google Keep notes from Google Takeout (S-3.7.5, T-3.7.5.2, the Keep half).

Takeout writes one JSON file per note under ``Takeout/Keep/`` (with the
note's images beside it). Each note has ``title``, ``textContent`` or
``listContent[]`` (``text``, ``isChecked``), ``labels[]``, ``annotations[]``
(web links), ``attachments[]``, ``isTrashed``, ``isArchived``, ``isPinned``
and microsecond timestamps. The upload is either the Takeout zip or a single
note's ``.json``.

A Keep note is something the user wrote, so it is their own words by default
(``own_words``); the user can turn that off for an account full of pasted
quotes. Trashed notes are skipped unless ``include_trashed`` is set. Images
are counted, not imported.

A Takeout zip can carry other products too. They are named in the preview's
warnings; the YouTube history in it comes with the event importers.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterator

from app.services.echo_importers.base import ImportedShare, ExportUnreadable, ImportPreview, ImportSource

NAME = "google_keep"
LABEL = "Google Keep notes (Takeout)"
CONTENT_TYPE = "keep_note"

_KEEP_MEMBER = re.compile(r"(^|/)Keep/[^/]+\.json$", re.I)
_MAX_NOTE_BYTES = 10 * 1024 * 1024
_OTHER_PRODUCTS = {
    "YouTube and YouTube Music": "YouTube history arrives with the event importers",
    "My Activity": "My Activity arrives with the event importers",
}


def _members(source: ImportSource) -> list[str]:
    return [n for n in source.member_names() if _KEEP_MEMBER.search(n)]


def _looks_like_note(data: dict) -> bool:
    return isinstance(data, dict) and (
        "textContent" in data or "listContent" in data
    ) and ("userEditedTimestampUsec" in data or "createdTimestampUsec" in data)


def accepts(source: ImportSource) -> bool:
    try:
        if source.is_zip:
            return bool(_members(source))
        if not source.filename.lower().endswith(".json"):
            return False
        head = source.head(65536).decode("utf-8", "replace")
        return ("textContent" in head or "listContent" in head) and "TimestampUsec" in head
    except Exception:
        return False


def _load(source: ImportSource, member: str | None) -> dict | None:
    if member is not None:
        info = source.zip.getinfo(member)
        if info.file_size > _MAX_NOTE_BYTES:
            return None
    elif source.size() > _MAX_NOTE_BYTES:
        raise ExportUnreadable("This file is too large to be a single Keep note.")
    with source.open_binary(member) as fh:
        try:
            data = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
    return data if _looks_like_note(data) else None


def _notes(source: ImportSource) -> Iterator[tuple[str, dict]]:
    if source.is_zip:
        for member in _members(source):
            note = _load(source, member)
            if note is not None:
                yield member, note
    else:
        note = _load(source, None)
        if note is None:
            raise ExportUnreadable("This JSON file is not a Google Keep note.")
        yield source.filename, note


def _when(note: dict) -> datetime | None:
    for key in ("userEditedTimestampUsec", "createdTimestampUsec"):
        value = note.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
    return None


def note_text(note: dict) -> str:
    parts: list[str] = []
    title = (note.get("title") or "").strip()
    if title:
        parts.append(title)
    body = (note.get("textContent") or "").strip()
    if body:
        parts.append(body)
    items = note.get("listContent") or []
    if items:
        parts.append("\n".join(
            f"- [{'x' if i.get('isChecked') else ' '}] {(i.get('text') or '').strip()}"
            for i in items if (i.get("text") or "").strip()
        ))
    links = [a.get("url") for a in note.get("annotations") or [] if a.get("url")]
    if links:
        parts.append("\n".join(links))
    return "\n\n".join(p for p in parts if p)


def _other_products(source: ImportSource) -> list[str]:
    if not source.is_zip:
        return []
    found = []
    names = source.member_names()
    for product, why in _OTHER_PRODUCTS.items():
        if any(f"/{product}/" in f"/{n}" for n in names):
            found.append(f"This archive also holds {product}; {why}.")
    return found


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    counts = {"notes": 0, "trashed": 0, "archived": 0, "pinned": 0, "lists": 0, "with_images": 0, "empty": 0}
    labels: dict[str, int] = {}
    first: datetime | None = None
    last: datetime | None = None
    for _, note in _notes(source):
        if note.get("isTrashed"):
            counts["trashed"] += 1
            continue
        if not note_text(note):
            counts["empty"] += 1
            continue
        counts["notes"] += 1
        counts["archived"] += bool(note.get("isArchived"))
        counts["pinned"] += bool(note.get("isPinned"))
        counts["lists"] += bool(note.get("listContent"))
        counts["with_images"] += bool(note.get("attachments"))
        for label in note.get("labels") or []:
            name = (label.get("name") or "").strip()
            if name:
                labels[name] = labels.get(name, 0) + 1
        when = _when(note)
        if when:
            first = min(first, when) if first else when
            last = max(last, when) if last else when
    if counts["notes"] == 0 and counts["trashed"] == 0:
        raise ExportUnreadable("No Google Keep notes were found in this upload.")
    return ImportPreview(
        importer=NAME,
        label=LABEL,
        summary={
            **counts,
            "labels": dict(sorted(labels.items(), key=lambda kv: -kv[1])[:20]),
            "first_at": first.isoformat() if first else None,
            "last_at": last.isoformat() if last else None,
        },
        options={"own_words": True, "include_trashed": False},
        warnings=_other_products(source),
    )


def parse(source: ImportSource, options: dict[str, Any], stats: dict[str, int]) -> Iterator[ImportedShare]:
    own = options.get("own_words", True) is not False
    include_trashed = bool(options.get("include_trashed"))
    for member, note in _notes(source):
        if note.get("isTrashed") and not include_trashed:
            stats["skipped_trashed"] = stats.get("skipped_trashed", 0) + 1
            continue
        text = note_text(note)
        if not text:
            stats["skipped_empty"] = stats.get("skipped_empty", 0) + 1
            continue
        when = _when(note)
        yield ImportedShare(
            content_type=CONTENT_TYPE,
            text=text,
            author_is_tenant=own,
            occurred_at=when,
            meta={
                "title": (note.get("title") or "").strip() or None,
                "labels": [lb.get("name") for lb in note.get("labels") or [] if lb.get("name")],
                "pinned": bool(note.get("isPinned")),
                "archived": bool(note.get("isArchived")),
                "trashed": bool(note.get("isTrashed")),
                "images": len(note.get("attachments") or []),
                "file": member.rsplit("/", 1)[-1],
            },
        )

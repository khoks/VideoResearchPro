"""Notes — CRUD, target resolution and target summaries (M5 / S-8.5.1).

Two invariants every caller relies on:

1. **A note is read only through its tenant.** Every query here filters on
   ``Note.tenant_id``. A foreign note id is indistinguishable from a missing
   one (``NoteNotFound``), the same rule the library Q&A delete follows.
2. **You cannot annotate what you cannot see.** ``resolve_target`` checks the
   target through the tenant's visibility (documents, channels) or ownership
   (jobs, exchanges) before any write. A target the tenant cannot see raises
   ``NoteTargetNotFound``, which the router turns into the same 404 as a
   missing target.

Documents have two ids until D-070 lands — the canonical ``document_id`` and
the legacy YouTube ``video_id`` that most UI surfaces still carry. The
service accepts either on input and stores the canonical one, so a note
written from the library shelf (video_id) and one written from a job page
(document_id) land in the same stream. The response carries both back so the
caller can match on whichever it has.

No embedding, no retrieval here: that is S-8.5.2, after the D-068 re-rank.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.note import Note
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.services import subscription_service, visibility_service

logger = logging.getLogger(__name__)

TARGET_TYPES: frozenset[str] = frozenset(
    {
        "document",
        "job",
        "qa_exchange",
        "library_qa_exchange",
        "qa_history_exchange",
        "channel",
        "knowledge_artifact",
    }
)
MOTIVATIONS: frozenset[str] = frozenset({"commenting", "highlighting", "tagging"})

# Target types whose id is a document's. Both resolve through the document
# row; a knowledge artifact additionally has to exist.
_DOCUMENT_BACKED = frozenset({"document", "knowledge_artifact"})

_LABEL_MAX = 140


class NoteNotFound(LookupError):
    """No live note with that id belongs to this tenant."""


class NoteTargetNotFound(LookupError):
    """The target does not exist or is not visible to this tenant."""


class InvalidNote(ValueError):
    """A closed-set field carried a value outside the set."""


@dataclass(frozen=True)
class ResolvedTarget:
    target_type: str
    target_id: str  # canonical
    label: str | None
    video_id: str | None = None


# ---------------------------------------------------------------------------
# Target resolution (visibility and ownership)
# ---------------------------------------------------------------------------


def _truncate(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= _LABEL_MAX else text[: _LABEL_MAX - 1] + "…"


def _job_label(job: Job) -> str:
    if job.job_type == "topic":
        return job.topic or "Untitled topic"
    if job.job_type == "subscription":
        return "Subscription sync"
    return "Channel collection"


def _visible_document(db: Session, tenant_id: str, raw_id: str) -> Document | None:
    """The document ``raw_id`` names, by canonical or legacy id, if this tenant
    may see it (D-063). One query; the visibility subquery is keyed on the
    legacy ``video_id`` until D-070 moves it."""
    return (
        db.query(Document)
        .filter(
            or_(Document.document_id == raw_id, Document.video_id == raw_id),
            Document.video_id.in_(visibility_service.visible_video_ids(db, tenant_id)),
        )
        .first()
    )


def resolve_target(
    db: Session, tenant_id: str, target_type: str, target_id: str
) -> ResolvedTarget:
    """Check the target exists AND this tenant may see or owns it.

    Returns the canonical target id and a display label. Raises
    ``NoteTargetNotFound`` otherwise — never distinguishes "missing" from
    "someone else's".
    """
    if target_type not in TARGET_TYPES:
        raise InvalidNote(f"unknown target_type {target_type!r}")
    target_id = target_id.strip()
    if not target_id:
        raise NoteTargetNotFound(f"{target_type}: blank id")

    if target_type in _DOCUMENT_BACKED:
        doc = _visible_document(db, tenant_id, target_id)
        if doc is None:
            raise NoteTargetNotFound(f"{target_type} {target_id} not visible")
        if target_type == "knowledge_artifact" and doc.knowledge_extracted_at is None:
            # The artifact is columns on the document row; "exists" means
            # extraction has run. A note on a report that has not been
            # written yet would dangle.
            raise NoteTargetNotFound(f"no knowledge artifact for {target_id}")
        return ResolvedTarget(
            target_type, doc.document_id, _truncate(doc.title), video_id=doc.video_id
        )

    if target_type == "job":
        job = (
            db.query(Job)
            .filter(Job.id == target_id, Job.tenant_id == tenant_id)
            .first()
        )
        if job is None:
            raise NoteTargetNotFound(f"job {target_id} not owned")
        return ResolvedTarget(target_type, job.id, _truncate(_job_label(job)))

    if target_type == "qa_exchange":
        row = (
            db.query(QAExchange)
            .filter(QAExchange.id == target_id, QAExchange.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            raise NoteTargetNotFound(f"qa_exchange {target_id} not owned")
        return ResolvedTarget(target_type, row.id, _truncate(row.question))

    if target_type == "library_qa_exchange":
        row = (
            db.query(LibraryQAExchange)
            .filter(
                LibraryQAExchange.id == target_id,
                LibraryQAExchange.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise NoteTargetNotFound(f"library_qa_exchange {target_id} not owned")
        return ResolvedTarget(target_type, row.id, _truncate(row.question))

    if target_type == "qa_history_exchange":
        row = (
            db.query(QAHistoryExchange)
            .filter(
                QAHistoryExchange.id == target_id,
                QAHistoryExchange.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise NoteTargetNotFound(f"qa_history_exchange {target_id} not owned")
        return ResolvedTarget(target_type, row.id, _truncate(row.question))

    if target_type == "channel":
        ch = (
            db.query(Channel)
            .filter(
                Channel.channel_id == target_id,
                Channel.channel_id.in_(
                    subscription_service.visible_channel_ids(db, tenant_id)
                ),
            )
            .first()
        )
        if ch is None:
            raise NoteTargetNotFound(f"channel {target_id} not visible")
        return ResolvedTarget(target_type, ch.channel_id, _truncate(ch.name))

    raise InvalidNote(f"unhandled target_type {target_type!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


def _dump_selector(selector: dict | None) -> str | None:
    if selector is None:
        return None
    return json.dumps(selector, ensure_ascii=False, separators=(",", ":"))


def load_selector(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("notes: corrupt selector_json ignored")
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _live(query, include_deleted: bool = False):
    return query if include_deleted else query.filter(Note.deleted_at.is_(None))


def create_note(
    db: Session,
    tenant_id: str,
    *,
    target_type: str,
    target_id: str,
    body_md: str,
    motivation: str = "commenting",
    selector: dict | None = None,
) -> Note:
    if motivation not in MOTIVATIONS:
        raise InvalidNote(f"unknown motivation {motivation!r}")
    if not body_md or not body_md.strip():
        raise InvalidNote("body_md must not be blank")
    target = resolve_target(db, tenant_id, target_type, target_id)
    note = Note(
        tenant_id=tenant_id,
        target_type=target.target_type,
        target_id=target.target_id,
        body_md=body_md,
        motivation=motivation,
        selector_json=_dump_selector(selector),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    logger.info(
        "notes: tenant %s wrote note %s on %s:%s",
        tenant_id[:8], note.id[:8], target.target_type, target.target_id[:12],
    )
    return note


def get_note(
    db: Session, tenant_id: str, note_id: str, *, include_deleted: bool = False
) -> Note:
    note = _live(
        db.query(Note).filter(Note.id == note_id, Note.tenant_id == tenant_id),
        include_deleted,
    ).first()
    if note is None:
        raise NoteNotFound(note_id)
    return note


_UNSET = object()


def update_note(
    db: Session,
    tenant_id: str,
    note_id: str,
    *,
    body_md: str | None = None,
    motivation: str | None = None,
    selector: dict | None | object = _UNSET,
) -> Note:
    note = get_note(db, tenant_id, note_id)
    if body_md is not None:
        if not body_md.strip():
            raise InvalidNote("body_md must not be blank")
        note.body_md = body_md
    if motivation is not None:
        if motivation not in MOTIVATIONS:
            raise InvalidNote(f"unknown motivation {motivation!r}")
        note.motivation = motivation
    if selector is not _UNSET:
        note.selector_json = _dump_selector(selector)  # type: ignore[arg-type]
    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, tenant_id: str, note_id: str) -> Note:
    """Soft delete. The row stays (exports carry deletions, Echo keeps the
    signal); it leaves every live list and ``get_note`` at once."""
    note = get_note(db, tenant_id, note_id)
    note.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return note


def list_notes(
    db: Session,
    tenant_id: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[Note], int]:
    """Newest first. ``target_id`` must already be canonical (call
    ``resolve_target`` first when it came from a client).

    Returns ``(page, total)``.
    """
    if target_type is not None and target_type not in TARGET_TYPES:
        raise InvalidNote(f"unknown target_type {target_type!r}")
    query = _live(db.query(Note).filter(Note.tenant_id == tenant_id), include_deleted)
    if target_type is not None:
        query = query.filter(Note.target_type == target_type)
    if target_id is not None:
        query = query.filter(Note.target_id == target_id)
    if q:
        query = query.filter(Note.body_md.ilike(f"%{q}%"))
    total = query.with_entities(func.count(Note.id)).scalar() or 0
    page = (
        query.order_by(Note.created_at.desc(), Note.id.desc())
        .offset(max(offset, 0))
        .limit(max(limit, 0))
        .all()
    )
    return page, int(total)


def iter_notes(
    db: Session, tenant_id: str, *, include_deleted: bool = True, batch: int = 200
) -> Iterable[Note]:
    """Every note of the tenant, oldest first, in constant memory. For exports."""
    query = _live(db.query(Note).filter(Note.tenant_id == tenant_id), include_deleted)
    yield from query.order_by(Note.created_at.asc(), Note.id.asc()).yield_per(batch)


# ---------------------------------------------------------------------------
# Target summaries (label + legacy id), batched per type
# ---------------------------------------------------------------------------


def describe_targets(
    db: Session, notes: Iterable[Note]
) -> dict[tuple[str, str], ResolvedTarget]:
    """One query per target type present, not one per note.

    Does NOT re-check visibility: the notes are already the tenant's, and the
    target was checked when the note was written. A target that has since
    gone (deleted job) simply has no entry, which the response renders as a
    missing label rather than dropping the user's note.
    """
    by_type: dict[str, set[str]] = {}
    for n in notes:
        by_type.setdefault(n.target_type, set()).add(n.target_id)
    out: dict[tuple[str, str], ResolvedTarget] = {}

    doc_ids = by_type.get("document", set()) | by_type.get("knowledge_artifact", set())
    if doc_ids:
        for d in db.query(Document).filter(Document.document_id.in_(doc_ids)):
            for t in ("document", "knowledge_artifact"):
                if d.document_id in by_type.get(t, ()):
                    out[(t, d.document_id)] = ResolvedTarget(
                        t, d.document_id, _truncate(d.title), video_id=d.video_id
                    )

    if ids := by_type.get("job"):
        for j in db.query(Job).filter(Job.id.in_(ids)):
            out[("job", j.id)] = ResolvedTarget("job", j.id, _truncate(_job_label(j)))

    for t, model in (
        ("qa_exchange", QAExchange),
        ("library_qa_exchange", LibraryQAExchange),
        ("qa_history_exchange", QAHistoryExchange),
    ):
        if ids := by_type.get(t):
            for row in db.query(model).filter(model.id.in_(ids)):
                out[(t, row.id)] = ResolvedTarget(t, row.id, _truncate(row.question))

    if ids := by_type.get("channel"):
        for ch in db.query(Channel).filter(Channel.channel_id.in_(ids)):
            out[("channel", ch.channel_id)] = ResolvedTarget(
                "channel", ch.channel_id, _truncate(ch.name)
            )

    return out

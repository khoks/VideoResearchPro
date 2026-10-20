"""The notes retrieval index (M5 / S-8.5.2): ``notes_global``.

One vector per live note, private per tenant. Notes are kept out of the
shared transcript collection because chunks there are shared across tenants
(D-063) and notes never are; every query here carries a fail-closed tenant
filter, the ``qa_library_global`` pattern.

What the Q&A agent gets back is chunk-shaped (``{"text", "metadata",
"distance"}``) so it flows through the existing retrieval, re-rank, prompt
and citation machinery. The metadata says what it is:

- ``source_type = "note"``, ``note_id``, ``target_type``, ``target_id``,
  ``target_key`` (``"<type>:<id>"``, what job scoping filters on),
  ``target_label``, ``target_parent_id`` (the job of a ``qa_exchange``),
  ``created_at`` (ISO, UTC) and ``created_date`` (YYYY-MM-DD);
- ``video_title`` = ``"Your note of <date> on <target label>"`` and
  ``channel_name`` = ``"you"``, so the existing ``[Source: "<title>" by
  <channel>]`` citation path cites a note without a special case;
- ``source_id`` = ``"note:<id>"``, so dedupe keys never collide with a
  transcript chunk's.

Withdrawn notes (``deleted_at`` set) are never in the collection: a soft
delete removes the vector (D-074 item 2). Index writes are best-effort and
never fail the note write; the startup backfill repairs anything missed.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone

import chromadb

from app.config import settings
from app.models.note import Note
from app.services import chroma_service, note_service
from app.services.note_service import ResolvedTarget

logger = logging.getLogger(__name__)

NOTE_SOURCE_TYPE = "note"
NOTE_AUTHOR = "you"
_LABEL_MAX = 90
_BATCH = 100


def enabled() -> bool:
    return bool(settings.NOTES_INDEX_ENABLED)


def note_vector_id(note_id: str) -> str:
    return f"note:{note_id}"


def target_key(target_type: str, target_id: str) -> str:
    return f"{target_type}:{target_id}"


def get_notes_collection() -> chromadb.Collection:
    client = chroma_service.get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_NOTES_COLLECTION_NAME,
        metadata={"scope": "notes"},
        embedding_function=chroma_service._get_embedding_function(),
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _clean_label(label: str | None) -> str:
    """A target label safe inside a citation tag: no quotes or brackets (they
    end the tag), single-spaced, bounded."""
    text = re.sub(r'["“”\[\]]', "", label or "")
    text = " ".join(text.split())
    if len(text) > _LABEL_MAX:
        text = text[: _LABEL_MAX - 1].rstrip() + "…"
    return text


def note_title(created_date: str, label: str | None) -> str:
    """What the answer cites a note as. Distinct per date and target, and at
    least ten characters so the citation matcher can find it."""
    clean = _clean_label(label)
    return f"Your note of {created_date} on {clean}" if clean else f"Your note of {created_date}"


def note_metadata(note: Note, target: ResolvedTarget | None) -> dict:
    created = _aware(note.created_at)
    created_date = created.date().isoformat()
    label = target.label if target else None
    meta = {
        "tenant_id": note.tenant_id,
        "source_type": NOTE_SOURCE_TYPE,
        "source_id": note_vector_id(note.id),
        "note_id": note.id,
        "target_type": note.target_type,
        "target_id": note.target_id,
        "target_key": target_key(note.target_type, note.target_id),
        "target_label": _clean_label(label),
        "motivation": note.motivation,
        "created_at": created.isoformat(),
        "created_date": created_date,
        "video_title": note_title(created_date, label),
        "channel_name": NOTE_AUTHOR,
    }
    if target is not None and target.parent_id:
        meta["target_parent_id"] = target.parent_id
    # Chroma metadata values must be scalars and never None.
    return {k: v for k, v in meta.items() if v is not None}


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _upsert(notes: list[Note], targets: dict) -> None:
    if not notes:
        return
    col = get_notes_collection()
    col.upsert(
        ids=[note_vector_id(n.id) for n in notes],
        documents=[n.body_md for n in notes],
        metadatas=[note_metadata(n, targets.get((n.target_type, n.target_id))) for n in notes],
    )


def sync_note(db, note: Note) -> None:
    """Bring the index in line with one note: upsert it if live, remove it
    if withdrawn. Best-effort; logged, never raised."""
    if not enabled():
        return
    try:
        if note.deleted_at is not None:
            remove_note(note.id)
            return
        _upsert([note], note_service.describe_targets(db, [note]))
    except Exception:
        logger.exception("notes index: could not sync note %s", note.id)


def remove_note(note_id: str) -> None:
    if not enabled():
        return
    try:
        get_notes_collection().delete(ids=[note_vector_id(note_id)])
    except Exception:
        logger.exception("notes index: could not remove note %s", note_id)


def backfill(session_factory=None) -> dict[str, int]:
    """Idempotent: upsert every live note, remove every withdrawn one. Runs
    at API startup like the Q&A backfill; safe to run any number of times."""
    if not enabled():
        return {"upserted": 0, "removed": 0}
    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    upserted = removed = 0
    try:
        batch: list[Note] = []
        withdrawn: list[str] = []
        for note in db.query(Note).order_by(Note.id).yield_per(_BATCH):
            if note.deleted_at is not None:
                withdrawn.append(note_vector_id(note.id))
                continue
            batch.append(note)
            if len(batch) >= _BATCH:
                _upsert(batch, note_service.describe_targets(db, batch))
                upserted += len(batch)
                batch = []
        if batch:
            _upsert(batch, note_service.describe_targets(db, batch))
            upserted += len(batch)
        if withdrawn:
            get_notes_collection().delete(ids=withdrawn)
            removed = len(withdrawn)
    finally:
        db.close()
    logger.info("notes index: backfill upserted %d, removed %d", upserted, removed)
    return {"upserted": upserted, "removed": removed}


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def query_notes(
    query_text: str,
    tenant_id: str | None,
    *,
    target_keys: Iterable[str] | None = None,
    n_results: int | None = None,
    distance_threshold: float | None = None,
) -> list[dict]:
    """The tenant's notes nearest to ``query_text``, chunk-shaped.

    Fail-closed: no ``tenant_id`` returns nothing. ``target_keys`` scopes to
    notes on those targets (job Q&A); ``None`` means every note of the tenant
    (library Q&A); an empty list means nothing is in scope. Hits over the raw
    ``distance_threshold`` are dropped before anything else sees them, so the
    note weight can never pull in an off-topic note.
    """
    if not enabled() or not tenant_id:
        return []
    keys = None if target_keys is None else sorted(set(target_keys))
    if keys is not None and not keys:
        return []
    if distance_threshold is None:
        distance_threshold = settings.RAG_DISTANCE_THRESHOLD
    n = n_results or settings.RAG_TOP_K

    where: dict = {"tenant_id": tenant_id}
    if keys is not None:
        where = {"$and": [{"tenant_id": tenant_id}, {"target_key": {"$in": keys}}]}
    try:
        col = get_notes_collection()
        available = col.count()
        if available == 0:
            return []
        res = col.query(
            query_texts=[query_text],
            n_results=min(n, available),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        logger.exception("notes index: query failed; answering without notes")
        return []

    out: list[dict] = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        if dist > distance_threshold:
            continue
        # Defence in depth: never trust the filter alone with private text.
        if (meta or {}).get("tenant_id") != tenant_id:
            logger.error("notes index: dropped a hit from another tenant")
            continue
        out.append({"text": doc, "metadata": dict(meta), "distance": float(dist)})
    return out


def job_target_keys(db, job_id: str, document_ids: Iterable[str]) -> list[str]:
    """What job-scoped Q&A may draw notes from: notes on the job itself, on
    its approved documents and their knowledge reports, on its own Q&A
    answers, and on the channels its documents come from. A note on a
    document reaches every job containing that document (D-074 item 1)."""
    from app.models.document import Document
    from app.models.qa_exchange import QAExchange

    doc_ids = [d for d in dict.fromkeys(document_ids) if d]
    keys = [target_key("job", job_id)]
    for d in doc_ids:
        keys.append(target_key("document", d))
        keys.append(target_key("knowledge_artifact", d))
    keys.extend(
        target_key("qa_exchange", row[0])
        for row in db.query(QAExchange.id).filter(QAExchange.job_id == job_id)
    )
    if doc_ids:
        keys.extend(
            target_key("channel", row[0])
            for row in db.query(Document.channel_id)
            .filter(Document.document_id.in_(doc_ids), Document.channel_id.isnot(None))
            .distinct()
        )
    return keys

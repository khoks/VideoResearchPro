"""Metadata backfills that need no LLM and no re-embedding (T-1.16.1.7, S-1.17.3).

Two passes over what the library already holds, each dry-run by default:

* ``backfill_language_mix`` — ``documents.language_mix`` for documents
  profiled before the column existed, computed from their stored text
  (``language_mix_service.stored_segments``) with the lexicon tagger.
* ``backfill_chunk_temporal_fields`` — the era and numeric publish fields on
  chunks embedded before R3 shipped (2026-10-19), or before their
  document's era was extracted. D-072 deferred this backfill because it
  read as a re-index; it is a metadata-only update, the same operation
  ``chroma_service.backfill_chunk_document_ids`` already runs at startup.

Both are idempotent (a second run finds nothing to change) and resumable (an
interrupted run is finished by running it again). The CLIs are
``scripts/backfill_language_mix.py`` and
``scripts/backfill_chunk_temporal_fields.py``; ``--write`` is the owner's step.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.document import Document
from app.services import language_mix_service, temporal_service
from app.utils.chunking import published_numeric_fields

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# T-1.16.1.7: documents.language_mix
# ---------------------------------------------------------------------------


@dataclass
class LanguageMixReport:
    write: bool
    considered: int = 0
    # A profile was computed (from either store).
    profiled: int = 0
    # The column was set or replaced (would be, in a dry run).
    changed: int = 0
    # The stored profile already equals the computed one.
    unchanged: int = 0
    # Neither the transcript cache nor Chroma holds any text for it.
    no_text: int = 0
    failed: int = 0
    by_origin: Counter = field(default_factory=Counter)
    by_primary: Counter = field(default_factory=Counter)
    # Profiles whose chunks carry `code_mix_*` (the chunker's 3% floor).
    code_mixed: int = 0

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["by_origin"] = dict(self.by_origin)
        data["by_primary"] = dict(self.by_primary)
        return data


def backfill_language_mix(
    db: Session,
    *,
    write: bool = False,
    recompute: bool = False,
    document_ids: Iterable[str] | None = None,
    limit: int | None = None,
    on_row: Callable[[Document, str, dict | None], None] | None = None,
) -> LanguageMixReport:
    """Profile documents that hold text and have no ``language_mix`` yet.

    ``recompute`` also re-profiles documents that already have one (written
    only where the profile differs). Only documents with text are read:
    ``transcript_status == 'fetched'`` or embedded. A dry run computes every
    profile and writes nothing; a write commits each document as it goes,
    so an interrupted run loses nothing and the next one starts where it
    stopped. ``on_row(document, outcome, profile)`` is called per document,
    for the CLI's progress lines.
    """
    from app.services import code_mixing_service

    report = LanguageMixReport(write=write)
    query = db.query(Document).filter(
        or_(Document.transcript_status == "fetched", Document.embedded_in_chroma.is_(True))
    )
    if not recompute:
        query = query.filter(Document.language_mix.is_(None))
    wanted = [d for d in (document_ids or []) if d]
    if wanted:
        query = query.filter(Document.document_id.in_(wanted))
    query = query.order_by(Document.created_at, Document.document_id)
    if limit:
        query = query.limit(limit)

    for document in query.all():
        report.considered += 1
        try:
            segments, origin = language_mix_service.stored_segments(db, document)
            if segments is None:
                report.no_text += 1
                outcome, profile = "no_text", None
            else:
                profile = language_mix_service.compute(segments)
                report.profiled += 1
                report.by_origin[origin] += 1
                report.by_primary[profile.get("primary_language") or "?"] += 1
                if code_mixing_service.chunk_metadata_from_profile(profile):
                    report.code_mixed += 1
                if language_mix_service.load(document) == profile:
                    report.unchanged += 1
                    outcome = "unchanged"
                else:
                    report.changed += 1
                    outcome = "changed"
                    if write:
                        language_mix_service.record(document, profile)
                        db.commit()
        except Exception:
            logger.exception("backfill_language_mix: document %s failed", document.document_id)
            report.failed += 1
            outcome, profile = "failed", None
            db.rollback()
        if on_row is not None:
            on_row(document, outcome, profile)
    logger.info("backfill_language_mix: %s", report.as_dict())
    return report


# ---------------------------------------------------------------------------
# S-1.17.3: era + numeric publish fields on pre-R3 chunks
# ---------------------------------------------------------------------------

TEMPORAL_FIELDS = (
    "era_start", "era_end", "era_confidence", "is_retrospective",
    "published_ts", "published_year",
)


def chunk_temporal_fields(document: Any) -> dict[str, Any]:
    """The temporal fields a chunk of ``document`` carries when chunked today.

    The exact functions ``chunk_transcript`` uses (``era_metadata`` and
    ``published_numeric_fields``), so an old chunk ends up with what a new
    one is written with. Unknown values are absent, never sentinels.
    """
    fields = dict(temporal_service.era_metadata(temporal_service.load_era(document)))
    fields.update(published_numeric_fields(getattr(document, "published_at", None)))
    return fields


def _merge_metadata(stored: dict[str, Any] | None, new_fields: dict[str, Any]) -> dict[str, Any]:
    """The whole metadata to send: what the chunk has, plus the new fields.

    Sent whole so the update is correct whether Chroma merges an update's
    metadata (1.5 does) or replaces it.
    """
    return {**(stored or {}), **new_fields}


def _same(current: Any, target: Any) -> bool:
    if current is None:
        return False
    if isinstance(target, bool) or isinstance(current, bool):
        return isinstance(current, bool) and isinstance(target, bool) and current == target
    if isinstance(target, float) or isinstance(current, float):
        try:
            return math.isclose(float(current), float(target), rel_tol=1e-6, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return current == target


@dataclass
class TemporalReport:
    write: bool
    documents_with_dates: int = 0
    chunks_scanned: int = 0
    # Chunks resolved to a document that has an era or a publish date.
    chunks_matched: int = 0
    # Chunks of a document with neither (nothing to add).
    chunks_undated: int = 0
    # Chunks whose document is not in the table, or not in the requested set.
    chunks_unresolved: int = 0
    chunks_already_current: int = 0
    chunks_to_update: int = 0
    chunks_updated: int = 0
    # Per field: chunks that lacked it, and chunks holding a different value.
    gained: Counter = field(default_factory=Counter)
    changed: Counter = field(default_factory=Counter)
    stopped: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gained"] = {f: self.gained.get(f, 0) for f in TEMPORAL_FIELDS}
        data["changed"] = {f: self.changed.get(f, 0) for f in TEMPORAL_FIELDS}
        return data


def backfill_chunk_temporal_fields(
    db: Session,
    *,
    write: bool = False,
    page_size: int = 1000,
    document_ids: Iterable[str] | None = None,
    collection: Any = None,
) -> TemporalReport:
    """Bring every chunk of a dated document up to its document's temporal fields.

    Pages through the global collection (metadata only), resolves each chunk
    to its document — ``document_id`` metadata first, then ``(source_type,
    source_id)`` and ``video_id`` for a chunk the startup backfill has not
    stamped — and lists the fields that are missing or differ. Nothing is
    ever removed: a field the document does not know is left as the chunk
    has it.

    With ``write``, each batch's metadata is re-read just before the update
    and sent whole (stored metadata plus the new fields). Chroma 1.5 merges
    an ``update``'s metadata into the stored one, so the explicit merge only
    matters on a version that replaces; either way every other key
    (``document_id``, ``code_mix_*``, ``text_en``, timestamps) survives. The
    embedding and the stored text are not touched. The first failed batch
    stops the pass; running it again resumes, because chunks already
    updated compare equal and are skipped.
    """
    report = TemporalReport(write=write)
    if collection is None:
        from app.services import chroma_service

        collection = chroma_service.get_global_collection()

    wanted = {d for d in (document_ids or []) if d}
    query = db.query(Document)
    if wanted:
        query = query.filter(Document.document_id.in_(wanted))
    targets: dict[str, dict[str, Any]] = {}
    known: set[str] = set()
    by_video: dict[str, str] = {}
    by_source: dict[tuple[str, str], str] = {}
    for document in query.all():
        known.add(document.document_id)
        if document.video_id:
            by_video[document.video_id] = document.document_id
        if document.source_id:
            by_source[(document.source_type or "video", document.source_id)] = document.document_id
        fields = chunk_temporal_fields(document)
        if fields:
            targets[document.document_id] = fields
    report.documents_with_dates = len(targets)
    if not targets:
        logger.info("backfill_chunk_temporal_fields: no dated documents; %s", report.as_dict())
        return report

    pending: list[tuple[str, dict[str, Any]]] = []
    offset = 0
    while True:
        try:
            page = collection.get(limit=page_size, offset=offset, include=["metadatas"])
        except Exception as exc:  # noqa: BLE001 — a partial scan writes nothing
            logger.exception("backfill_chunk_temporal_fields: scan failed at offset %d", offset)
            report.stopped = (
                f"scan failed at chunk {offset} ({type(exc).__name__}); nothing written"
            )
            report.chunks_to_update = len(pending)
            return report
        ids = page.get("ids") or []
        if not ids:
            break
        metas = page.get("metadatas") or [None] * len(ids)
        for chunk_id, meta in zip(ids, metas):
            meta = meta or {}
            report.chunks_scanned += 1
            document_id = meta.get("document_id") or by_source.get(
                (str(meta.get("source_type") or "video"), str(meta.get("source_id") or ""))
            ) or by_video.get(str(meta.get("video_id") or ""))
            document_id = str(document_id or "")
            fields = targets.get(document_id)
            if fields is None:
                if document_id in known:
                    report.chunks_undated += 1
                else:
                    report.chunks_unresolved += 1
                continue
            report.chunks_matched += 1
            diff: dict[str, Any] = {}
            for name, value in fields.items():
                if _same(meta.get(name), value):
                    continue
                diff[name] = value
                if meta.get(name) is None:
                    report.gained[name] += 1
                else:
                    report.changed[name] += 1
            if diff:
                pending.append((chunk_id, diff))
            else:
                report.chunks_already_current += 1
        offset += len(ids)
        if len(ids) < page_size:
            break
    report.chunks_to_update = len(pending)

    if write:
        for start in range(0, len(pending), page_size):
            batch = pending[start:start + page_size]
            try:
                current = collection.get(ids=[cid for cid, _ in batch], include=["metadatas"])
                stored = dict(zip(current.get("ids") or [], current.get("metadatas") or []))
                ids_out = [cid for cid, _ in batch if cid in stored]
                metas_out = [
                    _merge_metadata(stored[cid], diff) for cid, diff in batch if cid in stored
                ]
                if ids_out:
                    collection.update(ids=ids_out, metadatas=metas_out)
                report.chunks_updated += len(ids_out)
            except Exception as exc:  # noqa: BLE001 — report and stop; a re-run resumes
                logger.exception(
                    "backfill_chunk_temporal_fields: update failed for the batch at %d", start
                )
                report.stopped = (
                    f"update failed at chunk {start} of {len(pending)} "
                    f"({type(exc).__name__}); run again to resume"
                )
                break

    logger.info("backfill_chunk_temporal_fields: %s", report.as_dict())
    return report

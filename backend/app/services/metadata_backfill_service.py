"""Metadata backfills that need no LLM and no re-embedding (T-1.16.1.7, S-1.17.3).

Three passes over what the library already holds, each dry-run by default:

* ``backfill_language_mix`` — ``documents.language_mix`` for documents
  profiled before the column existed, computed from their stored text
  (``language_mix_service.stored_segments``) with the lexicon tagger.
* ``backfill_chunk_temporal_fields`` — the era and numeric publish fields on
  chunks embedded before R3 shipped (2026-10-19), or before their
  document's era was extracted, with the ``published_at`` display string
  kept in step with the numeric publish fields. D-072 deferred this
  backfill because it read as a re-index; it is a metadata-only update, the
  same operation ``chroma_service.backfill_chunk_document_ids`` already
  runs at startup. ``stamp_chunk_temporal_fields`` is the same update for
  one document, which a job runs when it extracts a reused document's era
  for the first time (T-1.17.3.3).
* ``backfill_chunk_language_fields`` — the document-level ``code_mix_*``
  fields on chunks written before S-1.16.2, from the stored
  ``documents.language_mix`` (T-1.16.2.14).

All are idempotent (a second run finds nothing to change) and resumable (an
interrupted run is finished by running it again). The CLIs are
``scripts/backfill_language_mix.py``,
``scripts/backfill_chunk_temporal_fields.py`` and
``scripts/backfill_chunk_language_fields.py``; ``--write`` is the owner's step.
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
from app.services import code_mixing_service, language_mix_service, temporal_service
from app.utils.chunking import published_at_field, published_numeric_fields

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
    # Profiles that are not plain English by the chunker's 3% rule. Their
    # chunks gain `code_mix_*` only when re-chunked; this pass writes the
    # column, never the chunks.
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
# Shared by the chunk passes: resolve a chunk to its document, diff, write
# ---------------------------------------------------------------------------


@dataclass
class _DocumentIndex:
    """How a chunk finds its document: ``document_id`` metadata first, then
    ``(source_type, source_id)`` and ``video_id`` for a chunk the startup
    backfill has not stamped."""

    known: set[str] = field(default_factory=set)
    by_video: dict[str, str] = field(default_factory=dict)
    by_source: dict[tuple[str, str], str] = field(default_factory=dict)

    def add(self, document: Any) -> None:
        self.known.add(document.document_id)
        if document.video_id:
            self.by_video[document.video_id] = document.document_id
        if document.source_id:
            self.by_source[(document.source_type or "video", document.source_id)] = (
                document.document_id
            )

    def resolve(self, meta: dict[str, Any]) -> str:
        document_id = meta.get("document_id") or self.by_source.get(
            (str(meta.get("source_type") or "video"), str(meta.get("source_id") or ""))
        ) or self.by_video.get(str(meta.get("video_id") or ""))
        return str(document_id or "")


def _scan_chunks(collection: Any, page_size: int, visit: Callable[[str, dict], None], name: str) -> str:
    """Call ``visit(chunk_id, metadata)`` for every chunk, metadata only.

    Returns "" or, when a page could not be read, why the pass stopped: a
    partial scan writes nothing.
    """
    offset = 0
    while True:
        try:
            page = collection.get(limit=page_size, offset=offset, include=["metadatas"])
        except Exception as exc:  # noqa: BLE001 — a partial scan writes nothing
            logger.exception("%s: scan failed at offset %d", name, offset)
            return f"scan failed at chunk {offset} ({type(exc).__name__}); nothing written"
        ids = page.get("ids") or []
        if not ids:
            return ""
        metas = page.get("metadatas") or [None] * len(ids)
        for chunk_id, meta in zip(ids, metas):
            visit(chunk_id, meta or {})
        offset += len(ids)
        if len(ids) < page_size:
            return ""


def _diff_fields(
    fields: dict[str, Any], meta: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """What ``fields`` would change on a chunk: ``(diff, gained, changed)``."""
    diff: dict[str, Any] = {}
    gained: list[str] = []
    changed: list[str] = []
    for name, value in fields.items():
        if _same(name, meta.get(name), value):
            continue
        diff[name] = value
        (gained if _missing(meta.get(name)) else changed).append(name)
    return diff, gained, changed


def _write_pending(
    collection: Any, pending: list[tuple[str, dict[str, Any]]], page_size: int, name: str
) -> tuple[int, str]:
    """Metadata-only updates: ``(chunks updated, why it stopped or "")``.

    Each batch's metadata is re-read just before the update and sent whole
    (stored metadata plus the new fields). Chroma 1.5 merges an ``update``'s
    metadata into the stored one, so the explicit merge only matters on a
    version that replaces; either way every other key (``document_id``,
    ``code_mix_*``, ``text_en``, timestamps) survives. The embedding and the
    stored text are not touched. The first failed batch stops the pass;
    running it again resumes, because chunks already updated compare equal
    and are skipped.
    """
    updated = 0
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
            updated += len(ids_out)
        except Exception as exc:  # noqa: BLE001 — report and stop; a re-run resumes
            logger.exception("%s: update failed for the batch at %d", name, start)
            return updated, (
                f"update failed at chunk {start} of {len(pending)} "
                f"({type(exc).__name__}); run again to resume"
            )
    return updated, ""


# ---------------------------------------------------------------------------
# S-1.17.3: era + numeric publish fields on pre-R3 chunks
# ---------------------------------------------------------------------------

# The fields R3 added to chunks: chunks embedded before it carry none of them.
TEMPORAL_FIELDS = (
    "era_start", "era_end", "era_confidence", "is_retrospective",
    "published_ts", "published_year",
)
# The display date every chunk has carried since before R3 ("" when the
# document was undated at chunk time). The prompts read it, so the pass
# writes it together with its numeric twins: a chunk must never show one
# date and range-filter on another.
PUBLISHED_AT = "published_at"
# Every field the pass may write, as its report counts them.
REPORT_FIELDS = TEMPORAL_FIELDS + (PUBLISHED_AT,)


def chunk_temporal_fields(document: Any) -> dict[str, Any]:
    """The temporal fields a chunk of ``document`` carries when chunked today.

    The exact functions ``chunk_transcript`` uses (``era_metadata``,
    ``published_numeric_fields`` and ``published_at_field``), so an old chunk
    ends up with what a new one is written with. Unknown values are absent,
    never sentinels; ``published_at`` is included exactly when the numeric
    publish fields are, so the three always move together.
    """
    fields = dict(temporal_service.era_metadata(temporal_service.load_era(document)))
    published_at = getattr(document, "published_at", None)
    numeric = published_numeric_fields(published_at)
    if numeric:
        fields.update(numeric)
        fields[PUBLISHED_AT] = published_at_field(published_at)
    return fields


def _merge_metadata(stored: dict[str, Any] | None, new_fields: dict[str, Any]) -> dict[str, Any]:
    """The whole metadata to send: what the chunk has, plus the new fields.

    Sent whole so the update is correct whether Chroma merges an update's
    metadata (1.5 does) or replaces it.
    """
    return {**(stored or {}), **new_fields}


def _missing(value: Any) -> bool:
    # The chunker writes "" for an unknown `published_at`; every other
    # temporal field is simply absent.
    return value is None or value == ""


def _same(name: str, current: Any, target: Any) -> bool:
    if _missing(current):
        return False
    if name == PUBLISHED_AT:
        # The same instant, however the string is spelled (a date-only or
        # `Z`-suffixed value is not rewritten just for its format).
        return published_numeric_fields(current) == published_numeric_fields(target)
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
        data["gained"] = {f: self.gained.get(f, 0) for f in REPORT_FIELDS}
        data["changed"] = {f: self.changed.get(f, 0) for f in REPORT_FIELDS}
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
    to its document and lists the fields that are missing or differ. Nothing
    is ever removed: a field the document does not know is left as the chunk
    has it. ``published_at`` is rewritten with ``published_ts`` /
    ``published_year`` whenever the document's date is known and the chunk's
    string names a different instant (or none), so the date the prompts show
    and the one a range filter reads always agree. With ``write`` the
    differences go through ``_write_pending``.
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
    index = _DocumentIndex()
    for document in query.all():
        index.add(document)
        fields = chunk_temporal_fields(document)
        if fields:
            targets[document.document_id] = fields
    report.documents_with_dates = len(targets)
    if not targets:
        logger.info("backfill_chunk_temporal_fields: no dated documents; %s", report.as_dict())
        return report

    pending: list[tuple[str, dict[str, Any]]] = []

    def visit(chunk_id: str, meta: dict[str, Any]) -> None:
        report.chunks_scanned += 1
        document_id = index.resolve(meta)
        fields = targets.get(document_id)
        if fields is None:
            if document_id in index.known:
                report.chunks_undated += 1
            else:
                report.chunks_unresolved += 1
            return
        report.chunks_matched += 1
        diff, gained, changed = _diff_fields(fields, meta)
        report.gained.update(gained)
        report.changed.update(changed)
        if diff:
            pending.append((chunk_id, diff))
        else:
            report.chunks_already_current += 1

    report.stopped = _scan_chunks(collection, page_size, visit, "backfill_chunk_temporal_fields")
    report.chunks_to_update = len(pending)
    if report.stopped:
        return report

    if write:
        report.chunks_updated, report.stopped = _write_pending(
            collection, pending, page_size, "backfill_chunk_temporal_fields"
        )

    logger.info("backfill_chunk_temporal_fields: %s", report.as_dict())
    return report


def stamp_chunk_temporal_fields(document: Any, *, collection: Any = None, page_size: int = 1000) -> int:
    """The same update for one document's chunks (T-1.17.3.3). Returns how many changed.

    A job that reuses an embedded document re-chunks it without re-inserting,
    so an era extracted on that run would otherwise reach the stored chunks
    only at the next backfill. Reads the document's chunks by ``document_id``
    (then ``video_id``, like ``chroma_service.get_document_chunks``) instead
    of scanning the collection. Raises on a Chroma read error and logs a
    failed write; the caller decides what that means for its job.
    """
    fields = chunk_temporal_fields(document)
    if not fields:
        return 0
    if collection is None:
        from app.services import chroma_service

        collection = chroma_service.get_global_collection()
    got = collection.get(where={"document_id": document.document_id}, include=["metadatas"])
    video_id = getattr(document, "video_id", None)
    if not (got.get("ids") or []) and video_id:
        got = collection.get(where={"video_id": video_id}, include=["metadatas"])
    ids = got.get("ids") or []
    metas = got.get("metadatas") or [None] * len(ids)
    pending = []
    for chunk_id, meta in zip(ids, metas):
        diff, _, _ = _diff_fields(fields, meta or {})
        if diff:
            pending.append((chunk_id, diff))
    updated, _ = _write_pending(collection, pending, page_size, "stamp_chunk_temporal_fields")
    return updated


# ---------------------------------------------------------------------------
# T-1.16.2.14: document-level code_mix_* on chunks written before S-1.16.2
# ---------------------------------------------------------------------------


@dataclass
class LanguageFieldsReport:
    write: bool
    # Documents with a stored `language_mix`, and those it says are not plain
    # English: only those have fields to stamp.
    documents_profiled: int = 0
    documents_code_mixed: int = 0
    chunks_scanned: int = 0
    chunks_matched: int = 0
    # Chunks of a document profiled as plain English (nothing to add), of a
    # document with no stored profile (run backfill_language_mix.py first),
    # and of no document in scope.
    chunks_plain_english: int = 0
    chunks_unprofiled: int = 0
    chunks_unresolved: int = 0
    # Plain-English chunks still carrying `code_mix_*`: a refreshed profile
    # no longer agrees with them. The pass removes nothing, so they stay.
    chunks_stale: int = 0
    chunks_already_current: int = 0
    chunks_to_update: int = 0
    chunks_updated: int = 0
    # Chunks of a code-mixed document with no English rendering. Their fields
    # tell every prompt the source's language; their vectors stay those of
    # the original text (D-084): rendering takes an LLM and a re-embed.
    chunks_embedded_as_original: int = 0
    gained: Counter = field(default_factory=Counter)
    changed: Counter = field(default_factory=Counter)
    stopped: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gained"] = {f: self.gained.get(f, 0) for f in LANGUAGE_FIELDS}
        data["changed"] = {f: self.changed.get(f, 0) for f in LANGUAGE_FIELDS}
        return data


# What `chunk_metadata_from_profile` writes. The per-chunk `code_mix_chunk_*`
# fields are not document-level and are left to chunking.
LANGUAGE_FIELDS = (
    "code_mix_primary", "code_mix_script", "code_mix_share",
    "code_mix_matrix_share", "code_mix_quote",
)


def chunk_language_fields(profile: dict[str, Any] | None) -> dict[str, Any]:
    """The document-level fields a chunk carries for this stored profile.

    ``chunk_metadata_from_profile``, the function chunking uses, so an old
    chunk ends up with what a new one is written with. Empty for plain
    English and for a missing profile. A blank value is left out: it would
    compare as missing on every run.
    """
    fields = code_mixing_service.chunk_metadata_from_profile(profile)
    return {name: value for name, value in fields.items() if value != ""}


def backfill_chunk_language_fields(
    db: Session,
    *,
    write: bool = False,
    page_size: int = 1000,
    document_ids: Iterable[str] | None = None,
    collection: Any = None,
) -> LanguageFieldsReport:
    """Stamp each chunk of a code-mixed document from ``documents.language_mix``.

    Metadata only, through ``_write_pending``: nothing is re-embedded and no
    LLM runs, so a chunk written before D-084 keeps the vector of its
    original text (``chunks_embedded_as_original`` counts them). A chunk
    holding a different value is brought up to the stored profile, which is
    how a refreshed profile reaches its chunks. Nothing is removed: a
    document now profiled as plain English keeps what its chunks carry, and
    ``chunks_stale`` reports it.
    """
    report = LanguageFieldsReport(write=write)
    if collection is None:
        from app.services import chroma_service

        collection = chroma_service.get_global_collection()

    wanted = {d for d in (document_ids or []) if d}
    query = db.query(Document)
    if wanted:
        query = query.filter(Document.document_id.in_(wanted))
    index = _DocumentIndex()
    profiled: set[str] = set()
    targets: dict[str, dict[str, Any]] = {}
    for document in query.all():
        index.add(document)
        profile = language_mix_service.load(document)
        if profile is None:
            continue
        profiled.add(document.document_id)
        fields = chunk_language_fields(profile)
        if fields:
            targets[document.document_id] = fields
    report.documents_profiled = len(profiled)
    report.documents_code_mixed = len(targets)

    pending: list[tuple[str, dict[str, Any]]] = []

    def visit(chunk_id: str, meta: dict[str, Any]) -> None:
        report.chunks_scanned += 1
        document_id = index.resolve(meta)
        fields = targets.get(document_id)
        if fields is None:
            if document_id in profiled:
                report.chunks_plain_english += 1
                report.chunks_stale += 1 if meta.get("code_mix_primary") else 0
            elif document_id in index.known:
                report.chunks_unprofiled += 1
            else:
                report.chunks_unresolved += 1
            return
        report.chunks_matched += 1
        report.chunks_embedded_as_original += 0 if meta.get("text_en") else 1
        diff, gained, changed = _diff_fields(fields, meta)
        report.gained.update(gained)
        report.changed.update(changed)
        if diff:
            pending.append((chunk_id, diff))
        else:
            report.chunks_already_current += 1

    report.stopped = _scan_chunks(collection, page_size, visit, "backfill_chunk_language_fields")
    report.chunks_to_update = len(pending)
    if report.stopped:
        return report

    if write:
        report.chunks_updated, report.stopped = _write_pending(
            collection, pending, page_size, "backfill_chunk_language_fields"
        )

    logger.info("backfill_chunk_language_fields: %s", report.as_dict())
    return report

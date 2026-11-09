"""Documents flagged ``embedded_in_chroma`` with no chunk in the library (T-5.2.24).

Until PR #440 (D-161) both extraction loops committed ``embedded_in_chroma``
as each document was chunked, while its chunks reached Chroma only at the RAG
build. A run stopped between the two (a cancel, a route failing the row, an
exception) left documents flagged with no chunks. Before D-070 (2026-10-19)
``insert_chunks`` also skipped every chunk without a ``video_id``, and the
upload, paste and job paths flagged those documents all the same. A job that
selects a flagged document whose text is in ``transcript_cache`` takes it as
fully reused: it re-chunks the text for the report and inserts nothing. So no
job or library Q&A, for any tenant, retrieves it.

``check_embedded_flags`` finds them. It reads every document and the global
collection's metadata (never a chunk's text, never an embedding), and a
document counts as having chunks when any chunk names it:

* by its ``document_id`` metadata, which every chunk written since
  2026-10-19 carries;
* by ``(source_type, source_id)`` or ``video_id`` metadata, for a chunk the
  startup backfill (``chroma_service.backfill_chunk_document_ids``) has not
  stamped yet;
* by its id, ``{video_id}:{index}`` for a YouTube document and
  ``{document_id}:{index}`` for every other one (``_chunk_storage_key``).

Every route that can say "this document has chunks" is taken, because the
mistake that costs something is the other one: a flag cleared on a document
that has chunks only makes the next job re-insert them in place, but a
document wrongly counted as embedded stays out of retrieval.

The documents found are sorted by where their text lives, which decides what
brings them back:

* ``cached`` — ``transcript_cache`` holds their text. Unflagged, the next job
  that selects one (after an approval, or a subscription sync) re-chunks it
  from there and inserts it, with no fetch, and flags it once it is in.
* ``fetch_again`` — no usable cached text: their text lived only in the
  chunks that never reached Chroma (PDFs, pasted pages, threads and podcast
  episodes cached theirs nowhere before ``job_tasks._cache_document_text``;
  see ``document_text_service``). Only a fresh fetch brings it back. A job
  that selects one already fetches it again, flagged or not, because a flagged
  document with no cached text falls through to a fetch; a PDF or a pasted
  page is selected by no job, and its re-upload or re-paste is a dedup hit
  that embeds nothing. Clearing the flag makes it say what is true.
* ``empty`` — cached text with no words. There is nothing to embed, and the
  next job would flag it again, so ``write`` leaves these alone.

A dry run writes nothing (the CLI also holds its session read-only).
``write`` clears the flag on the ``cached`` and ``fetch_again`` documents,
each re-checked against Chroma just before the write, so one a job embedded
since the scan keeps its flag. Nothing in Chroma changes. A scan that stops
part-way, or a collection none of whose chunks belongs to a document in this
database (the wrong ``DATABASE_URL`` or ``CHROMA_PERSIST_DIR``), writes
nothing: either would make documents with chunks look chunkless. The CLI is
``scripts/check_embedded_flags.py``; ``--write`` is the owner's step.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import chroma_service
from app.services.metadata_backfill_service import _DocumentIndex, _scan_chunks

logger = logging.getLogger(__name__)

BUCKET_CACHED = "cached"
BUCKET_FETCH_AGAIN = "fetch_again"
BUCKET_EMPTY = "empty"
BUCKETS = (BUCKET_CACHED, BUCKET_FETCH_AGAIN, BUCKET_EMPTY)
# What ``write`` clears. An empty document has nothing to embed.
CLEARED_BUCKETS = (BUCKET_CACHED, BUCKET_FETCH_AGAIN)

# Ids per IN (...) list: well under SQLite's bound-parameter limit.
_ID_BATCH = 500


@dataclass
class FlagCheckReport:
    write: bool
    collection: str = ""
    chunks_scanned: int = 0
    # Chunks that name no document in this database (their document was
    # deleted, or the store belongs to another database). Left alone.
    chunks_of_no_document: int = 0
    # Documents in scope flagged embedded, and how many of those have chunks.
    flagged: int = 0
    flagged_with_chunks: int = 0
    # Not flagged, yet chunks name them. Harmless (the next job that selects
    # one inserts in place) and left alone; reported so the two counts add up.
    unflagged_with_chunks: int = 0
    # source_type -> {"flagged", "with_chunks", "cached", "fetch_again", "empty"}
    by_source: dict[str, Counter] = field(default_factory=dict)
    # bucket -> [{"document_id", "source_type", "video_id"}]: ids, never text.
    found: dict[str, list[dict[str, str]]] = field(
        default_factory=lambda: {bucket: [] for bucket in BUCKETS}
    )
    to_clear: int = 0
    cleared: int = 0
    # Chunks named them by the time of the write: a job embedded them since.
    kept_on_recheck: int = 0
    stopped: str = ""

    def without_chunks(self) -> int:
        return sum(len(rows) for rows in self.found.values())

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["by_source"] = {k: dict(v) for k, v in sorted(self.by_source.items())}
        data["without_chunks"] = self.without_chunks()
        return data


def _owner_of_chunk_id(chunk_id: str, index: _DocumentIndex) -> str:
    """The document a chunk id names: ``{video_id}:{n}`` or ``{document_id}:{n}``."""
    if ":" not in chunk_id:
        return ""
    key = chunk_id.rsplit(":", 1)[0]
    if key in index.known:
        return key
    return index.by_video.get(key, "")


def _open_collection() -> Any:
    """The global collection, read as it is: never created, and with no
    embedding model loaded, since only metadata is read."""
    return chroma_service.get_chroma_client().get_collection(
        name=settings.CHROMA_GLOBAL_COLLECTION_NAME, embedding_function=None
    )


def _text_state(segments_json: str | None) -> str:
    """``cached``, ``empty`` or ``fetch_again`` for one cache row's segments,
    read as ``job_tasks._load_cached_segments`` reads them: a missing or
    corrupt row is no text."""
    if segments_json is None:
        return BUCKET_FETCH_AGAIN
    try:
        segments = json.loads(segments_json)
    except (TypeError, ValueError):
        return BUCKET_FETCH_AGAIN
    if not isinstance(segments, list):
        return BUCKET_FETCH_AGAIN
    for segment in segments:
        if isinstance(segment, dict) and str(segment.get("text") or "").strip():
            return BUCKET_CACHED
    return BUCKET_EMPTY


def _text_states(db: Session, documents: list[Any]) -> dict[str, str]:
    """Each document's bucket, from its cache row: by ``document_id``, else by
    the legacy ``video_id``, the order ``_load_cached_segments`` looks in.
    Columns, not rows: no cached text is left in the session."""
    ids = [d.document_id for d in documents]
    video_ids = [d.video_id for d in documents if d.video_id]
    by_document: dict[str, str] = {}
    by_video: dict[str, str] = {}
    for start in range(0, len(ids), _ID_BATCH):
        for document_id, segments_json in db.query(
            TranscriptCache.document_id, TranscriptCache.segments_json
        ).filter(TranscriptCache.document_id.in_(ids[start:start + _ID_BATCH])):
            by_document[document_id] = _text_state(segments_json)
    for start in range(0, len(video_ids), _ID_BATCH):
        for video_id, segments_json in db.query(
            TranscriptCache.video_id, TranscriptCache.segments_json
        ).filter(TranscriptCache.video_id.in_(video_ids[start:start + _ID_BATCH])):
            by_video.setdefault(video_id, _text_state(segments_json))
    return {
        d.document_id: by_document.get(d.document_id)
        or (by_video.get(d.video_id) if d.video_id else None)
        or BUCKET_FETCH_AGAIN
        for d in documents
    }


def _has_chunks_now(collection: Any, document_id: str, video_id: str | None) -> bool:
    """Whether any chunk names the document now, by metadata or by id."""
    if collection.get(where={"document_id": document_id}, limit=1, include=[]).get("ids"):
        return True
    if video_id and collection.get(where={"video_id": video_id}, limit=1, include=[]).get("ids"):
        return True
    keys = [key for key in (video_id, document_id) if key]
    return bool(collection.get(ids=[f"{key}:0" for key in keys], include=[]).get("ids"))


def check_embedded_flags(
    db: Session,
    *,
    write: bool = False,
    page_size: int = 1000,
    document_ids: Iterable[str] | None = None,
) -> FlagCheckReport:
    """Find documents flagged embedded with no chunk; with ``write``, unflag them.

    ``document_ids`` narrows which documents are checked; the whole
    collection is still scanned, since any chunk may name them. A dry run
    leaves the session with nothing to commit.
    """
    report = FlagCheckReport(write=write, collection=settings.CHROMA_GLOBAL_COLLECTION_NAME)
    try:
        collection = _open_collection()
    except Exception as exc:  # noqa: BLE001 — reported; nothing to read
        logger.exception("check_embedded_flags: could not open the global collection")
        report.stopped = (
            f"could not open the collection {report.collection} "
            f"({type(exc).__name__}); nothing read, nothing written"
        )
        return report

    rows = db.query(
        Document.document_id, Document.video_id, Document.source_type,
        Document.source_id, Document.embedded_in_chroma,
    ).all()
    index = _DocumentIndex()
    for row in rows:
        index.add(row)

    named: set[str] = set()

    def visit(chunk_id: str, meta: dict) -> None:
        report.chunks_scanned += 1
        owners = {index.resolve(meta), _owner_of_chunk_id(chunk_id, index)} - {""}
        named.update(owners)
        if not owners & index.known:
            report.chunks_of_no_document += 1

    report.stopped = _scan_chunks(collection, page_size, visit, "check_embedded_flags")
    if report.stopped:
        return report

    wanted = {d for d in (document_ids or []) if d}
    stranded = []
    for row in rows:
        if wanted and row.document_id not in wanted:
            continue
        has_chunks = row.document_id in named
        source = report.by_source.setdefault(row.source_type or "video", Counter())
        if not row.embedded_in_chroma:
            if has_chunks:
                report.unflagged_with_chunks += 1
            continue
        report.flagged += 1
        source["flagged"] += 1
        if has_chunks:
            report.flagged_with_chunks += 1
            source["with_chunks"] += 1
        else:
            stranded.append(row)
    report.by_source = {k: v for k, v in report.by_source.items() if v}

    states = _text_states(db, stranded)
    for row in stranded:
        bucket = states[row.document_id]
        report.by_source[row.source_type or "video"][bucket] += 1
        report.found[bucket].append({
            "document_id": row.document_id,
            "source_type": row.source_type or "video",
            "video_id": row.video_id or "",
        })
    report.to_clear = sum(len(report.found[b]) for b in CLEARED_BUCKETS)

    if report.chunks_scanned and report.chunks_scanned == report.chunks_of_no_document:
        report.stopped = (
            f"none of the {report.chunks_scanned} chunks in {report.collection} belongs to a "
            "document in this database; check DATABASE_URL and CHROMA_PERSIST_DIR. "
            "Nothing written"
        )
        return report
    if write and report.to_clear:
        _clear(db, collection, report)
    logger.info(
        "check_embedded_flags: %d flagged, %d without chunks, %d cleared",
        report.flagged, report.without_chunks(), report.cleared,
    )
    return report


def _clear(db: Session, collection: Any, report: FlagCheckReport) -> None:
    """Unflag what the scan found, each re-checked against Chroma first."""
    candidates = [row for b in CLEARED_BUCKETS for row in report.found[b]]
    for start in range(0, len(candidates), _ID_BATCH):
        batch = candidates[start:start + _ID_BATCH]
        clear_ids = []
        try:
            for row in batch:
                if _has_chunks_now(collection, row["document_id"], row["video_id"] or None):
                    report.kept_on_recheck += 1
                else:
                    clear_ids.append(row["document_id"])
        except Exception as exc:  # noqa: BLE001 — stop; what was cleared stays cleared
            logger.exception("check_embedded_flags: re-check failed")
            report.stopped = (
                f"re-check against Chroma failed ({type(exc).__name__}) after "
                f"{report.cleared} cleared; run again to finish"
            )
            return
        if clear_ids:
            report.cleared += (
                db.query(Document)
                .filter(Document.document_id.in_(clear_ids), Document.embedded_in_chroma.is_(True))
                .update({Document.embedded_in_chroma: False}, synchronize_session=False)
            )
            db.commit()

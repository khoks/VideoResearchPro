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
  chunks that never reached Chroma (PDFs and pasted pages keep theirs nowhere
  else, and threads and podcast episodes did not before
  ``job_tasks._cache_document_text``; see ``document_text_service``). Only a
  fresh fetch brings it back. A job that selects one already fetches it
  again, flagged or not, because a flagged document with no cached text falls
  through to a fetch. A PDF is selected by no job, a pasted page only when a
  search finds the same page, and a re-upload or re-paste is a dedup hit that
  embeds nothing. Clearing the flag makes it say what is true.
* ``empty`` — cached text with no words. There is nothing to embed, and the
  next job would flag it again, so ``write`` leaves these alone.

A dry run writes nothing (the CLI also holds its session read-only).
``write`` clears the flag on the ``cached`` and ``fetch_again`` documents,
each re-checked against Chroma just before the write, so one a job embedded
since the scan keeps its flag. Nothing in Chroma changes. A scan that stops
part-way, a collection none of whose chunks belongs to a document in this
database (the wrong ``DATABASE_URL`` or ``CHROMA_PERSIST_DIR``), or a
collection with no chunks at all while documents are flagged, writes nothing:
each would make documents with chunks look chunkless. The empty one is the
likeliest form of the mistake, because the API's startup creates the
configured collection (``get_or_create_collection``): an install that
embedded under the legacy ``videoresearchpro_global`` and lost its
``CHROMA_GLOBAL_COLLECTION_NAME`` pin, or an API started from another working
directory, leaves an empty collection for this check to read. A store that
really was emptied is cleared only with ``empty_store_ok``.

The configured collection is not always the only one holding the library's
chunks (T-5.2.26). After a lost pin the app embeds new documents into an
empty ``pratidhvani_global`` while most of the library still sits in
``videoresearchpro_global``; a few chunks of this database then pass every
guard above, and every document whose chunks are only in the other
collection looks chunkless. So the check also lists the store's collections
and reads every other one, metadata only (never created, no embedding model
loaded). Any collection holding chunks of this database's documents stops the
write, and the dry run, whatever ``empty_store_ok`` says: the owner points
``CHROMA_GLOBAL_COLLECTION_NAME`` at the collection that holds the library,
or migrates the chunks into one collection (docs/migration-code-identifiers.md,
section A). Two tests tell a chunk collection from the app's others:

* by name, the Q&A, notes, shares and personal-context collections, under
  their configured names, are never read. They hold rows of other kinds,
  some naming a document (a note's target), and Echo's hold a tenant's
  private rows.
* by shape, a row of any other collection counts only when it is a chunk of
  a document here: its id is ``{video_id}:{n}`` or ``{document_id}:{n}``, or
  its metadata names the document and carries an integer ``chunk_index``,
  as every chunk the chunker writes (and the old per-job collections' chunks)
  does. A Q&A exchange (``qa:{id}``), a note (``note:{id}``), a share or a
  personal-context row has neither, so a renamed setting's old collection
  does not stop the check.

The CLI is ``scripts/check_embedded_flags.py``; ``--write`` is the owner's
step.
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
from app.services import chroma_service, echo_vectors
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
class OtherCollection:
    """A collection in the store besides the configured one, as read."""

    name: str
    rows_scanned: int = 0
    # Rows shaped as chunks of a document in this database.
    chunks_of_this_database: int = 0
    # The documents of this database those chunks name...
    documents: int = 0
    # ...of which no chunk of the configured collection names...
    documents_only_here: int = 0
    # ...and the flagged ones a write would have cleared.
    documents_to_clear: int = 0


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
    # Every other collection read, by name. One whose chunks name a document
    # of this database stops the write (T-5.2.26).
    other_collections: list[OtherCollection] = field(default_factory=list)
    # The app's collections of other kinds, by their configured names: not read.
    other_kinds: list[str] = field(default_factory=list)
    stopped: str = ""

    def without_chunks(self) -> int:
        return sum(len(rows) for rows in self.found.values())

    def holding_this_database(self) -> list[OtherCollection]:
        return [entry for entry in self.other_collections if entry.documents]

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


def _other_kind_names() -> set[str]:
    """The app's collections that hold rows of other kinds, by their
    configured names: Q&A exchanges, notes, and Echo's (shares, personal
    context; ``echo_collection_names`` lists every one)."""
    return {
        settings.CHROMA_QA_COLLECTION_NAME,
        settings.CHROMA_NOTES_COLLECTION_NAME,
        *echo_vectors.echo_collection_names(),
    }


def _is_chunk_index(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return isinstance(value, float) and value.is_integer() and value >= 0


def _chunk_owner(chunk_id: str, meta: dict, index: _DocumentIndex) -> str:
    """The document of this database a row of another collection is a chunk
    of, or "". A chunk is told by its shape: its id is ``{key}:{n}`` with
    ``key`` a document's ``video_id`` or ``document_id``, or its metadata
    names a document and carries an integer ``chunk_index``. A note naming
    a document has neither (``note:{id}``, no ``chunk_index``)."""
    _, sep, suffix = chunk_id.rpartition(":")
    if sep and suffix.isdigit():
        owner = _owner_of_chunk_id(chunk_id, index)
        if owner:
            return owner
    if _is_chunk_index(meta.get("chunk_index")):
        owner = index.resolve(meta)
        if owner in index.known:
            return owner
    return ""


def _scan_other_collections(
    report: FlagCheckReport, index: _DocumentIndex, page_size: int
) -> tuple[dict[str, set[str]], str]:
    """Read every collection in the store besides the configured one and
    the app's collections of other kinds, metadata only: never created, no
    embedding model loaded. Returns ``({name: documents its chunks name},
    "")``, or why the pass stopped: one unread collection is a doubt."""
    client = chroma_service.get_chroma_client()
    try:
        listed = client.list_collections()
    except Exception as exc:  # noqa: BLE001 — a doubt: nothing written
        logger.exception("check_embedded_flags: could not list the store's collections")
        return {}, f"could not list the store's collections ({type(exc).__name__}); nothing written"
    other_kinds = _other_kind_names()
    named_by: dict[str, set[str]] = {}
    for name in sorted({c if isinstance(c, str) else c.name for c in listed}):
        if name == report.collection:
            continue
        if name in other_kinds:
            report.other_kinds.append(name)
            continue
        entry = OtherCollection(name=name)
        report.other_collections.append(entry)
        try:
            collection = client.get_collection(name=name, embedding_function=None)
        except Exception as exc:  # noqa: BLE001 — a doubt: nothing written
            logger.exception("check_embedded_flags: could not open another collection")
            return named_by, f"could not open the collection {name} ({type(exc).__name__}); nothing written"
        documents: set[str] = set()

        def visit(chunk_id: str, meta: dict, entry: OtherCollection = entry,
                  documents: set[str] = documents) -> None:
            entry.rows_scanned += 1
            owner = _chunk_owner(chunk_id, meta, index)
            if owner:
                entry.chunks_of_this_database += 1
                documents.add(owner)

        stopped = _scan_chunks(collection, page_size, visit, "check_embedded_flags")
        if stopped:
            return named_by, f"reading {name}: {stopped}"
        entry.documents = len(documents)
        named_by[name] = documents
    return named_by, ""


def _held_elsewhere(report: FlagCheckReport) -> str:
    """Why a write stops while other collections hold chunks of this database."""
    listed = "; ".join(
        f"{entry.name} holds chunks of {entry.documents} document(s) of this database, "
        f"{entry.documents_only_here} of them named by no chunk in {report.collection}"
        for entry in report.holding_this_database()
    )
    return (
        f"{listed}. This check reads {report.collection} alone, so a document whose "
        "chunks sit only elsewhere would look chunkless. Point CHROMA_GLOBAL_COLLECTION_NAME "
        "at the collection that holds the library, or migrate the chunks into one collection "
        "and delete the other once Q&A answers from it (docs/migration-code-identifiers.md, "
        "section A). Nothing written"
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
    empty_store_ok: bool = False,
) -> FlagCheckReport:
    """Find documents flagged embedded with no chunk; with ``write``, unflag them.

    ``document_ids`` narrows which documents are checked; the whole
    collection is still scanned, since any chunk may name them. A dry run
    leaves the session with nothing to commit. A collection with no chunks
    while documents are flagged stops the check unless ``empty_store_ok``
    says the store really was emptied. Another collection holding chunks of
    this database's documents stops it whatever ``empty_store_ok`` says.
    """
    report = FlagCheckReport(write=write, collection=settings.CHROMA_GLOBAL_COLLECTION_NAME)
    rows = db.query(
        Document.document_id, Document.video_id, Document.source_type,
        Document.source_id, Document.embedded_in_chroma,
    ).all()
    index = _DocumentIndex()
    for row in rows:
        index.add(row)

    try:
        collection = _open_collection()
    except Exception as exc:  # noqa: BLE001 — reported; nothing to check against
        logger.exception("check_embedded_flags: could not open the global collection")
        report.stopped = (
            f"could not open the collection {report.collection} "
            f"({type(exc).__name__}); nothing written"
        )
        # Where the library is, when the pin names a collection that is not there.
        _, unread = _scan_other_collections(report, index, page_size)
        if not unread and report.holding_this_database():
            report.stopped += ". " + _held_elsewhere(report)
        return report

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
    named_elsewhere, unread = _scan_other_collections(report, index, page_size)

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
    to_clear_ids = {row["document_id"] for b in CLEARED_BUCKETS for row in report.found[b]}
    for entry in report.other_collections:
        documents = named_elsewhere.get(entry.name, set())
        entry.documents_only_here = len(documents - named)
        entry.documents_to_clear = len(documents & to_clear_ids)

    if unread:
        report.stopped = unread
        return report
    if report.holding_this_database():
        report.stopped = _held_elsewhere(report)
        return report
    if report.chunks_scanned and report.chunks_scanned == report.chunks_of_no_document:
        report.stopped = (
            f"none of the {report.chunks_scanned} chunks in {report.collection} belongs to a "
            "document in this database; check DATABASE_URL and CHROMA_PERSIST_DIR. "
            "Nothing written"
        )
        return report
    if not report.chunks_scanned and report.flagged and not empty_store_ok:
        report.stopped = (
            f"{report.collection} holds no chunks, yet {report.flagged} document(s) are flagged "
            "embedded; check CHROMA_GLOBAL_COLLECTION_NAME (an install that embedded before "
            "T-2.6.1 keeps its chunks in videoresearchpro_global) and CHROMA_PERSIST_DIR. "
            "Nothing written. If the store really was emptied, run again with --empty-store-ok"
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

"""ChromaDB service: global-collection model.

Pratidhvani stores every transcript chunk in a single shared ChromaDB
collection — ``settings.CHROMA_GLOBAL_COLLECTION_NAME`` (default
``pratidhvani_global`` as of T-2.6.1, 2026-04-28; the legacy default
``videoresearchpro_global`` was renamed in alignment with the project
brand and the post-OQ-11 dev-environment reset, which made the rename
risk-free in dev. Self-hosters with accumulated embeddings under the
legacy name should follow the migration runbook in T-2.6.6 — short
version: copy the legacy collection's documents into a fresh
``pratidhvani_global`` collection, or pin the legacy name via the env
var ``CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global``).
Documents are globally deduplicated: a given source's chunks are
indexed exactly once and re-used across any job that references the
source. The former per-job collection model has been retired.

Query scoping is performed via ChromaDB metadata filtering on ``video_id``:

* Job-scoped query  -> ``query_collection(..., video_ids=[...])`` passes the
  list as a ``{"video_id": {"$in": [...]}}`` ``where`` clause.
* Library-wide query -> ``query_collection(..., video_ids=None)`` omits the
  ``where`` clause and searches the whole collection.

Chunk IDs are derived as ``"{video_id}:{chunk_index}"`` and inserts use
``collection.upsert`` so repeated extraction of the same video is idempotent
— re-running an extraction overwrites existing chunks in place rather than
creating duplicates.

Q&A library collection
----------------------
In addition to the transcript-chunk global collection, a second collection
(``settings.CHROMA_QA_COLLECTION_NAME``, default ``qa_library_global``)
indexes every Q&A exchange — job-scoped, library-scoped, and future
history-chat turns — one document per exchange, keyed by ``f"qa:{id}"``.
See ``get_qa_collection``, ``upsert_qa_exchange``, ``query_qa_collection``,
and ``backfill_qa_library``.

Embedding model
---------------
Uses ``settings.EMBEDDING_MODEL_NAME`` (default
``paraphrase-multilingual-MiniLM-L12-v2``) via a cached
``SentenceTransformerEmbeddingFunction``. The same embedding function must be
passed on every ``get_or_create_collection`` / ``get_collection`` call so the
collection is opened with the same embedder it was created with.

Concurrency note
----------------
``PersistentClient`` holds an exclusive handle on the underlying SQLite
database, so only one client instance may exist per process. This is safe
for the current Celery topology (``--pool=solo`` on Windows, one worker =
one process). Running prefork/threads/gevent/eventlet pools, or multiple
worker processes sharing this persist directory, will fail with "An
instance of Chroma already exists" or SQLite lock errors. Switch to
``HttpClient`` against a dedicated chroma-server if concurrency > 1 is
required.
"""

from __future__ import annotations

import json
import logging
import warnings
from typing import Any, Literal

import chromadb
from chromadb.utils import embedding_functions

from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None

# A collection must be opened with the same embedding function it was
# created with, so we cache one instance and reuse it for every
# get_or_create_collection / get_collection call.
_embedding_function: embedding_functions.SentenceTransformerEmbeddingFunction | None = None

_BATCH_SIZE = 100


def get_chroma_client() -> chromadb.ClientAPI:
    """Return the process-level singleton ChromaDB client."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return _client


def _get_embedding_function() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """Return the process-level singleton embedding function.

    Uses ``settings.EMBEDDING_MODEL_NAME`` (multilingual by default so
    non-English transcripts embed meaningfully).
    """
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.EMBEDDING_MODEL_NAME,
        )
    return _embedding_function


def get_global_collection() -> chromadb.Collection:
    """Return the single global collection, creating it if missing."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_GLOBAL_COLLECTION_NAME,
        metadata={"scope": "global"},
        embedding_function=_get_embedding_function(),
    )


def _flatten_metadata(metadata: dict) -> dict[str, Any]:
    """ChromaDB metadata must be flat primitives (str/int/float/bool)."""
    flat: dict[str, Any] = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            flat[k] = v
        else:
            flat[k] = str(v)
    return flat


def insert_chunks(
    chunks_or_job_id: list[dict] | str,
    chunks: list[dict] | None = None,
) -> int:
    """Upsert transcript chunks into the global ChromaDB collection.

    Preferred::

        insert_chunks(chunks)

    Each chunk is ``{"text": str, "metadata": {"video_id": str,
    "chunk_index": int, ...}}``. Chunk IDs are ``f"{video_id}:{chunk_index}"``,
    written via ``collection.upsert``, so repeated calls for the same video
    overwrite in place instead of duplicating.

    Deprecated legacy form ``insert_chunks(job_id, chunks)`` is still
    accepted — ``job_id`` is ignored and a ``DeprecationWarning`` is emitted.

    Returns the number of chunks written.
    """
    if isinstance(chunks_or_job_id, str):
        warnings.warn(
            "insert_chunks(job_id, chunks) is deprecated; call "
            "insert_chunks(chunks) instead — chunks are now global.",
            DeprecationWarning,
            stacklevel=2,
        )
        if chunks is None:
            raise TypeError("insert_chunks(job_id, chunks): missing 'chunks'")
        actual_chunks = chunks
    else:
        if chunks is not None:
            raise TypeError(
                "insert_chunks() got two chunk arguments; call "
                "insert_chunks(chunks) with a single list."
            )
        actual_chunks = chunks_or_job_id

    collection = get_global_collection()

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for chunk in actual_chunks:
        meta_in = chunk.get("metadata", {}) or {}
        video_id = meta_in.get("video_id")
        chunk_index = meta_in.get("chunk_index")
        if not video_id or chunk_index is None:
            logger.warning(
                "Skipping chunk missing video_id or chunk_index: "
                f"video_id={video_id!r} chunk_index={chunk_index!r}"
            )
            continue

        ids.append(f"{video_id}:{chunk_index}")
        documents.append(chunk["text"])
        metadatas.append(_flatten_metadata(meta_in))

    if not ids:
        logger.info("ChromaDB upsert: no chunks to insert")
        return 0

    n_batches = (len(ids) + _BATCH_SIZE - 1) // _BATCH_SIZE
    logger.info(f"ChromaDB upsert: {len(ids)} chunks in {n_batches} batch(es)")

    for i in range(0, len(ids), _BATCH_SIZE):
        collection.upsert(
            ids=ids[i:i + _BATCH_SIZE],
            documents=documents[i:i + _BATCH_SIZE],
            metadatas=metadatas[i:i + _BATCH_SIZE],
        )

    logger.info(f"ChromaDB upsert complete: {len(ids)} chunks stored")
    return len(ids)


def query_collection(
    query_or_job_id: str,
    query_text_or_n_results: str | int | None = None,
    n_results: int | None = None,
    video_ids: list[str] | None = None,
    distance_threshold: float | None = None,
) -> list[dict]:
    """Query the global collection, optionally scoped by ``video_ids``.

    Preferred::

        query_collection(
            query_text,
            n_results=settings.RAG_TOP_K,
            video_ids=None,
            distance_threshold=None,
        )

    When ``video_ids`` is None/empty the whole library is searched;
    otherwise the query is filtered with
    ``where={"video_id": {"$in": video_ids}}``.

    Deprecated legacy form ``query_collection(job_id, query_text, n_results=...)``
    is still accepted — ``job_id`` is ignored, a ``DeprecationWarning`` is
    emitted, and the second positional argument becomes ``query_text``.

    Returns a list of ``{"text", "metadata", "distance"}`` dicts, sorted by
    relevance, with chunks over ``distance_threshold`` filtered out.
    """
    # Disambiguate: two positionals -> legacy (job_id, query_text, ...);
    # one positional -> new (query_text, ...).
    if isinstance(query_text_or_n_results, str):
        warnings.warn(
            "query_collection(job_id, query_text, ...) is deprecated; "
            "call query_collection(query_text, video_ids=[...]) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        query_text = query_text_or_n_results
    elif query_text_or_n_results is None:
        query_text = query_or_job_id
    else:
        # second positional is numeric -> it's n_results from the new form
        query_text = query_or_job_id
        if n_results is None:
            n_results = query_text_or_n_results

    if n_results is None:
        n_results = settings.RAG_TOP_K
    if distance_threshold is None:
        distance_threshold = settings.RAG_DISTANCE_THRESHOLD

    where: dict | None = (
        {"video_id": {"$in": list(video_ids)}} if video_ids else None
    )
    preview = query_text[:80] + ("..." if len(query_text) > 80 else "")
    scope = f"video_ids={len(video_ids)}" if video_ids else "global"
    logger.info(
        f"ChromaDB query: scope={scope}, n_results={n_results}, "
        f"distance_threshold={distance_threshold}, query='{preview}'"
    )

    try:
        collection = get_global_collection()
    except Exception:
        logger.exception("Failed to open global ChromaDB collection")
        return []

    params: dict[str, Any] = {
        "query_texts": [query_text],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        params["where"] = where

    try:
        results = collection.query(**params)
    except Exception:
        logger.exception("ChromaDB query failed")
        return []

    chunks: list[dict] = []
    dropped = 0
    if results and results.get("documents"):
        docs = results["documents"][0] if results["documents"] else []
        dists = results["distances"][0] if results.get("distances") else []
        metas = results["metadatas"][0] if results.get("metadatas") else []
        for i, doc in enumerate(docs):
            distance = dists[i] if i < len(dists) else 0.0
            if distance > distance_threshold:
                dropped += 1
                continue
            chunks.append({
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "distance": distance,
            })

    logger.info(
        f"ChromaDB query returned {len(chunks)} results "
        f"(dropped {dropped} by distance > {distance_threshold})"
    )
    return chunks


def delete_video_chunks(video_id: str) -> bool:
    """Delete every chunk belonging to ``video_id`` from the global collection.

    Returns ``True`` if the delete call succeeded (no-op on empty/missing
    video IDs returns ``False``).
    """
    if not video_id:
        logger.warning("delete_video_chunks called with empty video_id; skipping")
        return False

    try:
        collection = get_global_collection()
        collection.delete(where={"video_id": video_id})
    except Exception:
        logger.exception(f"ChromaDB delete failed for video_id={video_id}")
        return False

    logger.info(f"Deleted chunks for video_id={video_id} from global collection")
    return True


def delete_collection(job_id: str) -> bool:
    """Deprecated no-op kept for backward compatibility.

    Per-job collections were retired; chunks now live in the global
    collection and are keyed by ``video_id``. The existing delete-job
    router still calls this, so we log and return ``True`` rather than
    break callers.
    """
    logger.info(
        f"[job:{job_id}] Per-job collection deletion is deprecated — "
        f"chunks are global. No-op."
    )
    return True


# --- Backward-compatibility shims for callers not yet migrated ------------

def create_collection(job_id: str) -> chromadb.Collection:
    """Deprecated. Returns the global collection; ``job_id`` is ignored."""
    warnings.warn(
        "create_collection(job_id) is deprecated; use get_global_collection().",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.info(
        f"[job:{job_id}] create_collection is a shim: returning global collection"
    )
    return get_global_collection()


def get_collection(job_id: str) -> chromadb.Collection | None:
    """Deprecated. Returns the global collection; ``job_id`` is ignored."""
    warnings.warn(
        "get_collection(job_id) is deprecated; use get_global_collection().",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        return get_global_collection()
    except Exception:
        logger.exception(f"[job:{job_id}] get_global_collection failed")
        return None


# --- Q&A library collection -----------------------------------------------

QASource = Literal["job", "library", "history"]


def get_qa_collection() -> chromadb.Collection:
    """Return the Q&A library collection, creating it if missing.

    One document per Q&A exchange (not chunked). Document text is
    ``f"Q: {question}\n\nA: {answer}"``; IDs are ``f"qa:{exchange_id}"``.
    """
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_QA_COLLECTION_NAME,
        metadata={"scope": "qa_library"},
        embedding_function=_get_embedding_function(),
    )


def _qa_document_text(question: str, answer: str) -> str:
    return f"Q: {question}\n\nA: {answer}"


def _reference_count(exchange: Any) -> int:
    """Return the length of the exchange's references list, tolerating both
    ``references`` (job Q&A) and ``references_json`` (library Q&A) attrs
    and any malformed JSON.
    """
    raw = getattr(exchange, "references_json", None)
    if raw is None:
        raw = getattr(exchange, "references", None)
    if raw is None:
        return 0
    if isinstance(raw, list):
        return len(raw)
    if not isinstance(raw, str):
        return 0
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def upsert_qa_exchange(
    exchange: Any,
    source: QASource,
    tenant_id: str | None = None,
) -> bool:
    """Upsert a single Q&A exchange into the Q&A library collection.

    Expects the ORM object to expose ``id``, ``question``, ``answer``,
    ``created_at`` and (optionally) ``job_id`` / ``answer_language``.
    All failures are caught and logged — callers MUST NOT let a Chroma
    error break the Q&A response. Returns ``True`` on success, ``False``
    otherwise.

    Tenant scoping (T-5.6.6): if ``tenant_id`` is omitted, falls back to
    ``exchange.tenant_id``. The value is written to Chroma metadata so
    `query_qa_collection(tenant_id=...)` can enforce per-tenant isolation
    on similarity searches. Rows where ``tenant_id`` is unresolvable
    (legacy data created before E-5.1 phase 2a) still upsert without the
    metadata key — they become invisible to tenant-scoped queries until
    an operator backfills them. The fail-safe direction (invisible rather
    than universally visible) closes the cross-tenant leak.
    """
    try:
        exchange_id = str(exchange.id)
        question = exchange.question or ""
        answer = exchange.answer or ""
    except Exception:
        logger.exception("upsert_qa_exchange: malformed exchange object")
        return False

    if tenant_id is None:
        tenant_id = getattr(exchange, "tenant_id", None)

    metadata: dict[str, Any] = {
        "source": source,
        "exchange_id": exchange_id,
        "reference_count": _reference_count(exchange),
    }

    if tenant_id is not None:
        metadata["tenant_id"] = str(tenant_id)
    else:
        logger.warning(
            "upsert_qa_exchange: no tenant_id resolvable for exchange_id=%s "
            "source=%s — row will be invisible to tenant-scoped queries.",
            exchange_id,
            source,
        )

    job_id = getattr(exchange, "job_id", None)
    if job_id is not None:
        metadata["job_id"] = str(job_id)

    answer_language = getattr(exchange, "answer_language", None)
    if answer_language is not None:
        metadata["answer_language"] = str(answer_language)

    created_at = getattr(exchange, "created_at", None)
    if created_at is not None:
        try:
            metadata["created_at_iso"] = created_at.isoformat()
        except Exception:
            metadata["created_at_iso"] = str(created_at)

    try:
        collection = get_qa_collection()
        collection.upsert(
            ids=[f"qa:{exchange_id}"],
            documents=[_qa_document_text(question, answer)],
            metadatas=[_flatten_metadata(metadata)],
        )
    except Exception:
        logger.exception(
            f"upsert_qa_exchange failed for exchange_id={exchange_id} source={source}"
        )
        return False

    logger.info(
        f"Upserted Q&A exchange into '{settings.CHROMA_QA_COLLECTION_NAME}': "
        f"id={exchange_id} source={source} tenant_id={tenant_id}"
    )
    return True


def query_qa_collection(
    query_text: str,
    top_k: int | None = None,
    where: dict | None = None,
    tenant_id: str | None = None,
) -> list[dict]:
    """Query the Q&A library collection.

    Returns a list of ``{"text", "metadata", "distance"}`` dicts sorted by
    relevance. ``where`` is passed straight through to ChromaDB for
    metadata filtering (e.g. ``{"source": "job"}``).

    Tenant scoping (T-5.6.6): when ``tenant_id`` is provided, the query is
    restricted to chunks with matching ``tenant_id`` metadata. Combines
    with any caller-provided ``where`` via ``$and`` so both filters apply.
    Passing ``tenant_id=None`` is allowed (e.g. for backfill / admin
    aggregation) but every user-facing call site MUST pass a non-None
    value — that's how the cross-tenant isolation is enforced. Legacy
    rows that pre-date E-5.1 phase 2a (and hence have no ``tenant_id``
    metadata) are invisible to tenant-scoped queries; the fail-safe
    direction closes the leak.
    """
    if top_k is None:
        top_k = settings.RAG_TOP_K

    try:
        collection = get_qa_collection()
    except Exception:
        logger.exception("Failed to open Q&A ChromaDB collection")
        return []

    # Build the effective where filter combining caller `where` and tenant.
    effective_where: dict | None
    if tenant_id is not None and where:
        effective_where = {"$and": [{"tenant_id": str(tenant_id)}, where]}
    elif tenant_id is not None:
        effective_where = {"tenant_id": str(tenant_id)}
    else:
        effective_where = where

    params: dict[str, Any] = {
        "query_texts": [query_text],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if effective_where:
        params["where"] = effective_where

    try:
        results = collection.query(**params)
    except Exception:
        logger.exception("Q&A ChromaDB query failed")
        return []

    out: list[dict] = []
    if results and results.get("documents"):
        docs = results["documents"][0] if results["documents"] else []
        dists = results["distances"][0] if results.get("distances") else []
        metas = results["metadatas"][0] if results.get("metadatas") else []
        for i, doc in enumerate(docs):
            out.append({
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else 0.0,
            })
    return out


def backfill_qa_library() -> int:
    """Upsert every existing ``QAExchange``, ``LibraryQAExchange``, and
    ``QAHistoryExchange`` row into the Q&A library collection.

    Idempotent: upsert on the fixed ``qa:{id}`` chunk ID means re-running
    only overwrites in place. Safe to call on every process startup.

    T-5.6.6 update: now also covers ``QAHistoryExchange`` rows (previously
    omitted), and propagates ``tenant_id`` from each row's column into
    Chroma metadata so per-tenant queries hide other users' history.

    Returns the total number of rows upserted (including repeats).
    """
    # Imports are local so importing chroma_service never pulls in
    # SQLAlchemy / app models — keeps the service free of module-level
    # side effects for tests that monkeypatch the ORM.
    from app.database import SessionLocal
    from app.models.library_qa_exchange import LibraryQAExchange
    from app.models.qa_exchange import QAExchange
    from app.models.qa_history_exchange import QAHistoryExchange

    count = 0
    try:
        db = SessionLocal()
    except Exception:
        logger.exception("backfill_qa_library: failed to open DB session")
        return 0

    try:
        for exchange in db.query(QAExchange).all():
            if upsert_qa_exchange(exchange, source="job"):
                count += 1
        for exchange in db.query(LibraryQAExchange).all():
            if upsert_qa_exchange(exchange, source="library"):
                count += 1
        for exchange in db.query(QAHistoryExchange).all():
            if upsert_qa_exchange(exchange, source="history"):
                count += 1
    except Exception:
        logger.exception("backfill_qa_library: unexpected error during backfill")
    finally:
        try:
            db.close()
        except Exception:
            logger.exception("backfill_qa_library: failed to close DB session")

    logger.info(f"backfill_qa_library: upserted {count} Q&A exchange(s)")
    return count


# --- Startup migration ----------------------------------------------------

def migrate_legacy_per_job_collections() -> None:
    """Merge any legacy ``job_*`` collections into the global collection.

    Iterates ``client.list_collections()`` filtering by ``name.startswith
    ("job_")``, upserts all chunks (preserving metadata) into the global
    collection, then deletes the legacy collection. Idempotent — safe to
    run on every startup because ``upsert`` by ``video_id:chunk_index``
    overwrites in place and the source collection is removed after a
    successful merge.

    NOTE: Not yet wired into ``app/main.py`` startup. TODO: add
    ``chroma_service.migrate_legacy_per_job_collections()`` to the
    ``lifespan`` context in ``backend/app/main.py`` once Unit 1 lands.
    """
    try:
        client = get_chroma_client()
    except Exception:
        logger.exception("migrate_legacy_per_job_collections: client init failed")
        return

    try:
        all_collections = client.list_collections()
    except Exception:
        logger.exception("migrate_legacy_per_job_collections: list_collections failed")
        return

    legacy = [c for c in all_collections if getattr(c, "name", "").startswith("job_")]
    if not legacy:
        logger.info("migrate_legacy_per_job_collections: nothing to migrate")
        return

    logger.info(
        f"migrate_legacy_per_job_collections: migrating {len(legacy)} legacy "
        f"collection(s) into '{settings.CHROMA_GLOBAL_COLLECTION_NAME}'"
    )

    global_collection = get_global_collection()

    for legacy_coll in legacy:
        name = legacy_coll.name
        try:
            data = legacy_coll.get(include=["documents", "metadatas"])
        except Exception:
            logger.exception(f"Failed to read legacy collection '{name}'; skipping")
            continue

        docs = data.get("documents") or []
        metas = data.get("metadatas") or []

        if not docs:
            logger.info(f"Legacy collection '{name}' is empty; deleting")
            _safe_delete_legacy(client, name)
            continue

        new_ids: list[str] = []
        new_docs: list[str] = []
        new_metas: list[dict[str, Any]] = []
        skipped = 0
        for doc, meta in zip(docs, metas):
            meta = meta or {}
            video_id = meta.get("video_id")
            chunk_index = meta.get("chunk_index")
            if not video_id or chunk_index is None:
                skipped += 1
                continue
            new_ids.append(f"{video_id}:{chunk_index}")
            new_docs.append(doc)
            new_metas.append(_flatten_metadata(meta))

        if new_ids:
            try:
                for i in range(0, len(new_ids), _BATCH_SIZE):
                    global_collection.upsert(
                        ids=new_ids[i:i + _BATCH_SIZE],
                        documents=new_docs[i:i + _BATCH_SIZE],
                        metadatas=new_metas[i:i + _BATCH_SIZE],
                    )
            except Exception:
                logger.exception(
                    f"Failed to upsert from legacy collection '{name}'; "
                    f"leaving it in place"
                )
                continue

        logger.info(
            f"Migrated '{name}': {len(new_ids)} chunk(s) upserted "
            f"(skipped {skipped} missing video_id/chunk_index)"
        )
        _safe_delete_legacy(client, name)


def _safe_delete_legacy(client: chromadb.ClientAPI, name: str) -> None:
    try:
        client.delete_collection(name=name)
        logger.info(f"Deleted legacy collection '{name}'")
    except Exception:
        logger.exception(f"Failed to delete legacy collection '{name}'")

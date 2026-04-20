"""ChromaDB service: global-collection model.

VideoResearchPro stores every transcript chunk in a single shared ChromaDB
collection — ``settings.CHROMA_GLOBAL_COLLECTION_NAME`` (default
``videoresearchpro_global``). Videos are globally deduplicated: a given
video's chunks are indexed exactly once and re-used across any job that
references the video. The former per-job collection model has been retired.

Query scoping is performed via ChromaDB metadata filtering on ``video_id``:

* Job-scoped query  -> ``query_collection(..., video_ids=[...])`` passes the
  list as a ``{"video_id": {"$in": [...]}}`` ``where`` clause.
* Library-wide query -> ``query_collection(..., video_ids=None)`` omits the
  ``where`` clause and searches the whole collection.

Chunk IDs are derived as ``"{video_id}:{chunk_index}"`` and inserts use
``collection.upsert`` so repeated extraction of the same video is idempotent
— re-running an extraction overwrites existing chunks in place rather than
creating duplicates.

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

import logging
import warnings
from typing import Any

import chromadb

from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None

_BATCH_SIZE = 100


def get_chroma_client() -> chromadb.ClientAPI:
    """Return the process-level singleton ChromaDB client."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return _client


def get_global_collection() -> chromadb.Collection:
    """Return the single global collection, creating it if missing."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_GLOBAL_COLLECTION_NAME,
        metadata={"scope": "global"},
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

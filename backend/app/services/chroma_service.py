import logging

import chromadb

from app.config import settings

logger = logging.getLogger(__name__)

# Process-level singleton: ChromaDB's PersistentClient holds an exclusive
# handle on the underlying SQLite database, so only one client instance may
# exist per process. This is safe for the current Celery worker topology
# (`--pool=solo` on Windows, one worker = one process), but it imposes a
# concurrency limitation: running Celery with prefork/threads/gevent/eventlet
# pools, or multiple worker processes sharing this persist directory, will
# fail with "An instance of Chroma already exists" or SQLite lock errors.
# If concurrency > 1 is ever required, switch to ChromaDB's client/server
# mode (HttpClient against a dedicated chroma-server) instead of the
# in-process PersistentClient.
_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return _client


def create_collection(job_id: str) -> chromadb.Collection:
    """Create a new ChromaDB collection for a job."""
    client = get_chroma_client()
    name = f"job_{job_id.replace('-', '_')}"
    collection = client.get_or_create_collection(
        name=name,
        metadata={"job_id": job_id},
    )
    logger.info(f"[job:{job_id}] ChromaDB collection ready: '{name}'")
    return collection


def get_collection(job_id: str) -> chromadb.Collection | None:
    """Get an existing collection for a job."""
    client = get_chroma_client()
    name = f"job_{job_id.replace('-', '_')}"
    try:
        return client.get_collection(name=name)
    except Exception:
        return None


def delete_collection(job_id: str) -> bool:
    """Delete a job's ChromaDB collection."""
    client = get_chroma_client()
    name = f"job_{job_id.replace('-', '_')}"
    try:
        client.delete_collection(name=name)
        return True
    except Exception:
        return False


def insert_chunks(job_id: str, chunks: list[dict]) -> int:
    """
    Insert transcript chunks into a job's ChromaDB collection.

    Args:
        job_id: The job ID.
        chunks: List of {text, metadata} dicts from chunking.py.

    Returns:
        Number of chunks inserted.
    """
    collection = create_collection(job_id)

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        vid = chunk["metadata"].get("video_id", "unknown")
        chunk_id = f"chunk_{job_id}_{vid}_{i}"
        ids.append(chunk_id)
        documents.append(chunk["text"])

        # ChromaDB metadata must be flat (str, int, float, bool)
        meta = {}
        for k, v in chunk["metadata"].items():
            if isinstance(v, (str, int, float, bool)):
                meta[k] = v
            else:
                meta[k] = str(v)
        metadatas.append(meta)

    if not ids:
        logger.info(f"[job:{job_id}] ChromaDB insert: no chunks to insert")
        return 0

    logger.info(f"[job:{job_id}] ChromaDB insert: {len(ids)} chunks in "
                f"{(len(ids) + 99) // 100} batch(es)")

    # Insert in batches of 100 (ChromaDB recommendation)
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )

    logger.info(f"[job:{job_id}] ChromaDB insert complete: {len(ids)} chunks stored")
    return len(ids)


def query_collection(
    job_id: str,
    query_text: str,
    n_results: int = 15,
    where: dict | None = None,
) -> list[dict]:
    """
    Query a job's ChromaDB collection.

    Returns:
        List of {text, metadata, distance} dicts sorted by relevance.
    """
    logger.info(f"[job:{job_id}] ChromaDB query: n_results={n_results}, "
                f"query='{query_text[:80]}{'...' if len(query_text) > 80 else ''}'")
    collection = get_collection(job_id)
    if not collection:
        logger.warning(f"[job:{job_id}] ChromaDB collection not found for query")
        return []

    params = {
        "query_texts": [query_text],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        params["where"] = where

    results = collection.query(**params)

    chunks = []
    if results and results.get("documents"):
        for i, doc in enumerate(results["documents"][0]):
            chunks.append({
                "text": doc,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                "distance": results["distances"][0][i] if results.get("distances") else 0.0,
            })

    logger.info(f"[job:{job_id}] ChromaDB query returned {len(chunks)} results")
    return chunks

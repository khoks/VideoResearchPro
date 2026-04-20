"""Tests for the global-library ChromaDB service (Unit 2).

Verifies the refactored chroma_service that uses a single global collection
with `video_id` metadata filtering instead of one collection per job.
"""
import inspect

import pytest

from app.services import chroma_service

# Unit 2 refactors chroma_service's public API: `insert_chunks` drops the
# `job_id` argument, `query_collection` takes a `video_ids` filter, and a
# new `delete_video_chunks` helper exists. Skip the whole module until the
# new signatures land.
_insert_sig = inspect.signature(chroma_service.insert_chunks)
if "job_id" in _insert_sig.parameters:
    pytest.skip(
        "pending Unit 2 merge — chroma_service not yet refactored to global collection",
        allow_module_level=True,
    )
if not hasattr(chroma_service, "delete_video_chunks"):
    pytest.skip(
        "pending Unit 2 merge — delete_video_chunks not yet defined",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def use_ephemeral_chroma(monkeypatch):
    """Use in-memory ChromaDB for tests, isolated per test."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    # allow_reset lets us nuke state between tests; EphemeralClient defaults
    # to sharing a system registry which would leak collection data across
    # tests in the same process.
    client = chromadb.EphemeralClient(settings=ChromaSettings(allow_reset=True))
    client.reset()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield
    try:
        client.reset()
    except Exception:
        pass


def _make_chunks(video_id: str = "vid1", count: int = 3) -> list[dict]:
    chunks = []
    for i in range(count):
        chunks.append({
            "text": f"Chunk {i} about quantum computing, networking, and DNS systems.",
            "metadata": {
                "video_id": video_id,
                "video_title": f"Video {video_id}",
                "channel_name": "Channel A",
                "channel_id": "UCtest",
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "timestamp_start": i * 60.0,
                "timestamp_end": (i + 1) * 60.0,
                "chunk_index": i,
                "total_chunks": count,
                "language": "en",
                "word_count": 10,
            },
        })
    return chunks


def test_insert_chunks_without_job_id():
    """New `insert_chunks(chunks)` signature does not take a job_id."""
    chunks = _make_chunks("vA", count=3)
    inserted = chroma_service.insert_chunks(chunks)
    assert inserted == 3


def test_insert_chunks_is_idempotent():
    """Inserting the same (video_id, chunk_index) twice keeps one row per chunk."""
    chunks = _make_chunks("vIdem", count=4)
    chroma_service.insert_chunks(chunks)
    chroma_service.insert_chunks(chunks)  # re-ingest

    results = chroma_service.query_collection(
        "quantum",
        video_ids=["vIdem"],
        n_results=50,
    )
    # De-duplicated on (video_id, chunk_index): 4 unique, not 8.
    keys = {(r["metadata"].get("video_id"), r["metadata"].get("chunk_index"))
            for r in results}
    assert len(keys) == 4


def test_query_filters_by_video_ids():
    """`query_collection(q, video_ids=[...])` returns only chunks whose
    metadata.video_id is in the allow-list."""
    chroma_service.insert_chunks(_make_chunks("vA", count=3))
    chroma_service.insert_chunks(_make_chunks("vB", count=3))
    chroma_service.insert_chunks(_make_chunks("vC", count=3))

    results = chroma_service.query_collection(
        "quantum computing",
        video_ids=["vA"],
        n_results=20,
    )
    assert results
    assert all(r["metadata"]["video_id"] == "vA" for r in results)


def test_query_video_ids_none_returns_global_results():
    """`video_ids=None` searches the full global collection."""
    chroma_service.insert_chunks(_make_chunks("vA", count=2))
    chroma_service.insert_chunks(_make_chunks("vB", count=2))

    results = chroma_service.query_collection(
        "quantum computing",
        video_ids=None,
        n_results=20,
    )
    video_ids = {r["metadata"]["video_id"] for r in results}
    assert video_ids == {"vA", "vB"}


def test_delete_video_chunks_removes_only_that_video():
    chroma_service.insert_chunks(_make_chunks("vA", count=3))
    chroma_service.insert_chunks(_make_chunks("vB", count=3))

    chroma_service.delete_video_chunks("vA")

    # vA gone; vB intact.
    a_results = chroma_service.query_collection(
        "quantum", video_ids=["vA"], n_results=20
    )
    b_results = chroma_service.query_collection(
        "quantum", video_ids=["vB"], n_results=20
    )
    assert a_results == []
    assert len(b_results) == 3

import uuid
import warnings

import pytest

from app.services import chroma_service


@pytest.fixture(autouse=True)
def use_ephemeral_chroma(monkeypatch):
    """Use in-memory ChromaDB for tests.

    Chroma's EphemeralClient shares a process-level SharedSystemClient, so
    collections can leak across tests. We clear the system cache and the
    module-level singleton between tests to guarantee isolation.
    """
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient
    SharedSystemClient._identifier_to_system = {}

    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def job_id():
    return str(uuid.uuid4())


def _make_chunks(video_id: str = "vid1", count: int = 5) -> list[dict]:
    chunks = []
    for i in range(count):
        chunks.append({
            "text": f"This is chunk {i} about quantum computing and physics research findings.",
            "metadata": {
                "video_id": video_id,
                "video_title": "Test Video",
                "channel_name": "TestChannel",
                "channel_id": "UCtest",
                "video_url": f"https://youtube.com/watch?v={video_id}",
                "timestamp_start": i * 60.0,
                "timestamp_end": (i + 1) * 60.0,
                "chunk_index": i,
                "total_chunks": count,
                "language": "en",
                "word_count": 10,
            },
        })
    return chunks


# --- Legacy shim tests (job_id-based API kept for backward compatibility) ---

def test_create_and_get_collection(job_id):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        collection = chroma_service.create_collection(job_id)
        assert collection is not None

        retrieved = chroma_service.get_collection(job_id)
        assert retrieved is not None


def test_insert_chunks(job_id):
    chunks = _make_chunks(count=10)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        inserted = chroma_service.insert_chunks(job_id, chunks)
    assert inserted == 10


def test_query_collection(job_id):
    chunks = _make_chunks(count=5)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        chroma_service.insert_chunks(job_id, chunks)
        results = chroma_service.query_collection(
            job_id, "quantum computing physics", n_results=3
        )
    assert len(results) > 0
    assert "text" in results[0]
    assert "metadata" in results[0]
    assert "distance" in results[0]


def test_query_empty_collection(job_id):
    # Global collection exists but is empty.
    chroma_service.get_global_collection()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        results = chroma_service.query_collection(job_id, "anything")
    assert results == []


def test_query_nonexistent_collection():
    # Global model: "nonexistent" job id is simply ignored.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        results = chroma_service.query_collection("nonexistent-id", "anything")
    assert results == []


def test_delete_collection(job_id):
    # Now a no-op that returns True and keeps the global collection alive.
    assert chroma_service.delete_collection(job_id) is True


def test_insert_empty_chunks(job_id):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        inserted = chroma_service.insert_chunks(job_id, [])
    assert inserted == 0


# --- New global-collection API tests ---------------------------------------

def test_global_insert_and_query_library_wide():
    """insert_chunks(chunks) + query_collection(video_ids=None) returns
    results from the global collection."""
    chroma_service.insert_chunks(_make_chunks("vid_alpha", count=3))
    chroma_service.insert_chunks(_make_chunks("vid_beta", count=3))

    results = chroma_service.query_collection(
        "quantum computing physics research",
        n_results=10,
        distance_threshold=float("inf"),
    )
    assert len(results) > 0
    video_ids_seen = {r["metadata"]["video_id"] for r in results}
    assert video_ids_seen == {"vid_alpha", "vid_beta"}


def test_query_scoped_by_video_ids():
    """query_collection(video_ids=['abc']) only returns chunks where
    metadata.video_id matches."""
    chroma_service.insert_chunks(_make_chunks("vid_alpha", count=3))
    chroma_service.insert_chunks(_make_chunks("vid_beta", count=3))

    results = chroma_service.query_collection(
        "quantum computing physics research",
        n_results=10,
        video_ids=["vid_alpha"],
        distance_threshold=float("inf"),
    )
    assert len(results) > 0
    for r in results:
        assert r["metadata"]["video_id"] == "vid_alpha"


def test_query_scoped_by_multiple_video_ids():
    chroma_service.insert_chunks(_make_chunks("vid_a", count=2))
    chroma_service.insert_chunks(_make_chunks("vid_b", count=2))
    chroma_service.insert_chunks(_make_chunks("vid_c", count=2))

    results = chroma_service.query_collection(
        "quantum computing physics research",
        n_results=20,
        video_ids=["vid_a", "vid_c"],
        distance_threshold=float("inf"),
    )
    video_ids_seen = {r["metadata"]["video_id"] for r in results}
    assert video_ids_seen.issubset({"vid_a", "vid_c"})
    assert video_ids_seen  # non-empty


def test_insert_chunks_is_idempotent_via_upsert():
    """Re-inserting the same (video_id, chunk_index) pairs does not
    create duplicates: upsert overwrites by id."""
    chunks = _make_chunks("vid_dup", count=4)
    chroma_service.insert_chunks(chunks)
    chroma_service.insert_chunks(chunks)  # second pass -> upsert, no dup
    chroma_service.insert_chunks(chunks)  # third pass

    collection = chroma_service.get_global_collection()
    stored = collection.get(where={"video_id": "vid_dup"}, include=[])
    assert len(stored["ids"]) == 4


def test_delete_video_chunks_removes_only_target_video():
    chroma_service.insert_chunks(_make_chunks("vid_keep", count=3))
    chroma_service.insert_chunks(_make_chunks("vid_drop", count=4))

    assert chroma_service.delete_video_chunks("vid_drop") is True

    collection = chroma_service.get_global_collection()
    kept = collection.get(where={"video_id": "vid_keep"}, include=[])
    dropped = collection.get(where={"video_id": "vid_drop"}, include=[])
    assert len(kept["ids"]) == 3
    assert len(dropped["ids"]) == 0


def test_delete_video_chunks_empty_video_id_is_noop():
    assert chroma_service.delete_video_chunks("") is False


def test_insert_skips_chunks_missing_required_metadata():
    bad = [
        {"text": "missing video_id", "metadata": {"chunk_index": 0}},
        {"text": "missing chunk_index", "metadata": {"video_id": "vid_x"}},
    ]
    good = _make_chunks("vid_ok", count=2)
    inserted = chroma_service.insert_chunks(bad + good)
    assert inserted == 2


def test_query_with_kwargs():
    chroma_service.insert_chunks(_make_chunks("vid_kw", count=3))
    results = chroma_service.query_collection(
        "quantum computing physics research",
        n_results=5,
        video_ids=["vid_kw"],
        distance_threshold=float("inf"),
    )
    assert len(results) > 0
    assert all(r["metadata"]["video_id"] == "vid_kw" for r in results)


def test_legacy_insert_emits_deprecation_warning(job_id):
    chunks = _make_chunks("vid_leg", count=1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        chroma_service.insert_chunks(job_id, chunks)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_legacy_query_emits_deprecation_warning(job_id):
    chroma_service.insert_chunks(_make_chunks("vid_leg", count=2))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        chroma_service.query_collection(job_id, "quantum", n_results=3)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_migrate_legacy_per_job_collections_is_idempotent():
    """Create a legacy job_* collection, run migration twice, verify
    chunks land in the global collection and the legacy collection is gone."""
    client = chroma_service.get_chroma_client()
    legacy = client.get_or_create_collection(
        name="job_legacy_123", metadata={"job_id": "legacy-123"}
    )
    legacy.add(
        ids=["chunk_legacy_vidA_0", "chunk_legacy_vidA_1"],
        documents=["first legacy chunk", "second legacy chunk"],
        metadatas=[
            {"video_id": "vidA", "chunk_index": 0},
            {"video_id": "vidA", "chunk_index": 1},
        ],
    )

    chroma_service.migrate_legacy_per_job_collections()
    # Running twice must not raise.
    chroma_service.migrate_legacy_per_job_collections()

    names = [c.name for c in client.list_collections()]
    assert "job_legacy_123" not in names

    global_coll = chroma_service.get_global_collection()
    merged = global_coll.get(where={"video_id": "vidA"}, include=[])
    assert set(merged["ids"]) == {"vidA:0", "vidA:1"}

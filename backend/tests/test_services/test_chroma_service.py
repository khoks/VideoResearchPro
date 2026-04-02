import uuid

import pytest

from app.services import chroma_service


@pytest.fixture(autouse=True)
def use_ephemeral_chroma(monkeypatch):
    """Use in-memory ChromaDB for tests."""
    import chromadb
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield


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


def test_create_and_get_collection(job_id):
    collection = chroma_service.create_collection(job_id)
    assert collection is not None

    retrieved = chroma_service.get_collection(job_id)
    assert retrieved is not None


def test_insert_chunks(job_id):
    chunks = _make_chunks(count=10)
    inserted = chroma_service.insert_chunks(job_id, chunks)
    assert inserted == 10


def test_query_collection(job_id):
    chunks = _make_chunks(count=5)
    chroma_service.insert_chunks(job_id, chunks)

    results = chroma_service.query_collection(job_id, "quantum computing physics", n_results=3)
    assert len(results) > 0
    assert "text" in results[0]
    assert "metadata" in results[0]
    assert "distance" in results[0]


def test_query_empty_collection(job_id):
    chroma_service.create_collection(job_id)
    results = chroma_service.query_collection(job_id, "anything")
    assert results == []


def test_query_nonexistent_collection():
    results = chroma_service.query_collection("nonexistent-id", "anything")
    assert results == []


def test_delete_collection(job_id):
    chroma_service.create_collection(job_id)
    assert chroma_service.delete_collection(job_id) is True
    assert chroma_service.get_collection(job_id) is None


def test_insert_empty_chunks(job_id):
    inserted = chroma_service.insert_chunks(job_id, [])
    assert inserted == 0

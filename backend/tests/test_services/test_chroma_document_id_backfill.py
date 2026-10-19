"""``backfill_chunk_document_ids`` — the D-070 transition for chunks that
predate the ``document_id`` metadata field.

The retrieval filter moved from ``video_id`` to ``document_id`` in one step,
so every chunk embedded before 2026-10-19 would have become unretrievable.
The chosen transition is a metadata-only backfill at startup (no
re-embedding), rather than a dual filter — one retrieval path, not two.
"""
import pytest

from app.models.document import Document
from app.services import chroma_service


@pytest.fixture(autouse=True)
def use_ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def _legacy_chunks(video_id: str, count: int) -> list[dict]:
    """The pre-D-070 shape: video_id only, no document_id."""
    return [
        {
            "text": f"Legacy chunk {i} about quantum computing from {video_id}.",
            "metadata": {
                "video_id": video_id,
                "video_title": f"Video {video_id}",
                "channel_name": "Old Channel",
                "chunk_index": i,
                "total_chunks": count,
                "source_type": "video",
                "source_id": video_id,
                "language": "en",
            },
        }
        for i in range(count)
    ]


def _session_factory(db):
    class _NoClose:
        """The backfill closes its session; the fixture session must survive."""

        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    return lambda: _NoClose()


def test_backfill_stamps_document_id_without_reembedding(db):
    db.add_all([
        Document(document_id="doc-old-a", video_id="ytOLD000000a", title="A", url="u"),
        Document(document_id="doc-old-b", video_id="ytOLD000000b", title="B", url="u"),
    ])
    db.commit()
    chroma_service.insert_chunks(_legacy_chunks("ytOLD000000a", 3) + _legacy_chunks("ytOLD000000b", 2))

    # Unretrievable by document scope before the backfill.
    assert chroma_service.query_collection(
        "quantum computing", n_results=10, document_ids=["doc-old-a"], distance_threshold=float("inf")
    ) == []

    assert chroma_service.backfill_chunk_document_ids(_session_factory(db), page_size=2) == 5

    hits = chroma_service.query_collection(
        "quantum computing", n_results=10, document_ids=["doc-old-a"], distance_threshold=float("inf")
    )
    assert {h["metadata"]["video_id"] for h in hits} == {"ytOLD000000a"}
    assert len(hits) == 3
    # Other metadata survived the update, and the embedding did (the query hit).
    assert all(h["metadata"]["channel_name"] == "Old Channel" for h in hits)

    # Idempotent: nothing left to stamp.
    assert chroma_service.backfill_chunk_document_ids(_session_factory(db), page_size=2) == 0


def test_backfill_leaves_chunks_of_unknown_documents_alone(db):
    db.add(Document(document_id="doc-known", video_id="ytKNOWN0000a", title="K", url="u"))
    db.commit()
    chroma_service.insert_chunks(_legacy_chunks("ytKNOWN0000a", 1) + _legacy_chunks("ytGONE00000a", 1))

    assert chroma_service.backfill_chunk_document_ids(_session_factory(db)) == 1
    stored = chroma_service.get_global_collection().get(include=["metadatas"])
    by_id = dict(zip(stored["ids"], stored["metadatas"]))
    assert by_id["ytKNOWN0000a:0"]["document_id"] == "doc-known"
    assert "document_id" not in by_id["ytGONE00000a:0"]


def test_backfill_resolves_by_source_identity_when_video_id_is_absent(db):
    """A chunk whose metadata names its (source_type, source_id) but has no
    video_id — the shape a non-video chunk would have had — maps through the
    documents table's unique source index."""
    db.add(Document(
        document_id="doc-reddit", source_type="reddit_post", source_id="reddit:abc",
        title="Thread", url="https://reddit.com/r/x/abc",
    ))
    db.commit()
    chroma_service.get_global_collection().upsert(
        ids=["doc-reddit:0"],
        documents=["A reddit thread about quantum computing."],
        metadatas=[{"video_id": "", "source_type": "reddit_post", "source_id": "reddit:abc", "chunk_index": 0}],
    )
    assert chroma_service.backfill_chunk_document_ids(_session_factory(db)) == 1
    hits = chroma_service.query_collection(
        "quantum computing", n_results=5, document_ids=["doc-reddit"], distance_threshold=float("inf")
    )
    assert len(hits) == 1 and hits[0]["metadata"]["source_id"] == "reddit:abc"

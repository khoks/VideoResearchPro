"""Chroma retrieval scoped by ``document_id`` (D-070), against a real
in-memory collection.

Three things the router tests cannot show because they patch the write:

1. Chunks of a non-video document are WRITTEN. Before D-070 ``insert_chunks``
   keyed every chunk on ``video_id`` and skipped chunks without one, so no
   PDF or pasted page was ever embedded.
2. ``query_collection(document_ids=[...])`` returns only those documents'
   chunks, for video and non-video alike.
3. ``document_ids=[]`` returns nothing. It used to fall through to an
   unrestricted search, because the filter was built with a truthiness test.
"""
import pytest

from app.models.document import Document
from app.services import chroma_service
from app.tasks.job_tasks import _build_video_metadata
from app.utils.chunking import chunk_transcript


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


def _chunks_for(doc: Document, text: str) -> list[dict]:
    segments = [{"text": text, "start": 0.0, "duration": 0.0}]
    return chunk_transcript(
        segments, chunk_size=64, chunk_overlap=0,
        video_metadata=_build_video_metadata(doc, language="en"),
        transcription_source="pdf" if doc.source_type == "pdf" else "youtube",
    )


def _pdf(document_id: str, title: str) -> Document:
    return Document(
        document_id=document_id, source_type="pdf", source_id=f"pdf:{document_id}",
        source_url=f"/api/v1/library/pdf/{document_id}.pdf", title=title,
        url=f"/api/v1/library/pdf/{document_id}.pdf",
    )


def _video(document_id: str, video_id: str, title: str) -> Document:
    return Document(
        document_id=document_id, video_id=video_id, title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def test_non_video_chunks_are_written_and_keyed_on_document_id():
    doc = _pdf("doc-pdf-a", "Quantum error correction notes")
    chunks = _chunks_for(doc, "Quantum error correction protects qubits from decoherence.")
    assert chunks and chunks[0]["metadata"]["document_id"] == "doc-pdf-a"
    assert chunks[0]["metadata"]["video_id"] == ""

    assert chroma_service.insert_chunks(chunks) == len(chunks)
    stored = chroma_service.get_global_collection().get(include=["metadatas"])
    assert stored["ids"] == ["doc-pdf-a:0"]
    assert stored["metadatas"][0]["document_id"] == "doc-pdf-a"
    assert "video_id" not in stored["metadatas"][0] or stored["metadatas"][0]["video_id"] == ""


def test_video_chunks_keep_their_video_id_storage_key():
    """A re-ingested video must overwrite its existing chunks, which have
    been stored under the YouTube id since the global collection shipped."""
    doc = _video("doc-vid-a", "yt0000000001", "Networking basics")
    chunks = _chunks_for(doc, "DNS maps names to addresses.")
    chroma_service.insert_chunks(chunks)
    chroma_service.insert_chunks(chunks)
    stored = chroma_service.get_global_collection().get(include=["metadatas"])
    assert stored["ids"] == ["yt0000000001:0"]
    assert stored["metadatas"][0]["document_id"] == "doc-vid-a"


def test_query_scoped_by_document_ids_across_source_types():
    a_pdf = _pdf("doc-a-pdf", "A's paper")
    b_page = Document(
        document_id="doc-b-page", source_type="article", source_id="article:b",
        source_url="https://example.com/b", title="B's page", url="https://example.com/b",
    )
    c_vid = _video("doc-c-vid", "yt0000000002", "C's video")
    for doc, text in (
        (a_pdf, "Quantum computing and qubits in A's private paper."),
        (b_page, "Quantum computing explained on B's page."),
        (c_vid, "Quantum computing lecture transcript from C's video."),
    ):
        chroma_service.insert_chunks(_chunks_for(doc, text))

    def scope(ids):
        hits = chroma_service.query_collection(
            "quantum computing", n_results=10, document_ids=ids, distance_threshold=float("inf")
        )
        return {h["metadata"]["document_id"] for h in hits}

    assert scope(["doc-b-page"]) == {"doc-b-page"}
    assert scope(["doc-a-pdf", "doc-c-vid"]) == {"doc-a-pdf", "doc-c-vid"}
    assert scope(None) == {"doc-a-pdf", "doc-b-page", "doc-c-vid"}


def test_empty_document_scope_retrieves_nothing():
    chroma_service.insert_chunks(_chunks_for(_pdf("doc-x", "X"), "Quantum computing text."))
    assert chroma_service.query_collection(
        "quantum computing", n_results=10, document_ids=[], distance_threshold=float("inf")
    ) == []

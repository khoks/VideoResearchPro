"""Knowledge reports for non-video documents, at the production callers.

Until 2026-10-25 ``POST /videos/{id}/extract-knowledge`` read its text from
``transcript_cache`` by ``video_id``. A PDF, a pasted page, a thread or a
podcast episode has no ``video_id`` and no cache row — its text lives only in
its Chroma chunks — so every one of them got a 422.

These tests ingest through the real routes (``/library/upload-pdf`` and
``/library/paste-urls``) with only the connector's text extraction faked:
chunking runs for real at a small chunk size so neighbouring chunks overlap,
and the chunks go into a real (ephemeral) Chroma collection through
``insert_chunks``. The extraction agent is patched, so what it was handed is
the assertion: every sentence of the source exactly once, in order.

The first test doubles as the mutation check: with the router reading
``transcript_cache`` alone (the old code) it 422s, and with the overlap
de-duplication removed its exactly-once assertion fails
(``test_without_overlap_removal_the_router_would_repeat_sentences`` shows the
second half explicitly).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.config import settings
from app.models.document import Document
from app.services import auth_service, document_text_service
from app.sources.types import ExtractedText

# Distinct, numbered sentences: each one is findable, and their order is
# checkable, in whatever text reaches the agent.
SENTENCES = [
    f"Sentence {i:02d} explains finding number {i} about tidal energy storage."
    for i in range(1, 25)
]


def _pages(sentences: list[str], per_page: int = 4) -> list[dict]:
    """PDF-shaped segments: a few sentences per page, page anchors in extra."""
    out = []
    for n, start in enumerate(range(0, len(sentences), per_page), start=1):
        out.append({
            "text": " ".join(sentences[start:start + per_page]),
            "start": float(n - 1),
            "duration": 0.0,
            "extra": {"kind": "page", "comment_url": f"#page={n}"},
        })
    return out


class _FakeConnector:
    def __init__(self, extracted):
        self._extracted = extracted

    def fetch_text(self, candidate, **_kw):
        return self._extracted


def _pdf_text() -> ExtractedText:
    return ExtractedText(
        segments=_pages(SENTENCES),
        language="en",
        text_source="pdf",
        word_count=sum(len(s.split()) for s in SENTENCES),
        extra={"page_count": 6},
    )


def _article_text() -> ExtractedText:
    return ExtractedText(
        segments=[{"text": s, "start": 0.0, "duration": 0.0} for s in SENTENCES],
        language="en",
        text_source="trafilatura",
        word_count=sum(len(s.split()) for s in SENTENCES),
        extra={"extracted_title": "Tidal storage, explained", "extracted_author": "A. Writer"},
    )


def _agent_result() -> dict:
    return {
        "topics": ["tidal energy"],
        "concepts": ["pumped storage"],
        "events": [],
        "facts": ["Finding 1 concerns tidal energy storage"],
        "knowledge_report_md": "# Tidal energy storage\n\n## Overview\n\nText.",
    }


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    """A real, in-memory Chroma collection behind ``chroma_service``."""
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def small_chunks(monkeypatch):
    """Chunks of ~3 sentences carrying one sentence over: real overlap."""
    monkeypatch.setattr(settings, "CHUNK_SIZE", 48)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP", 16)


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))
    return tmp_path / "pdf"


@pytest.fixture
def other_tenant_headers(db):
    other = auth_service.create_user(db, email="stranger@example.com", password="testpass123")
    token, _ = auth_service.create_access_token(other.id)
    return {"Authorization": f"Bearer {token}"}


def _upload_pdf(client) -> str:
    with patch("app.routers.library._connector_for", return_value=_FakeConnector(_pdf_text())):
        resp = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": ("tidal-storage.pdf", b"%PDF-1.4\n% knowledge test\n", "application/pdf")},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


def _paste(client, url: str = "https://example.com/tidal-storage") -> str:
    with patch("app.routers.library._connector_for", return_value=_FakeConnector(_article_text())):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": [url]})
    assert resp.status_code == 201, resp.text
    (row,) = resp.json()["results"]
    assert row["status"] == "created", row
    return row["document_id"]


def _extract(client, doc_id: str, headers: dict | None = None):
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_agent_result(),
    ) as agent:
        resp = client.post(f"/api/v1/videos/{doc_id}/extract-knowledge", headers=headers or {})
    return resp, agent


def _assert_every_sentence_once_in_order(text: str) -> None:
    positions = []
    for sentence in SENTENCES:
        assert text.count(sentence) == 1, f"{sentence!r} appears {text.count(sentence)} times"
        positions.append(text.index(sentence))
    assert positions == sorted(positions), "sentences reached the agent out of order"


def _chunks_overlap(chroma, doc_id: str) -> bool:
    """True when at least one stored chunk repeats a sentence of the previous one."""
    chunks = sorted(
        chroma.get_document_chunks(doc_id), key=lambda c: c["metadata"]["chunk_index"]
    )
    assert len(chunks) > 3, "the fixture must produce several chunks"
    return any(
        any(s in a["text"] and s in b["text"] for s in SENTENCES)
        for a, b in zip(chunks, chunks[1:])
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_visible_pdf_gets_a_knowledge_report_from_its_chunks(
    client, db, upload_dir, ephemeral_chroma, small_chunks
):
    doc_id = _upload_pdf(client)
    assert _chunks_overlap(ephemeral_chroma, doc_id), "the test needs overlapping chunks"

    resp, agent = _extract(client, doc_id)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document_id"] == doc_id
    assert body["source_type"] == "pdf"
    assert body["video_id"] is None
    assert body["topics"] == ["tidal energy"]

    (document, text), _ = agent.call_args
    assert document.document_id == doc_id
    _assert_every_sentence_once_in_order(text)

    db.expire_all()
    stored = db.get(Document, doc_id)
    assert stored.knowledge_extracted_at is not None
    assert stored.knowledge_report_md.startswith("# Tidal energy storage")

    # The artifact reads back, and a second run without force is refused.
    assert client.get(f"/api/v1/videos/{doc_id}/knowledge").status_code == 200
    again, agent_again = _extract(client, doc_id)
    assert again.status_code == 409
    assert not agent_again.called


def test_pdf_another_tenant_cannot_see_404s_and_spends_nothing(
    client, upload_dir, ephemeral_chroma, small_chunks, other_tenant_headers
):
    doc_id = _upload_pdf(client)

    resp, agent = _extract(client, doc_id, headers=other_tenant_headers)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Video not found"}
    assert not agent.called


def test_pdf_knowledge_reaches_the_knowledge_dataset_export(
    client, upload_dir, ephemeral_chroma, small_chunks
):
    doc_id = _upload_pdf(client)
    resp, _ = _extract(client, doc_id)
    assert resp.status_code == 200, resp.text

    export = client.get("/api/v1/exports/knowledge-dataset/tuple.jsonl")
    assert export.status_code == 200
    rows = [json.loads(line) for line in export.text.split("\n") if line.strip()]
    assert any(r["assistant"].startswith("# Tidal energy storage") for r in rows), rows


def test_without_overlap_removal_the_router_would_repeat_sentences(
    client, upload_dir, ephemeral_chroma, small_chunks
):
    """The mutation check for the de-duplication: switch it off and the same
    request hands the agent the carried-over sentences twice."""
    doc_id = _upload_pdf(client)
    with patch.object(document_text_service, "strip_overlap", lambda prev, cur, max_words=None: cur):
        resp, agent = _extract(client, doc_id)
    assert resp.status_code == 200, resp.text
    (_, text), _ = agent.call_args
    assert any(text.count(s) > 1 for s in SENTENCES)


def test_with_only_the_transcript_cache_read_a_pdf_422s(
    client, upload_dir, ephemeral_chroma, small_chunks
):
    """The mutation check for the store: the old router read only
    ``transcript_cache``, which holds nothing for a PDF."""
    doc_id = _upload_pdf(client)
    with patch.object(
        document_text_service, "reassemble_chunks", lambda chunks: ""
    ):
        resp, agent = _extract(client, doc_id)
    assert resp.status_code == 422
    assert not agent.called


# ---------------------------------------------------------------------------
# Pasted page
# ---------------------------------------------------------------------------


def test_visible_pasted_page_gets_a_knowledge_report(
    client, db, ephemeral_chroma, small_chunks
):
    doc_id = _paste(client)

    resp, agent = _extract(client, doc_id)

    assert resp.status_code == 200, resp.text
    assert resp.json()["source_type"] == "article"
    (document, text), _ = agent.call_args
    assert document.source_type == "article"
    _assert_every_sentence_once_in_order(text)


def test_pasted_page_another_tenant_cannot_see_404s(
    client, ephemeral_chroma, small_chunks, other_tenant_headers
):
    doc_id = _paste(client)

    resp, agent = _extract(client, doc_id, headers=other_tenant_headers)

    assert resp.status_code == 404
    assert not agent.called
    # And the GET is closed to them too, once the owner has a report.
    assert _extract(client, doc_id)[0].status_code == 200
    assert client.get(
        f"/api/v1/videos/{doc_id}/knowledge", headers=other_tenant_headers
    ).status_code == 404


def test_document_with_no_chunks_yet_422s(client, db, test_user, ephemeral_chroma):
    """A visible document whose ingest has not written any text: nothing to
    extract from, so 422 (and the agent never runs)."""
    from app.services import visibility_service

    doc = Document(
        source_type="reddit_post",
        source_id="reddit:pending1",
        source_url="https://www.reddit.com/r/x/comments/pending1/",
        title="A thread still being fetched",
        url="https://www.reddit.com/r/x/comments/pending1/",
        transcript_status="pending",
    )
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], test_user.id)

    resp, agent = _extract(client, doc.document_id)
    assert resp.status_code == 422
    assert not agent.called

"""Echo share processing (S-3.7.2): text, links, text files, and the pipeline.

External calls (the article extractor, the YouTube Data API, the paste
connector, the task queue) are patched; Chroma is in-memory with the real
embedder, because "the share is embedded under its id with its tenant" is
what the per-share and whole-brain deletes depend on.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.config import settings
from app.models.document_visibility import DocumentVisibility
from app.models.share import Share
from app.services import auth_service, echo_processing_service, echo_vectors
from app.services.article_extraction.extractor import ExtractionResult
from app.sources.types import ExtractedText

SHARES = "/api/v1/echo/shares"
ARTICLE = "https://example.org/essays/tariffs"
VIDEO = "https://www.youtube.com/watch?v=abcdefghijk"


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def two(db, tmp_path, monkeypatch, chroma):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha = _studio(db, "proc-a@example.com")
    b, hb = _studio(db, "proc-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


def _article(text="Tariffs raise prices for the importing country's consumers first."):
    return ExtractionResult(text=text, title="Who pays for tariffs", author="A. Economist",
                            language="en", word_count=len(text.split()), source="trafilatura")


def _process(db, share_id):
    return echo_processing_service.process_share(db, share_id)


def _vector(chroma, share_id):
    col = chroma.get_collection(settings.CHROMA_SHARES_COLLECTION_NAME)
    got = col.get(ids=[echo_vectors.share_vector_id(share_id)], include=["documents", "metadatas"])
    return (got["documents"] or [None])[0], (got["metadatas"] or [None])[0]


# ---------------------------------------------------------------------------
# Per content type
# ---------------------------------------------------------------------------


def test_text_share_is_embedded_with_its_tenant_and_authorship(unauthenticated_client, db, two, chroma):
    s = unauthenticated_client.post(SHARES, json={"text": "Tariffs are a tax on your own consumers.",
                                                  "author_is_tenant": True, "annotation": "my line"},
                                    headers=two["ha"]).json()
    assert s["processing_state"] == "pending", "processing is off in the suite until called"
    assert _process(db, s["id"]).state == "processed"

    row = db.get(Share, s["id"])
    assert row.processing_state == "processed" and row.embedding_id == f"share:{s['id']}"
    doc, meta = _vector(chroma, s["id"])
    assert "my line" in doc and "tax on your own consumers" in doc
    assert meta["tenant_id"] == two["a"].id and meta["author_is_tenant"] is True
    assert meta["voice_eligible"] is True and meta["content_type"] == "text_snippet"


def test_context_only_shares_are_never_voice_eligible(unauthenticated_client, db, two, chroma):
    s = unauthenticated_client.post(SHARES, json={"text": "Someone else's WhatsApp line."},
                                    headers=two["ha"]).json()
    _process(db, s["id"])
    row = db.get(Share, s["id"])
    assert echo_processing_service.voice_eligible(row) is False
    assert _vector(chroma, s["id"])[1]["voice_eligible"] is False


def test_article_link_is_extracted_and_offered_to_the_library(unauthenticated_client, db, two, chroma):
    s = unauthenticated_client.post(SHARES, json={"url": ARTICLE}, headers=two["ha"]).json()
    with patch("app.services.article_extraction.extractor.extract_text", return_value=_article()) as ex:
        assert _process(db, s["id"]).state == "processed"
    ex.assert_called_once_with(ARTICLE)
    got = unauthenticated_client.get(f"{SHARES}/{s['id']}", headers=two["ha"]).json()
    assert got["extracted_text"].startswith("Tariffs raise prices")
    p = got["processing"]
    assert p["title"] == "Who pays for tariffs" and p["author"] == "A. Economist"
    assert p["extractor"] == "trafilatura" and p["embedded"] is True and p["processed_at"]
    assert p["library_offer"] == {"eligible": True, "reason": None, "source_type": "article"}
    assert "Who pays for tariffs" in _vector(chroma, s["id"])[0]


@pytest.mark.parametrize("url,vid", [
    (VIDEO, "abcdefghijk"),
    ("https://youtu.be/abcdefghijk?t=30", "abcdefghijk"),
    ("https://www.youtube.com/shorts/abcdefghijk", "abcdefghijk"),
])
def test_youtube_link_resolves_title_and_description_without_a_library_offer(
    unauthenticated_client, db, two, chroma, url, vid
):
    s = unauthenticated_client.post(SHARES, json={"url": url}, headers=two["ha"]).json()
    details = {vid: {"title": "Tariffs, explained", "channel_name": "Econ Channel",
                     "description": "Why tariffs raise prices.", "published_at": "2025-01-01T00:00:00Z",
                     "duration_seconds": 600}}
    with patch("app.services.youtube_service.get_video_details", return_value=details) as yt:
        assert _process(db, s["id"]).state == "processed"
    yt.assert_called_once_with([vid])
    got = unauthenticated_client.get(f"{SHARES}/{s['id']}", headers=two["ha"]).json()
    assert "Tariffs, explained" in got["extracted_text"] and "Why tariffs raise prices." in got["extracted_text"]
    assert got["processing"]["author"] == "Econ Channel"
    assert got["processing"]["library_offer"]["eligible"] is False
    assert "research run" in got["processing"]["library_offer"]["reason"]


def test_text_file_is_decoded(unauthenticated_client, db, two, chroma):
    txt = unauthenticated_client.post(f"{SHARES}/upload", headers=two["ha"],
                                      files={"file": ("keep.txt", "Keep note: शब्द and words".encode(), "text/plain")}).json()
    assert _process(db, txt["id"]).state == "processed"
    assert db.get(Share, txt["id"]).extracted_text == "Keep note: शब्द and words"
    got = unauthenticated_client.get(f"{SHARES}/{txt['id']}", headers=two["ha"]).json()
    assert got["processing"]["extractor"] == "text_file" and got["processing"]["embedded"] is True
    # Images, recordings and PDFs: tests/test_routers/test_echo_media.py


# ---------------------------------------------------------------------------
# Fail-soft and retry
# ---------------------------------------------------------------------------


def test_a_failed_extraction_stays_browsable_and_retry_recovers(unauthenticated_client, db, two, chroma, monkeypatch):
    s = unauthenticated_client.post(SHARES, json={"url": ARTICLE}, headers=two["ha"]).json()
    with patch("app.services.article_extraction.extractor.extract_text", return_value=None):
        assert _process(db, s["id"]).state == "failed"
    got = unauthenticated_client.get(f"{SHARES}/{s['id']}", headers=two["ha"]).json()
    assert got["processing_state"] == "failed"
    assert "No readable text" in got["processing"]["error"]
    assert s["id"] in {x["id"] for x in unauthenticated_client.get(SHARES, headers=two["ha"]).json()["items"]}

    # Retry through the endpoint, processed inline by patching the queue.
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "celery")
    with patch("app.services.task_routing_service.dispatch_for_user",
               side_effect=lambda task, user, sid: _process(db, sid)), \
         patch("app.services.article_extraction.extractor.extract_text", return_value=_article()):
        r = unauthenticated_client.post(f"{SHARES}/{s['id']}/process", headers=two["ha"])
    assert r.status_code == 200
    db.expire_all()
    row = db.get(Share, s["id"])
    assert row.processing_state == "processed"
    assert "error" not in json.loads(row.processing_json)


def test_an_unexpected_error_fails_soft(unauthenticated_client, db, two, chroma):
    s = unauthenticated_client.post(SHARES, json={"url": ARTICLE}, headers=two["ha"]).json()
    with patch("app.services.article_extraction.extractor.extract_text", side_effect=ValueError("boom")):
        result = _process(db, s["id"])
    assert result.state == "failed" and "ValueError" in result.reason


def test_an_embedding_failure_keeps_the_text(unauthenticated_client, db, two, chroma):
    s = unauthenticated_client.post(SHARES, json={"text": "kept even if Chroma fails"}, headers=two["ha"]).json()
    with patch.object(echo_vectors, "upsert_share_vector", side_effect=RuntimeError("chroma down")):
        assert _process(db, s["id"]).state == "processed"
    row = db.get(Share, s["id"])
    assert json.loads(row.processing_json)["embedded"] is False and row.embedding_id is None


def test_processing_a_deleted_share_is_a_no_op(db):
    assert echo_processing_service.process_share(db, "gone").state == "missing"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_creating_a_share_queues_it_for_its_tenant(unauthenticated_client, two, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "celery")
    from app.tasks.echo_tasks import process_share_task

    with patch("app.services.task_routing_service.dispatch_for_user") as dispatch:
        s = unauthenticated_client.post(SHARES, json={"text": "queue me"}, headers=two["ha"]).json()
    task, user, share_id = dispatch.call_args.args
    assert task is process_share_task and user.id == two["a"].id and share_id == s["id"]


def test_a_queue_failure_leaves_the_share_pending(unauthenticated_client, two, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "celery")
    with patch("app.services.task_routing_service.dispatch_for_user", side_effect=OSError("redis down")):
        r = unauthenticated_client.post(SHARES, json={"text": "still saved"}, headers=two["ha"])
    assert r.status_code == 201 and r.json()["processing_state"] == "pending"


# ---------------------------------------------------------------------------
# Library offer
# ---------------------------------------------------------------------------


class _FakeConnector:
    def __init__(self):
        self.calls = 0

    def fetch_text(self, candidate):
        self.calls += 1
        return ExtractedText(
            segments=[{"text": "Tariffs raise prices first.", "start": 0.0, "duration": 0.0}],
            language="en", text_source="trafilatura", word_count=4,
            extra={"extracted_title": "Who pays for tariffs", "extracted_author": "A. Economist"},
        )


def test_library_offer_ingests_for_the_sharer_only(unauthenticated_client, db, two, chroma):
    s = unauthenticated_client.post(SHARES, json={"url": ARTICLE}, headers=two["ha"]).json()
    with patch("app.services.article_extraction.extractor.extract_text", return_value=_article()):
        _process(db, s["id"])
    fake = _FakeConnector()
    with patch("app.routers.library._connector_for", return_value=fake), \
         patch("app.routers.library.chroma_service.insert_chunks"):
        r = unauthenticated_client.post(f"{SHARES}/{s['id']}/library", headers=two["ha"])
        again = unauthenticated_client.post(f"{SHARES}/{s['id']}/library", headers=two["ha"])
    assert r.status_code == 200, r.text
    doc_id = r.json()["linked_document_id"]
    assert doc_id and again.json()["linked_document_id"] == doc_id and fake.calls == 1
    grants = {(g.tenant_id) for g in db.query(DocumentVisibility).filter(DocumentVisibility.document_id == doc_id)}
    assert grants == {two["a"].id}, "visible to the sharer only (D-063)"
    titles = [d["title"] for d in unauthenticated_client.get("/api/v1/library/videos", headers=two["hb"]).json()]
    assert "Who pays for tariffs" not in titles


def test_library_offer_refuses_what_it_cannot_ingest(unauthenticated_client, db, two, chroma):
    text = unauthenticated_client.post(SHARES, json={"text": "just words"}, headers=two["ha"]).json()
    video = unauthenticated_client.post(SHARES, json={"url": VIDEO}, headers=two["ha"]).json()
    details = {"abcdefghijk": {"title": "t", "channel_name": "c", "description": "d"}}
    with patch("app.services.youtube_service.get_video_details", return_value=details):
        _process(db, video["id"])
    unprocessed = unauthenticated_client.post(SHARES, json={"url": ARTICLE}, headers=two["ha"]).json()
    for sid in (text["id"], video["id"], unprocessed["id"]):
        assert unauthenticated_client.post(f"{SHARES}/{sid}/library", headers=two["ha"]).status_code == 409
    r = unauthenticated_client.post(f"{SHARES}/{video['id']}/library", headers=two["ha"])
    assert "research run" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Two tenants, and the stores the deletes sweep
# ---------------------------------------------------------------------------


def test_another_tenant_cannot_process_or_offer_my_share(unauthenticated_client, two):
    s = unauthenticated_client.post(SHARES, json={"url": ARTICLE}, headers=two["ha"]).json()
    assert unauthenticated_client.post(f"{SHARES}/{s['id']}/process", headers=two["hb"]).status_code == 404
    assert unauthenticated_client.post(f"{SHARES}/{s['id']}/library", headers=two["hb"]).status_code == 404


def test_processed_vectors_are_removed_by_both_deletes(unauthenticated_client, db, two, chroma):
    one = unauthenticated_client.post(SHARES, json={"text": "first"}, headers=two["ha"]).json()
    other = unauthenticated_client.post(SHARES, json={"text": "second"}, headers=two["ha"]).json()
    theirs = unauthenticated_client.post(SHARES, json={"text": "b's"}, headers=two["hb"]).json()
    for sid in (one["id"], other["id"], theirs["id"]):
        _process(db, sid)
    assert unauthenticated_client.delete(f"{SHARES}/{one['id']}", headers=two["ha"]).json()["vectors"] == 1
    r = unauthenticated_client.delete("/api/v1/echo/brain", params={"confirm": "delete-everything"}, headers=two["ha"])
    assert r.json()["removed"]["vectors"][settings.CHROMA_SHARES_COLLECTION_NAME] == 1
    assert echo_vectors.count_tenant_vectors(two["a"].id)[settings.CHROMA_SHARES_COLLECTION_NAME] == 0
    assert echo_vectors.count_tenant_vectors(two["b"].id)[settings.CHROMA_SHARES_COLLECTION_NAME] == 1

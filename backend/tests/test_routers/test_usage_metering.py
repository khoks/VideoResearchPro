"""Usage metering at the production callers: routers and the services they
call (E-5.2, status plan item 10).

Each test drives the entry point a user triggers, with only the provider
client replaced below ``get_llm_for`` (``tests/usage_helpers.metered_llms``),
and asserts the ``usage_records`` rows it leaves: the right tenant, the right
feature. Where an agent is replaced, its stand-in makes its calls through the
production factory exactly as the agent does (``call_llm``).

Mutation checks (each makes the test named beside it fail, and is pinned as
a ``test_mutation_*`` below): dropping the feature from
``library_qa_service.ask`` (``test_library_qa_is_charged_to_library_qa``),
taking the scope out of ``byok_context`` (``test_knowledge_extraction_...``),
taking the scope out of the clarify route
(``test_job_clarify_is_charged_to_the_asker``), and taking the scope out of
``upload_pdf`` (``test_uploading_a_pdf_charges_the_english_rendering_...``).
"""
from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.job import Job
from app.services import auth_service, usage_service
from tests.usage_helpers import (  # noqa: F401
    CLARIFY_JSON,
    call_llm,
    metered_llms,
    tenants_with_usage,
    usage_rows,
    youtube_network,
)


def _completed_job(db, tenant_id):
    job = Job(job_type="topic", topic="tariffs", status="completed", num_videos=1, tenant_id=tenant_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _three(feature, calls=1, tin=100, tout=20):
    return {(feature, "llm_calls"): calls, (feature, "llm_tokens_in"): tin * calls, (feature, "llm_tokens_out"): tout * calls}


# ---------------------------------------------------------------- job Q&A


def test_job_clarify_is_charged_to_the_asker(client, db, test_user, metered_llms):
    metered_llms.reply = CLARIFY_JSON
    job = _completed_job(db, test_user.id)
    r = client.post(f"/api/v1/jobs/{job.id}/qa/clarify", json={"question": "who pays?"})
    assert r.status_code == 200, r.text
    assert usage_rows(db, test_user.id) == _three("job_qa")


def test_mutation_job_clarify_without_its_scope_records_nothing(client, db, test_user, metered_llms, monkeypatch):
    from app.routers import qa as qa_router

    monkeypatch.setattr(qa_router.usage_service, "metered", lambda *a, **k: nullcontext())
    metered_llms.reply = CLARIFY_JSON
    job = _completed_job(db, test_user.id)
    assert client.post(f"/api/v1/jobs/{job.id}/qa/clarify", json={"question": "who pays?"}).status_code == 200
    assert usage_rows(db, test_user.id) == {}


# ---------------------------------------------------------------- library Q&A


def test_library_clarify_is_charged_to_library_qa(client, db, test_user, metered_llms):
    metered_llms.reply = CLARIFY_JSON
    r = client.post("/api/v1/library/qa/clarify", json={"question": "who pays?"})
    assert r.status_code == 200, r.text
    assert usage_rows(db, test_user.id) == _three("library_qa")


def _library_agent(**kwargs):
    # The library agent calls a job-Q&A use case (sub-query expansion) and
    # its own answer use case.
    call_llm("qa_sub_query_expansion")
    call_llm("library_qa_formulate_answer")
    return {"answer": "Answer.", "references": []}


def _ask_library(client):
    with (
        patch("app.agents.qa_agent.run_library_qa_agent", side_effect=_library_agent),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        return client.post("/api/v1/library/qa", json={"question": "who pays for tariffs?"})


def test_library_qa_is_charged_to_library_qa(client, db, test_user, metered_llms):
    r = _ask_library(client)
    assert r.status_code == 200, r.text
    assert usage_rows(db, test_user.id) == _three("library_qa", calls=2)


def test_mutation_library_qa_without_its_feature_bills_job_qa(client, db, test_user, metered_llms, monkeypatch):
    """Drop ``feature="library_qa"`` from library_qa_service.ask and the
    sub-query call is billed as job Q&A, which the test above catches."""
    real = usage_service.metered
    monkeypatch.setattr(usage_service, "metered", lambda db, tenant_id, feature=None: real(db, tenant_id))
    assert _ask_library(client).status_code == 200
    rows = usage_rows(db, test_user.id)
    assert rows[("job_qa", "llm_calls")] == 1 and rows[("library_qa", "llm_calls")] == 1


def test_a_shelf_question_is_library_qa_too(client, db, test_user, metered_llms):
    test_user.tier = "pro"  # shelves are Pro+
    db.commit()
    shelf = client.post("/api/v1/shelves", json={"name": "Trade"}).json()
    with (
        patch("app.agents.qa_agent.run_library_qa_agent", side_effect=_library_agent),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        r = client.post(f"/api/v1/shelves/{shelf['id']}/qa", json={"question": "who pays?"})
    assert r.status_code == 200, r.text
    assert usage_rows(db, test_user.id) == _three("library_qa", calls=2)


# ---------------------------------------------------------------- Q&A history chat


def test_history_chat_is_charged_to_qa_history(client, db, test_user, metered_llms):
    async def agent(**kwargs):
        call_llm("qa_history_refine_context")
        call_llm("qa_history_formulate_answer")
        return {"answer": "You learned X.", "references": []}

    with (
        patch("app.agents.qa_history_agent.run_qa_history_chat_agent", side_effect=agent),
        patch("app.routers.qa_history.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        r = client.post("/api/v1/qa-history/chat", json={"question": "what did I learn?"})
    assert r.status_code == 200, r.text
    assert usage_rows(db, test_user.id) == _three("qa_history", calls=2)


# ---------------------------------------------------------------- knowledge


@pytest.fixture
def visible_video(db, test_user):
    from datetime import datetime, timezone

    from app.models.document import Document
    from app.models.transcript_cache import TranscriptCache
    from app.services import visibility_service

    doc = Document(video_id="vidUsage001", title="Tariffs", url="https://www.youtube.com/watch?v=vidUsage001",
                   duration_seconds=60, transcript_status="fetched")
    db.add(doc)
    db.add(TranscriptCache(video_id="vidUsage001", language="en", fetched_at=datetime.now(timezone.utc),
                           segments_json=json.dumps([{"text": "Tariffs are taxes.", "start": 0.0, "duration": 3.0}])))
    db.commit()
    db.refresh(doc)
    visibility_service.grant(db, [doc.document_id], test_user.id)
    return doc


def _knowledge_agent(video, text, **_kw):
    call_llm("knowledge_extract_batch")
    call_llm("knowledge_synthesize_report")
    return {"topics": ["trade"], "concepts": [], "events": [], "facts": [], "knowledge_report_md": "# Trade"}


def test_knowledge_extraction_is_charged_to_the_requester(client, db, test_user, metered_llms, visible_video):
    with patch("app.agents.knowledge_agent.run_knowledge_extract_agent", side_effect=_knowledge_agent):
        r = client.post(f"/api/v1/videos/{visible_video.video_id}/extract-knowledge")
    assert r.status_code == 200, r.text
    assert usage_rows(db, test_user.id) == _three("knowledge", calls=2)


def test_mutation_byok_context_without_a_scope_leaves_knowledge_unmetered(
    client, db, test_user, metered_llms, visible_video, monkeypatch
):
    """The knowledge route is metered only by the scope ``byok_context``
    opens; take it out and the test above fails."""
    from app.services import llm_service

    monkeypatch.setattr(llm_service.usage_service, "metered", lambda *a, **k: nullcontext())
    with patch("app.agents.knowledge_agent.run_knowledge_extract_agent", side_effect=_knowledge_agent):
        assert client.post(f"/api/v1/videos/{visible_video.video_id}/extract-knowledge").status_code == 200
    assert usage_rows(db, test_user.id) == {}


# ---------------------------------------------------------------- suggestions


def test_suggestions_route_is_charged_to_the_reader(client, db, test_user, metered_llms, monkeypatch):
    from app.services import llm_smoke, suggestion_service
    from tests.test_routers.test_suggestions import GENERATED, _job, fake_encode

    metered_llms.reply = json.dumps({"suggestions": GENERATED})
    monkeypatch.setattr(suggestion_service, "_encode", fake_encode)
    monkeypatch.setattr(suggestion_service.chroma_service, "query_qa_collection", lambda *a, **k: [])
    monkeypatch.setattr(llm_smoke._STATUS, "is_use_case_available", lambda uc: True)
    job = _job(db, test_user.id)
    r = client.get(f"/api/v1/suggestions?context=job:{job.id}")
    assert r.status_code == 200, r.text
    assert r.json()["generated"] is True
    assert usage_rows(db, test_user.id) == _three("suggestions")


# ---------------------------------------------------------------- ingest (pasted URL)


def test_pasting_a_url_charges_the_english_rendering_to_the_paster(client, db, test_user, metered_llms):
    from tests.test_routers.test_library_paste_urls import _FakeConnector, _extracted

    def insert_chunks(chunks):
        # What chroma_service.insert_chunks does for a non-English source.
        call_llm("code_mixing_render_english")
        return len(chunks)

    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(_extracted())),
        patch("app.routers.library.chroma_service.insert_chunks", side_effect=insert_chunks),
    ):
        r = client.post("/api/v1/library/paste-urls", json={"urls": ["https://example.com/hindi-essay"]})
    assert r.status_code == 201, r.text
    assert usage_rows(db, test_user.id) == _three("ingest")


# ---------------------------------------------------------------- ingest (PDF upload)


def _hinglish_pdf():
    from app.sources.types import ExtractedText

    return ExtractedText(
        segments=[
            {"text": "Yeh tariff ka asar hai, aur isliye importers ko zyada paisa dena padta hai. "
                     "Hum log samajhte hain ki sarkar ko yeh nahi karna chahiye.",
             "start": 0.0, "duration": 0.0, "extra": {"kind": "page", "comment_url": "#page=1"}},
            {"text": "Mera kehna hai ki yeh niti galat hai, kyunki isse mehngai badhti hai.",
             "start": 1.0, "duration": 0.0, "extra": {"kind": "page", "comment_url": "#page=2"}},
        ],
        language="hi",
        text_source="pdf",
        word_count=40,
        extra={"page_count": 2},
    )


def _upload_hinglish_pdf(client, monkeypatch, tmp_path, metered_llms):
    """``POST /library/upload-pdf`` with a romanised-Hindi PDF. Chunking runs
    for real (it tags the chunks as Hindi); the Chroma write is replaced by
    its first step, ``code_mixing_service.ensure_english_renderings``, run
    for real, so the rendering call goes through ``get_llm_for``."""
    from app.services import code_mixing_service
    from tests.test_routers.test_library_upload_pdf import _FakeConnector

    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))
    monkeypatch.setattr(settings, "CODE_MIX_ENGLISH_RENDERING_ENABLED", True)
    metered_llms.reply = json.dumps({"chunks": [{"i": 0, "english": "This is the effect of the tariff."}]})
    rendered: list = []

    def insert_chunks(chunks):
        code_mixing_service.ensure_english_renderings(chunks)
        rendered.extend(c["metadata"].get("text_en") for c in chunks)
        return len(chunks)

    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(_hinglish_pdf())),
        patch("app.routers.library.chroma_service.insert_chunks", side_effect=insert_chunks),
    ):
        r = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": ("tariffs-hi.pdf", b"%PDF-1.4\n% usage metering\n", "application/pdf")},
        )
    assert r.status_code == 201, r.text
    assert rendered == ["This is the effect of the tariff."], "the English rendering ran"
    return r


def test_uploading_a_pdf_charges_the_english_rendering_to_the_uploader(client, db, test_user, metered_llms,
                                                                       monkeypatch, tmp_path):
    _upload_hinglish_pdf(client, monkeypatch, tmp_path, metered_llms)
    assert usage_rows(db, test_user.id) == _three("ingest")
    assert tenants_with_usage(db) == {test_user.id}


def test_mutation_a_pdf_upload_without_its_scope_charges_no_one(client, db, test_user, metered_llms,
                                                               monkeypatch, tmp_path):
    """Take the scope out of ``upload_pdf``: the rendering still runs, and
    is charged to no one, which the test above catches."""
    monkeypatch.setattr("app.routers.library.usage_service.metered", lambda *a, **k: nullcontext())
    _upload_hinglish_pdf(client, monkeypatch, tmp_path, metered_llms)
    assert usage_rows(db, test_user.id) == {}
    assert tenants_with_usage(db) == set()


# ---------------------------------------------------------------- Echo


def _studio(db):
    user = auth_service.create_user(db, email=f"u-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def test_a_speak_as_me_draft_is_charged_to_echo_draft(unauthenticated_client, db, metered_llms, monkeypatch):
    from app.services import echo_draft_service
    from tests.test_routers.test_echo_drafts import _enable
    from tests.test_services.test_echo_draft import deps

    user, headers = _studio(db)
    _enable(db, user, monkeypatch)

    def real_calls(db_, user_):
        # The stand-in context sources of the service tests, with the three
        # model calls made through the production _llm (get_llm_for).
        d, _ = deps()
        canned = {"classify": d.classify, "draft": d.draft, "critique": d.critique}
        for name, use_case, cap in (("classify", "echo_classify_intent", 600), ("draft", "echo_draft", 1500),
                                    ("critique", "echo_critique", 900)):
            real = echo_draft_service._llm(use_case, user_.id, db_, cap)

            def call(prompt, real=real, fake=canned[name]):
                real(prompt)
                return fake(prompt)

            setattr(d, name, call)
        return d

    monkeypatch.setattr(echo_draft_service, "_real_deps", real_calls)
    r = unauthenticated_client.post("/api/v1/echo/draft", json={"message": "Who really pays for tariffs?"}, headers=headers)
    assert r.status_code == 201, r.text
    rows = usage_rows(db, user.id)
    assert rows[("echo_draft", "llm_calls")] >= 3
    assert rows[("echo_draft", "llm_tokens_in")] == 100 * rows[("echo_draft", "llm_calls")]
    assert {f for f, _ in rows} == {"echo_draft"}


def test_a_youtube_share_charges_its_metadata_lookup_to_the_sharer(
    unauthenticated_client, db, tmp_path, monkeypatch, youtube_network
):
    from app.services import echo_processing_service

    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    vectors = MagicMock()
    vectors.upsert_share_vector.return_value = "share:vector"
    monkeypatch.setattr(echo_processing_service, "echo_vectors", vectors)
    youtube_network.responses = {"videos": {"items": [{
        "id": "abcdefghijk",
        "snippet": {"title": "Tariffs, explained", "channelTitle": "Econ", "description": "Why prices rise."},
        "contentDetails": {"duration": "PT10M"},
    }]}}
    user, headers = _studio(db)
    share = unauthenticated_client.post(
        "/api/v1/echo/shares", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"}, headers=headers
    ).json()
    assert echo_processing_service.process_share(db, share["id"]).state == "processed"
    assert usage_rows(db, user.id) == {("video_metadata", "youtube_units"): 1}


# ---------------------------------------------------------------- the summary endpoint


def test_usage_endpoint_returns_only_the_callers_usage(client, db, test_user):
    from datetime import datetime, timezone

    from app.models.usage_record import UsageRecord

    today = datetime.now(timezone.utc).date()
    db.add_all([
        UsageRecord(tenant_id=test_user.id, day=today, feature="report", metric="llm_tokens_in", amount=1234),
        UsageRecord(tenant_id=test_user.id, day=today, feature="search", metric="youtube_units", amount=200),
        UsageRecord(tenant_id="someone-else", day=today, feature="library_qa", metric="llm_tokens_in", amount=999),
    ])
    db.commit()
    r = client.get("/api/v1/usage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["today"] == today.isoformat() and body["window_days"] == 30
    assert [f["feature"] for f in body["features"]] == ["report", "search"]
    assert body["features"][0]["label"] == "Reports"
    assert body["features"][0]["today"]["llm_tokens_in"] == 1234
    assert body["totals"]["last_30_days"] == {"llm_tokens_in": 1234, "llm_tokens_out": 0, "llm_calls": 0, "youtube_units": 200}


def test_usage_endpoint_requires_sign_in(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/usage").status_code == 401


def test_usage_after_real_calls_shows_on_the_endpoint(client, db, test_user, metered_llms):
    metered_llms.reply = CLARIFY_JSON
    client.post("/api/v1/library/qa/clarify", json={"question": "who pays?"})
    body = client.get("/api/v1/usage").json()
    assert body["features"] == [{
        "feature": "library_qa", "label": "Library Q&A",
        "today": {"llm_tokens_in": 100, "llm_tokens_out": 20, "llm_calls": 1, "youtube_units": 0},
        "last_30_days": {"llm_tokens_in": 100, "llm_tokens_out": 20, "llm_calls": 1, "youtube_units": 0},
    }]
    assert tenants_with_usage(db) == {test_user.id}

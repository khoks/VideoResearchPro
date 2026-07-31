"""S-5.7.1 — regression tests for four demonstrated cross-tenant leaks.

Each of these was live on 2026-07-31 and reproducible against real data:

1. `GET /library/videos` returned every tenant's documents AND the *job topics*
   of every other user — the topic string being the more sensitive half.
2. `DELETE /library/qa/{id}` fetched by primary key and deleted, so any user
   could destroy any other user's exchange.
3. `GET /exports/*` streamed every tenant's Q&A and knowledge artifacts as
   fine-tune data to anyone logged in.
4. `WS /ws/jobs` subscribed to any `job_id` the client named, streaming another
   tenant's progress, status and error text.

These tests assert the *absence* of other tenants' data, which is the only
direction that matters — a passing "I can see my own row" test would not have
caught any of the four.
"""
import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.services import dataset_service


OTHER = "other-tenant-uuid"


@pytest.fixture
def foreign_data(db, test_user):
    """A second tenant's job, document and Q&A — none of it the caller's."""
    job = Job(
        id="foreign-job",
        tenant_id=OTHER,
        job_type="topic",
        topic="SECRET COMPETITOR RESEARCH",
        status="completed",
    )
    doc = Document(
        document_id="foreign-doc",
        video_id="foreignvid1",
        title="Foreign video",
        url="https://youtu.be/foreignvid1",
        transcript_status="completed",
        knowledge_report_md="# foreign knowledge",
        extracted_knowledge_json='{"topics":["x"],"concepts":[],"events":[]}',
    )
    link = JobVideo(job_id="foreign-job", video_id="foreignvid1", approved=True)
    qa = LibraryQAExchange(
        id="foreign-qa",
        tenant_id=OTHER,
        question="foreign question",
        answer="foreign answer",
    )
    db.add_all([job, doc, link, qa])
    db.commit()
    return {"job": job, "doc": doc, "qa": qa}


# --- 1. library browse ------------------------------------------------------
def test_library_browse_hides_other_tenants_documents(client, foreign_data):
    r = client.get("/api/v1/library/videos")
    assert r.status_code == 200
    assert "foreignvid1" not in {v["id"] for v in r.json()}


def test_library_browse_never_leaks_another_tenants_job_topic(client, foreign_data):
    """The topic string is the sensitive half — it says what they researched."""
    r = client.get("/api/v1/library/videos")
    assert r.status_code == 200
    assert "SECRET COMPETITOR RESEARCH" not in r.text


# --- 2. cross-tenant delete -------------------------------------------------
def test_cannot_delete_another_tenants_qa_exchange(client, db, foreign_data):
    r = client.delete("/api/v1/library/qa/foreign-qa")
    assert r.status_code == 404, "a foreign id must be indistinguishable from a missing one"
    # And it must still exist.
    assert db.get(LibraryQAExchange, "foreign-qa") is not None


# --- 3. dataset exports -----------------------------------------------------
def test_qa_export_excludes_other_tenants(db, test_user, foreign_data):
    rows = list(dataset_service.iter_qa_rows(db, test_user.id))
    assert all("foreign" not in q and "foreign" not in a for q, a in rows)


def test_knowledge_export_excludes_other_tenants(db, test_user, foreign_data):
    rows = list(dataset_service.iter_knowledge_rows(db, test_user.id))
    assert all("foreign knowledge" not in report for *_, report in rows)


def test_export_endpoint_streams_only_the_callers_data(client, foreign_data):
    r = client.get("/api/v1/exports/qa-dataset/openai.jsonl")
    assert r.status_code == 200
    assert "foreign question" not in r.text
    assert "foreign answer" not in r.text


# --- 4. websocket job subscription -----------------------------------------
def test_ws_ownership_check_rejects_foreign_job(db, test_user, foreign_data):
    from tests.conftest import TestingSessionLocal
    from app.routers.ws import _owns_job

    assert _owns_job(OTHER, "foreign-job", TestingSessionLocal) is True
    assert _owns_job(test_user.id, "foreign-job", TestingSessionLocal) is False


def test_ws_ownership_check_fails_closed_on_unknown_job(db, test_user):
    from tests.conftest import TestingSessionLocal
    from app.routers.ws import _owns_job

    assert _owns_job(test_user.id, "does-not-exist", TestingSessionLocal) is False


def test_ws_ownership_check_fails_closed_on_error():
    """A DB blip must deny the subscription, never allow it."""
    from app.routers.ws import _owns_job

    def _boom():
        raise RuntimeError("db down")

    assert _owns_job("anyone", "any-job", _boom) is False


# --- 5. vector retrieval ----------------------------------------------------
def test_library_qa_retrieval_is_restricted_to_visible_documents(monkeypatch):
    """The sharpest leak: library Q&A searched EVERY tenant's transcripts.

    Chroma has no tenant concept, so the caller must pass the visible set.
    """
    from app.agents import qa_agent

    captured = {}

    def _fake_query(query_text, n_results=None, video_ids=None, distance_threshold=None):
        captured["video_ids"] = video_ids
        return []

    monkeypatch.setattr(qa_agent.chroma_service, "query_collection", _fake_query)
    qa_agent._query_library("anything", ["mine1", "mine2"])
    assert captured["video_ids"] == ["mine1", "mine2"]


def test_empty_visible_set_retrieves_nothing_rather_than_everything(monkeypatch):
    """An empty grant list must NOT degrade into an unrestricted search."""
    from app.agents import qa_agent

    captured = {}

    def _fake_query(query_text, n_results=None, video_ids=None, distance_threshold=None):
        captured["video_ids"] = video_ids
        return []

    monkeypatch.setattr(qa_agent.chroma_service, "query_collection", _fake_query)
    qa_agent._query_library("anything", [])
    assert captured["video_ids"] == [], "empty must stay empty, never become None"

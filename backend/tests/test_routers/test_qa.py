import json
from unittest.mock import MagicMock, patch

from app.models.job import Job
from app.models.qa_exchange import QAExchange


def _make_completed_job(
    db, report_path="/fake/path/report.html", tenant_id: str | None = None
):
    """Build a completed topic Job for the report endpoint tests.

    `tenant_id` (E-5.1 phase 2b) — set to the test user's id so the
    job is reachable via the tenant-scoped report endpoint filter.
    """
    job = Job(
        job_type="topic",
        topic="report auth test",
        status="completed",
        num_videos=1,
        report_path=report_path,
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_report_accepts_query_token(unauthenticated_client, db, auth_token, test_user):
    job = _make_completed_job(db, tenant_id=test_user.id)
    with patch("app.routers.qa.report_service.get_report_html", return_value="<html>ok</html>"):
        response = unauthenticated_client.get(
            f"/api/v1/jobs/{job.id}/report?token={auth_token}"
        )
    assert response.status_code == 200
    assert response.text == "<html>ok</html>"


def test_report_still_accepts_header_token(client, db, test_user):
    job = _make_completed_job(db, tenant_id=test_user.id)
    with patch("app.routers.qa.report_service.get_report_html", return_value="<html>ok</html>"):
        response = client.get(f"/api/v1/jobs/{job.id}/report")
    assert response.status_code == 200


def test_report_rejects_when_no_token(unauthenticated_client, db):
    job = _make_completed_job(db)
    response = unauthenticated_client.get(f"/api/v1/jobs/{job.id}/report")
    assert response.status_code == 401


def test_report_rejects_bad_query_token(unauthenticated_client, db):
    job = _make_completed_job(db)
    response = unauthenticated_client.get(
        f"/api/v1/jobs/{job.id}/report?token=not-a-real-jwt"
    )
    assert response.status_code == 401


def test_qa_history_does_not_accept_query_token(unauthenticated_client, db, auth_token):
    # The scoped query-token fallback must not leak to other QA routes —
    # /qa and /qa/clarify still require the Authorization header.
    job = _make_completed_job(db)
    response = unauthenticated_client.get(
        f"/api/v1/jobs/{job.id}/qa?token={auth_token}"
    )
    assert response.status_code == 401


# ---------- Q&A observability: token accounting + SSE streaming ----------


class _FakeLLMResponse:
    """Stand-in for a LangChain AIMessage with optional usage metadata."""

    def __init__(self, content, usage=None, response_metadata=None):
        self.content = content
        self.usage_metadata = usage
        self.response_metadata = response_metadata or {}


def _fake_llm(content, usage=None):
    llm = MagicMock()
    llm.invoke.return_value = _FakeLLMResponse(content, usage=usage)
    return llm


def _rag_chunk():
    return {
        "text": "some transcript text",
        "metadata": {
            "video_id": "v1",
            "video_title": "Video A",
            "channel_name": "ChA",
            "video_url": "https://www.youtube.com/watch?v=v1",
            "timestamp_start": 42.0,
        },
        "distance": 0.1,
    }


def _qa_agent_patches(with_usage=True):
    """Patch Chroma retrieval + the agent's LLMs (sub-query expansion,
    refine_context, formulate_answer, in that order) + the post-commit
    Q&A-library upsert. The answer cites v1 so reference extraction stays
    deterministic (no 4th LLM call)."""
    usages = (
        [
            {"input_tokens": 10, "output_tokens": 5},
            {"input_tokens": 100, "output_tokens": 20},
            {"input_tokens": 200, "output_tokens": 50},
        ]
        if with_usage
        else [None, None, None]
    )
    fake_llms = [
        _fake_llm("", usage=usages[0]),
        _fake_llm("compacted context", usage=usages[1]),
        _fake_llm("Answer referencing v1 / Video A", usage=usages[2]),
    ]
    return (
        patch(
            "app.agents.qa_agent.chroma_service.query_collection",
            return_value=[_rag_chunk()],
        ),
        patch("app.agents.qa_agent.get_llm_for", side_effect=fake_llms),
        patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True),
    )


def test_qa_persists_token_usage(client, db, test_user):
    from app.services import quota_metering_service

    job = _make_completed_job(db, report_path=None, tenant_id=test_user.id)
    p_chroma, p_llm, p_upsert = _qa_agent_patches()
    with p_chroma, p_llm, p_upsert:
        response = client.post(
            f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me"}
        )

    assert response.status_code == 200
    row = db.query(QAExchange).filter(QAExchange.job_id == job.id).one()
    assert row.prompt_tokens == 310
    assert row.completion_tokens == 75
    # Per-user token metering recorded alongside the row.
    assert quota_metering_service.get_usage(db, test_user.id, "llm_tokens_in") == 310
    assert quota_metering_service.get_usage(db, test_user.id, "llm_tokens_out") == 75


def test_qa_token_columns_stay_null_without_usage_metadata(client, db, test_user):
    job = _make_completed_job(db, report_path=None, tenant_id=test_user.id)
    p_chroma, p_llm, p_upsert = _qa_agent_patches(with_usage=False)
    with p_chroma, p_llm, p_upsert:
        response = client.post(
            f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me"}
        )

    assert response.status_code == 200
    row = db.query(QAExchange).filter(QAExchange.job_id == job.id).one()
    assert row.prompt_tokens is None
    assert row.completion_tokens is None


def test_qa_stream_emits_stage_and_complete_events(client, db, test_user):
    job = _make_completed_job(db, report_path=None, tenant_id=test_user.id)
    # S-1.12.1: retrieval is scoped to approved job videos — link one so
    # the mocked Chroma results flow through.
    from app.models.document import Document
    from app.models.job_video import JobVideo

    db.add(Document(video_id="v1", source_type="video", source_id="v1",
                    title="Video A", channel_id="UC1",
                    url="https://www.youtube.com/watch?v=v1"))
    db.commit()
    db.add(JobVideo(job_id=job.id, video_id="v1", approved=True,
                    selection_reason="search"))
    db.commit()
    p_chroma, p_llm, p_upsert = _qa_agent_patches()
    with p_chroma, p_llm, p_upsert:
        response = client.post(
            f"/api/v1/jobs/{job.id}/qa/stream", json={"question": "tell me"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    payloads = [
        line[len("data: "):]
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert payloads[-1] == "[DONE]"
    events = [json.loads(p) for p in payloads if p != "[DONE]"]

    stage_events = [e for e in events if e["type"] == "stage"]
    assert [e["stage"] for e in stage_events] == [
        "retrieving",
        "refining",
        "formulating",
        "extracting_references",
    ]

    complete_events = [e for e in events if e["type"] == "complete"]
    assert len(complete_events) == 1
    exchange = complete_events[0]["exchange"]
    assert exchange["question"] == "tell me"
    assert exchange["answer"] == "Answer referencing v1 / Video A"
    assert exchange["references"][0]["video_title"] == "Video A"
    assert "created_at" in exchange

    # Row persisted with token accounting, exactly like the sync endpoint.
    row = db.query(QAExchange).filter(QAExchange.job_id == job.id).one()
    assert row.id == exchange["id"]
    assert row.prompt_tokens == 310
    assert row.completion_tokens == 75


def test_qa_stream_requires_auth(unauthenticated_client, db):
    job = _make_completed_job(db)
    response = unauthenticated_client.post(
        f"/api/v1/jobs/{job.id}/qa/stream", json={"question": "tell me"}
    )
    assert response.status_code == 401

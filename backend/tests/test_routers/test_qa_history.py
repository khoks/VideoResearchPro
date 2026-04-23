"""Tests for the Q&A history chat router (Unit 2 — Personal Wiki).

Endpoints:
  POST /api/v1/qa-history/chat        ask a meta-question across all past Q&A
  GET  /api/v1/qa-history/exchanges   list persisted history exchanges
"""

from unittest.mock import AsyncMock, patch


def test_post_qa_history_chat_persists_and_returns_result(client):
    """POST runs the history agent (mocked), persists the exchange, upserts to
    the Q&A collection, and returns answer + references."""
    fake_answer = "You have asked about tariffs three times."
    fake_refs = [
        {
            "source_type": "job",
            "exchange_id": "ex-1",
            "question_preview": "What are the health risks of tariffs?",
            "job_id": "job-abc",
            "original_created_at": "2026-04-01T00:00:00+00:00",
        },
    ]

    agent_mock = AsyncMock(return_value={"answer": fake_answer, "references": fake_refs})

    with patch(
        "app.agents.qa_history_agent.run_qa_history_chat_agent",
        agent_mock,
    ), patch(
        "app.routers.qa_history.chroma_service.upsert_qa_exchange",
        create=True,
    ) as mock_upsert:
        response = client.post(
            "/api/v1/qa-history/chat",
            json={"question": "what have I learned about tariffs"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["answer"] == fake_answer
    assert "id" in data
    assert len(data["references"]) == 1
    assert data["references"][0]["source_type"] == "job"
    assert data["references"][0]["exchange_id"] == "ex-1"
    assert data["references"][0]["job_id"] == "job-abc"

    # The new exchange was indexed into qa_library_global (Unit 1 hook).
    assert mock_upsert.called
    call = mock_upsert.call_args
    # upsert_qa_exchange(exchange, source="history")
    assert call.kwargs.get("source") == "history"
    persisted = call.args[0]
    assert persisted.id == data["id"]


def test_post_qa_history_chat_survives_missing_chroma_api(client):
    """If Unit 1's ``upsert_qa_exchange`` isn't present yet, the POST must
    still succeed — the Chroma side effect is best-effort."""
    agent_mock = AsyncMock(return_value={"answer": "ok", "references": []})

    # Make sure upsert_qa_exchange is absent on the service module.
    from app.services import chroma_service
    had_attr = hasattr(chroma_service, "upsert_qa_exchange")
    if had_attr:
        saved = chroma_service.upsert_qa_exchange
        delattr(chroma_service, "upsert_qa_exchange")
    try:
        with patch(
            "app.agents.qa_history_agent.run_qa_history_chat_agent",
            agent_mock,
        ):
            response = client.post(
                "/api/v1/qa-history/chat",
                json={"question": "whatever"},
            )
    finally:
        if had_attr:
            chroma_service.upsert_qa_exchange = saved

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"


def test_post_qa_history_chat_survives_upsert_exception(client):
    """A raising upsert must not break the API response."""
    agent_mock = AsyncMock(return_value={"answer": "ok", "references": []})

    def _boom(*_a, **_kw):
        raise RuntimeError("chroma offline")

    with patch(
        "app.agents.qa_history_agent.run_qa_history_chat_agent",
        agent_mock,
    ), patch(
        "app.routers.qa_history.chroma_service.upsert_qa_exchange",
        create=True,
        side_effect=_boom,
    ):
        response = client.post(
            "/api/v1/qa-history/chat",
            json={"question": "whatever"},
        )

    assert response.status_code == 200


def test_get_qa_history_exchanges_initially_empty(client):
    response = client.get("/api/v1/qa-history/exchanges")
    assert response.status_code == 200
    assert response.json() == []


def test_get_qa_history_exchanges_returns_persisted_exchange(client):
    fake_refs = [
        {
            "source_type": "library",
            "exchange_id": "ex-99",
            "question_preview": "What is DNS?",
            "job_id": None,
            "original_created_at": "2026-03-15T12:00:00+00:00",
        }
    ]
    agent_mock = AsyncMock(return_value={"answer": "An answer.", "references": fake_refs})

    with patch(
        "app.agents.qa_history_agent.run_qa_history_chat_agent",
        agent_mock,
    ), patch(
        "app.routers.qa_history.chroma_service.upsert_qa_exchange",
        create=True,
    ):
        post_resp = client.post(
            "/api/v1/qa-history/chat",
            json={"question": "summarize my DNS questions"},
        )
    assert post_resp.status_code == 200

    get_resp = client.get("/api/v1/qa-history/exchanges")
    assert get_resp.status_code == 200
    items = get_resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["question"] == "summarize my DNS questions"
    assert item["answer"] == "An answer."
    assert item["answer_language"] == "en"
    assert item["created_at"] is not None
    assert len(item["references"]) == 1
    assert item["references"][0]["exchange_id"] == "ex-99"


def test_qa_history_endpoints_require_auth(unauthenticated_client):
    chat_resp = unauthenticated_client.post(
        "/api/v1/qa-history/chat", json={"question": "hi there"}
    )
    assert chat_resp.status_code == 401

    list_resp = unauthenticated_client.get("/api/v1/qa-history/exchanges")
    assert list_resp.status_code == 401

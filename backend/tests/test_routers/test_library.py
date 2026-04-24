"""Tests for the library-wide Q&A router (Unit 6).

Endpoints:
  GET  /api/v1/library/qa           list persisted exchanges
  POST /api/v1/library/qa           ask a question (library-scoped)
  POST /api/v1/library/qa/clarify   generate clarifying questions
"""
from unittest.mock import patch

import pytest

pytest.importorskip("app.routers.library", reason="pending Unit 6 merge — library router")


def test_get_library_qa_initially_empty(client):
    response = client.get("/api/v1/library/qa")
    assert response.status_code == 200
    assert response.json() == []


def test_post_library_qa_persists_and_returns_result(client):
    """POST runs the library Q&A agent (mocked), persists the exchange,
    returns the answer + references."""
    fake_answer = "DNS resolves domain names to IP addresses."
    fake_refs = [{
        "video_id": "vDNS",
        "video_url": "https://www.youtube.com/watch?v=vDNS",
        "video_title": "How DNS Works",
        "channel_name": "NetTeach",
        "timestamp_seconds": 30.0,
        "timestamp_display": "0:30",
        "youtube_link": "https://www.youtube.com/watch?v=vDNS&t=30",
    }]

    with patch(
        "app.agents.qa_agent.run_library_qa_agent",
        return_value={"answer": fake_answer, "references": fake_refs},
    ):
        response = client.post("/api/v1/library/qa", json={"question": "What is DNS?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == fake_answer
    assert "id" in data
    assert len(data["references"]) == 1
    assert data["references"][0]["video_title"] == "How DNS Works"


def test_get_library_qa_returns_persisted_exchange(client):
    fake_answer = "Answer."
    fake_refs = []
    with patch(
        "app.agents.qa_agent.run_library_qa_agent",
        return_value={"answer": fake_answer, "references": fake_refs},
    ):
        post_resp = client.post("/api/v1/library/qa", json={"question": "What is DNS?"})
    assert post_resp.status_code == 200

    get_resp = client.get("/api/v1/library/qa")
    assert get_resp.status_code == 200
    items = get_resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["question"] == "What is DNS?"
    assert item["answer"] == "Answer."
    assert item["created_at"] is not None


def test_post_library_qa_clarify_returns_interpretation_and_clarifications(client):
    """clarify endpoint mocks get_llm_for to return the JSON envelope the real route parses."""
    json_payload = (
        '{"interpretation": "User wants a DNS primer.", '
        '"clarifications": ["What level?", "Which record types?", "For DevOps?"]}'
    )

    class _Resp:
        content = json_payload

    class _LLM:
        def invoke(self, _prompt):
            return _Resp()

    with patch("app.routers.library.get_llm_for", return_value=_LLM()):
        response = client.post(
            "/api/v1/library/qa/clarify",
            json={"question": "What is DNS?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["interpretation"] == "User wants a DNS primer."
    assert len(data["clarifications"]) == 3
    assert "What level?" in data["clarifications"]

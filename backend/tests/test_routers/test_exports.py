"""Tests for the fine-tune dataset export router (Unit 6).

Endpoints under test:
  GET /api/v1/exports/qa-dataset/openai.jsonl
  GET /api/v1/exports/qa-dataset/tuple.jsonl
  GET /api/v1/exports/knowledge-dataset/openai.jsonl
  GET /api/v1/exports/knowledge-dataset/tuple.jsonl

Each test asserts that:
  - status == 200 and media_type is application/x-ndjson
  - Every non-empty line parses with ``json.loads``
  - Payloads carry the verbatim system prompts from the spec
  - The shape matches the format (messages[] for OpenAI, {system,user,assistant} for tuple)
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.services.dataset_service import (
    KNOWLEDGE_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(db):
    """Minimum-viable Job row to satisfy QAExchange.job_id FK."""
    from app.models.job import Job

    job = Job(job_type="topic", topic="test", status="completed", num_videos=1)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_qa_rows(db):
    """Seed two job-scoped and one library-scoped exchange with distinct timestamps
    so the ORDER BY ordering is observable in the streamed output."""
    job = _make_job(db)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    db.add_all([
        QAExchange(
            job_id=job.id,
            question="job question 1",
            answer="job answer 1",
            references="[]",
            created_at=base,
        ),
        QAExchange(
            job_id=job.id,
            question="job question 2",
            answer="job answer 2",
            references="[]",
            created_at=base + timedelta(minutes=2),
        ),
        LibraryQAExchange(
            question="library question 1",
            answer="library answer 1",
            references_json="[]",
            created_at=base + timedelta(minutes=1),
        ),
    ])
    db.commit()


def _parse_jsonl(body: str) -> list[dict]:
    """Parse a JSONL body into a list of dicts. Blank trailing lines are ignored.
    Raises json.JSONDecodeError if any non-empty line is invalid JSON."""
    return [json.loads(line) for line in body.split("\n") if line.strip()]


# ---------------------------------------------------------------------------
# Q&A dataset — OpenAI chat format
# ---------------------------------------------------------------------------


def test_qa_openai_returns_valid_jsonl_with_messages_envelope(client, db):
    _seed_qa_rows(db)

    response = client.get("/api/v1/exports/qa-dataset/openai.jsonl")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert 'filename="qa-dataset-openai.jsonl"' in response.headers.get("content-disposition", "")

    records = _parse_jsonl(response.text)
    assert len(records) == 3
    for rec in records:
        assert list(rec.keys()) == ["messages"]
        msgs = rec["messages"]
        assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
        assert msgs[0]["content"] == QA_SYSTEM_PROMPT


def test_qa_openai_is_ordered_by_created_at_ascending(client, db):
    _seed_qa_rows(db)

    response = client.get("/api/v1/exports/qa-dataset/openai.jsonl")
    records = _parse_jsonl(response.text)
    user_contents = [r["messages"][1]["content"] for r in records]

    # Seed order by created_at: job 1 (t=0), library 1 (t=+1), job 2 (t=+2).
    assert user_contents == ["job question 1", "library question 1", "job question 2"]


# ---------------------------------------------------------------------------
# Q&A dataset — tuple format
# ---------------------------------------------------------------------------


def test_qa_tuple_returns_valid_jsonl_with_flat_keys(client, db):
    _seed_qa_rows(db)

    response = client.get("/api/v1/exports/qa-dataset/tuple.jsonl")

    assert response.status_code == 200
    records = _parse_jsonl(response.text)
    assert len(records) == 3
    for rec in records:
        assert set(rec.keys()) == {"system", "user", "assistant"}
        assert rec["system"] == QA_SYSTEM_PROMPT


def test_qa_endpoints_empty_when_no_rows(client, db):
    response = client.get("/api/v1/exports/qa-dataset/openai.jsonl")
    assert response.status_code == 200
    # No rows → empty body, but it must still parse as valid (empty) JSONL.
    assert _parse_jsonl(response.text) == []


# ---------------------------------------------------------------------------
# Knowledge dataset
# ---------------------------------------------------------------------------


def test_knowledge_openai_empty_when_no_reports(client, db):
    response = client.get("/api/v1/exports/knowledge-dataset/openai.jsonl")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert _parse_jsonl(response.text) == []


def test_knowledge_tuple_empty_when_no_reports(client, db):
    response = client.get("/api/v1/exports/knowledge-dataset/tuple.jsonl")
    assert response.status_code == 200
    assert _parse_jsonl(response.text) == []


def test_knowledge_openai_serializes_report(client, db, monkeypatch):
    """Verify the OpenAI chat format for knowledge rows."""
    from app.services import dataset_service

    def fake_iter(_db):
        yield (
            ["AI safety", "alignment"],
            ["RLHF", "constitutional AI"],
            ["OpenAI announcement"],
            "# Report\n\nBody text.",
        )

    monkeypatch.setattr(dataset_service, "iter_knowledge_rows", fake_iter)

    response = client.get("/api/v1/exports/knowledge-dataset/openai.jsonl")
    records = _parse_jsonl(response.text)
    assert len(records) == 1
    msgs = records[0]["messages"]
    assert msgs[0]["content"] == KNOWLEDGE_SYSTEM_PROMPT
    assert "AI safety, alignment" in msgs[1]["content"]
    assert "RLHF, constitutional AI" in msgs[1]["content"]
    assert "OpenAI announcement" in msgs[1]["content"]
    assert msgs[2]["content"] == "# Report\n\nBody text."


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_exports_require_auth(unauthenticated_client):
    # All four paths — fan out so a regression on any single endpoint is caught.
    for path in [
        "/api/v1/exports/qa-dataset/openai.jsonl",
        "/api/v1/exports/qa-dataset/tuple.jsonl",
        "/api/v1/exports/knowledge-dataset/openai.jsonl",
        "/api/v1/exports/knowledge-dataset/tuple.jsonl",
    ]:
        resp = unauthenticated_client.get(path)
        assert resp.status_code == 401, f"expected 401 on {path}, got {resp.status_code}"


def test_exports_accept_query_token_fallback(unauthenticated_client, auth_token, db):
    # Browser downloads can't set Authorization — same pattern as the report route.
    _seed_qa_rows(db)
    response = unauthenticated_client.get(
        f"/api/v1/exports/qa-dataset/openai.jsonl?token={auth_token}"
    )
    assert response.status_code == 200
    assert len(_parse_jsonl(response.text)) == 3

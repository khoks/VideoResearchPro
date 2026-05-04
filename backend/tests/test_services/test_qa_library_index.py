"""Tests for the Q&A library Chroma collection (Unit 1).

Covers:
* ``upsert_qa_exchange`` writes one doc per exchange with the expected
  ID, text shape, and metadata.
* The post-commit hook in ``routers/qa.py`` fires on a job Q&A request.
* The post-commit hook in ``routers/library.py`` fires on a library Q&A request.
* ``backfill_qa_library`` is idempotent — repeat calls produce the same
  collection state (no duplicate rows, same IDs).
* Chroma failures in the hook must NOT break the Q&A response.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import chroma_service


@pytest.fixture(autouse=True)
def use_ephemeral_chroma(monkeypatch):
    """Use in-memory ChromaDB for tests."""
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


class _FakeExchange:
    """Minimal stand-in for QAExchange / LibraryQAExchange."""

    def __init__(
        self,
        question: str = "What is the mitochondrion?",
        answer: str = "The powerhouse of the cell.",
        *,
        job_id: str | None = None,
        references: str | None = None,
        references_json: str | None = None,
        answer_language: str | None = None,
        exchange_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = exchange_id or str(uuid.uuid4())
        self.question = question
        self.answer = answer
        self.job_id = job_id
        if references is not None:
            self.references = references
        if references_json is not None:
            self.references_json = references_json
        if answer_language is not None:
            self.answer_language = answer_language
        self.created_at = created_at or datetime.now(timezone.utc)


# --- upsert_qa_exchange ----------------------------------------------------

def test_upsert_qa_exchange_writes_document_with_expected_shape():
    ex = _FakeExchange(
        question="Explain tariffs.",
        answer="A tariff is a tax on imports.",
        job_id="job-abc",
        references=json.dumps([{"video_id": "v1"}, {"video_id": "v2"}]),
    )

    assert chroma_service.upsert_qa_exchange(ex, source="job") is True

    collection = chroma_service.get_qa_collection()
    data = collection.get(ids=[f"qa:{ex.id}"], include=["documents", "metadatas"])

    assert data["ids"] == [f"qa:{ex.id}"]
    assert data["documents"][0] == f"Q: {ex.question}\n\nA: {ex.answer}"

    meta = data["metadatas"][0]
    assert meta["source"] == "job"
    assert meta["exchange_id"] == ex.id
    assert meta["job_id"] == "job-abc"
    assert meta["reference_count"] == 2
    assert "created_at_iso" in meta


def test_upsert_qa_exchange_library_source_includes_answer_language():
    ex = _FakeExchange(
        question="Resumen en espanol?",
        answer="Respuesta corta.",
        references_json=json.dumps([]),
        answer_language="es",
    )

    assert chroma_service.upsert_qa_exchange(ex, source="library") is True

    collection = chroma_service.get_qa_collection()
    data = collection.get(ids=[f"qa:{ex.id}"], include=["metadatas"])
    meta = data["metadatas"][0]

    assert meta["source"] == "library"
    assert meta["answer_language"] == "es"
    assert meta["reference_count"] == 0
    assert "job_id" not in meta  # library exchanges have no job_id


def test_upsert_is_idempotent_on_fixed_id():
    ex = _FakeExchange()
    chroma_service.upsert_qa_exchange(ex, source="job")
    chroma_service.upsert_qa_exchange(ex, source="job")
    chroma_service.upsert_qa_exchange(ex, source="job")

    collection = chroma_service.get_qa_collection()
    data = collection.get(ids=[f"qa:{ex.id}"], include=[])
    assert data["ids"] == [f"qa:{ex.id}"]


def test_upsert_returns_false_on_chroma_error(monkeypatch):
    ex = _FakeExchange()

    def _boom():
        raise RuntimeError("chroma down")

    monkeypatch.setattr(chroma_service, "get_qa_collection", _boom)

    # Must not raise — hook site depends on this.
    assert chroma_service.upsert_qa_exchange(ex, source="job") is False


def test_upsert_tolerates_malformed_references():
    ex = _FakeExchange(references="not-json-at-all")
    assert chroma_service.upsert_qa_exchange(ex, source="job") is True

    collection = chroma_service.get_qa_collection()
    meta = collection.get(ids=[f"qa:{ex.id}"], include=["metadatas"])["metadatas"][0]
    assert meta["reference_count"] == 0


# --- query_qa_collection --------------------------------------------------

def test_query_qa_collection_returns_relevant_document():
    ex_a = _FakeExchange(
        question="What are tariffs?",
        answer="Taxes on imported goods.",
    )
    ex_b = _FakeExchange(
        question="What is chlorophyll?",
        answer="Green pigment in plants.",
    )
    chroma_service.upsert_qa_exchange(ex_a, source="job")
    chroma_service.upsert_qa_exchange(ex_b, source="library")

    results = chroma_service.query_qa_collection("tell me about tariffs", top_k=2)
    assert len(results) > 0
    # First result should mention tariffs
    assert "tariff" in results[0]["text"].lower()


def test_query_qa_collection_respects_where_filter():
    ex_job = _FakeExchange(question="Job q", answer="Job a")
    ex_lib = _FakeExchange(question="Lib q", answer="Lib a")
    chroma_service.upsert_qa_exchange(ex_job, source="job")
    chroma_service.upsert_qa_exchange(ex_lib, source="library")

    results = chroma_service.query_qa_collection(
        "anything at all",
        top_k=10,
        where={"source": "library"},
    )
    assert len(results) >= 1
    for r in results:
        assert r["metadata"]["source"] == "library"


# --- Hook firing via routers ----------------------------------------------

def _make_completed_topic_job(db, tenant_id: str | None = None):
    """Create a completed topic job so the Q&A endpoint accepts questions.

    `tenant_id` (E-5.1 phase 2b) — set to the test user's id so the
    job-id is reachable via the tenant-scoped router filter. Default
    ``None`` is for legacy-row simulation tests.
    """
    from app.models.job import Job

    job = Job(
        id=str(uuid.uuid4()),
        job_type="topic",
        status="completed",
        topic="tariffs",
        search_instructions="x",
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_job_qa_endpoint_upserts_exchange(client, db, test_user):
    """POST /jobs/{id}/qa must call upsert_qa_exchange with source='job'."""
    job = _make_completed_topic_job(db, tenant_id=test_user.id)

    with (
        patch("app.agents.qa_agent.run_qa_agent", return_value=("answer text", [])),
        patch(
            "app.services.chroma_service.upsert_qa_exchange",
            return_value=True,
        ) as mock_upsert,
    ):
        resp = client.post(
            f"/api/v1/jobs/{job.id}/qa",
            json={"question": "What are tariffs?"},
        )

    assert resp.status_code == 200, resp.text
    assert mock_upsert.call_count == 1
    _args, kwargs = mock_upsert.call_args
    assert kwargs.get("source") == "job"


def test_job_qa_endpoint_survives_chroma_failure(client, db, test_user):
    """A Chroma upsert exception must not break the Q&A response."""
    job = _make_completed_topic_job(db, tenant_id=test_user.id)

    with (
        patch("app.agents.qa_agent.run_qa_agent", return_value=("answer text", [])),
        patch(
            "app.services.chroma_service.upsert_qa_exchange",
            side_effect=RuntimeError("chroma down"),
        ),
    ):
        resp = client.post(
            f"/api/v1/jobs/{job.id}/qa",
            json={"question": "What are tariffs?"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] == "answer text"


def test_library_qa_endpoint_upserts_exchange(client):
    with (
        patch(
            "app.agents.qa_agent.run_library_qa_agent",
            return_value={"answer": "lib answer", "references": []},
        ),
        patch(
            "app.services.chroma_service.upsert_qa_exchange",
            return_value=True,
        ) as mock_upsert,
    ):
        resp = client.post(
            "/api/v1/library/qa",
            json={"question": "What is in my library?", "answer_language": "en"},
        )

    assert resp.status_code == 200, resp.text
    assert mock_upsert.call_count == 1
    _args, kwargs = mock_upsert.call_args
    assert kwargs.get("source") == "library"


def test_library_qa_endpoint_survives_chroma_failure(client):
    with (
        patch(
            "app.agents.qa_agent.run_library_qa_agent",
            return_value={"answer": "lib answer", "references": []},
        ),
        patch(
            "app.services.chroma_service.upsert_qa_exchange",
            side_effect=RuntimeError("chroma down"),
        ),
    ):
        resp = client.post(
            "/api/v1/library/qa",
            json={"question": "anything", "answer_language": "en"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] == "lib answer"


# --- Backfill --------------------------------------------------------------

def test_backfill_qa_library_is_idempotent(db, monkeypatch):
    """Seed both tables, run backfill twice, verify same IDs and no dupes."""
    from app.models.job import Job
    from app.models.library_qa_exchange import LibraryQAExchange
    from app.models.qa_exchange import QAExchange

    job = Job(
        id=str(uuid.uuid4()),
        job_type="topic",
        status="completed",
        topic="t",
    )
    db.add(job)
    db.commit()

    job_qa = QAExchange(
        job_id=job.id,
        question="Job Q",
        answer="Job A",
        references=json.dumps([{"v": 1}]),
    )
    lib_qa = LibraryQAExchange(
        question="Lib Q",
        answer="Lib A",
        references_json=json.dumps([]),
        answer_language="en",
    )
    db.add_all([job_qa, lib_qa])
    db.commit()
    db.refresh(job_qa)
    db.refresh(lib_qa)

    # backfill uses SessionLocal() — point it at the test session factory.
    def _session_factory():
        # Reuse the open test session; close() on it is a no-op to keep the
        # fixture-managed session alive for later assertions.
        class _Proxy:
            def query(self, *a, **kw):
                return db.query(*a, **kw)

            def close(self):
                pass

        return _Proxy()

    monkeypatch.setattr(
        "app.database.SessionLocal",
        _session_factory,
    )

    first = chroma_service.backfill_qa_library()
    second = chroma_service.backfill_qa_library()

    assert first == 2
    assert second == 2  # idempotent row count

    collection = chroma_service.get_qa_collection()
    all_rows = collection.get(include=["metadatas"])
    assert set(all_rows["ids"]) == {f"qa:{job_qa.id}", f"qa:{lib_qa.id}"}

    sources = {m["source"] for m in all_rows["metadatas"]}
    assert sources == {"job", "library"}


def test_backfill_on_empty_tables_returns_zero(monkeypatch, db):
    """No rows -> backfill is a no-op and returns 0."""
    def _session_factory():
        class _Proxy:
            def query(self, *a, **kw):
                return db.query(*a, **kw)

            def close(self):
                pass

        return _Proxy()

    monkeypatch.setattr("app.database.SessionLocal", _session_factory)
    assert chroma_service.backfill_qa_library() == 0

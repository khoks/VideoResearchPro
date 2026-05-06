"""Tests for T-5.6.6 — per-tenant Chroma isolation on qa_library_global.

The bug this closes: PR #152 (E-5.1 phase 2b) filtered SQL reads by
tenant_id, but the `qa_library_global` ChromaDB collection — which the
Q&A History meta-chat queries via similarity search — was a global
shared collection with no tenant filter. Result: a meta-chat question
could surface other users' Q&A history in the retrieved context.

This module locks in the tenant-scoped contract:

- `upsert_qa_exchange` writes ``tenant_id`` into Chroma metadata,
  defaulting to ``exchange.tenant_id`` when not explicitly passed.
- `query_qa_collection` accepts ``tenant_id`` and filters retrieval to
  matching rows. Combined with caller `where` via ``$and``.
- `run_qa_history_chat_agent` REQUIRES ``tenant_id`` keyword-only and
  propagates it.
- The `/qa-history/chat` endpoint stamps the requester's user_id.
- Backfill now also covers QAHistoryExchange rows (previously missed).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import chroma_service


@pytest.fixture(autouse=True)
def use_ephemeral_chroma(monkeypatch):
    """Use in-memory ChromaDB so tests don't touch real persisted state."""
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


class _FakeExchange:
    def __init__(
        self,
        question: str,
        answer: str,
        *,
        tenant_id: str | None = None,
        job_id: str | None = None,
        exchange_id: str | None = None,
    ) -> None:
        self.id = exchange_id or str(uuid.uuid4())
        self.question = question
        self.answer = answer
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.created_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Upsert writes tenant_id metadata
# ---------------------------------------------------------------------------


def test_upsert_qa_exchange_writes_tenant_id_from_attribute():
    ex = _FakeExchange(
        question="What is foo?", answer="Foo is bar.", tenant_id="user-A"
    )
    assert chroma_service.upsert_qa_exchange(ex, source="job") is True

    coll = chroma_service.get_qa_collection()
    data = coll.get(ids=[f"qa:{ex.id}"], include=["metadatas"])
    meta = data["metadatas"][0]
    assert meta["tenant_id"] == "user-A"


def test_upsert_qa_exchange_explicit_tenant_id_overrides_attribute():
    """Explicit `tenant_id=` arg wins over `exchange.tenant_id`."""
    ex = _FakeExchange(
        question="x", answer="y", tenant_id="attr-tenant"
    )
    chroma_service.upsert_qa_exchange(ex, source="job", tenant_id="explicit-tenant")

    coll = chroma_service.get_qa_collection()
    meta = coll.get(ids=[f"qa:{ex.id}"], include=["metadatas"])["metadatas"][0]
    assert meta["tenant_id"] == "explicit-tenant"


def test_upsert_qa_exchange_no_tenant_id_warns_but_succeeds(caplog):
    """Legacy rows pre-E-5.1 phase 2a may have tenant_id IS NULL. Upsert
    still succeeds but the row gets no tenant metadata — making it
    invisible to tenant-scoped queries (fail-safe)."""
    ex = _FakeExchange(question="x", answer="y", tenant_id=None)
    with caplog.at_level("WARNING"):
        assert chroma_service.upsert_qa_exchange(ex, source="job") is True
    assert any("no tenant_id resolvable" in r.message for r in caplog.records)

    coll = chroma_service.get_qa_collection()
    meta = coll.get(ids=[f"qa:{ex.id}"], include=["metadatas"])["metadatas"][0]
    # tenant_id key must NOT be present so it doesn't match any user's filter.
    assert "tenant_id" not in meta


# ---------------------------------------------------------------------------
# Query filters by tenant_id
# ---------------------------------------------------------------------------


def test_query_qa_collection_returns_only_matching_tenants_rows():
    """Two users each upsert one Q&A. A query as user-A only sees
    user-A's row even though both rows share lexically-similar content."""
    ex_a = _FakeExchange(
        question="What are tariffs?",
        answer="Taxes on imports.",
        tenant_id="user-A",
    )
    ex_b = _FakeExchange(
        question="What are tariffs?",
        answer="A type of border tax.",
        tenant_id="user-B",
    )
    chroma_service.upsert_qa_exchange(ex_a, source="library")
    chroma_service.upsert_qa_exchange(ex_b, source="library")

    results_a = chroma_service.query_qa_collection(
        "tariffs", top_k=10, tenant_id="user-A"
    )
    results_b = chroma_service.query_qa_collection(
        "tariffs", top_k=10, tenant_id="user-B"
    )

    assert all(r["metadata"]["tenant_id"] == "user-A" for r in results_a)
    assert all(r["metadata"]["tenant_id"] == "user-B" for r in results_b)
    assert len(results_a) == 1
    assert len(results_b) == 1


def test_query_qa_collection_combines_tenant_with_caller_where():
    """When the caller supplies `where={...}` AND `tenant_id`, both
    filters apply (Chroma `$and` combinator)."""
    ex_job = _FakeExchange(
        question="Job q", answer="Job a", tenant_id="me", job_id="job-X"
    )
    ex_lib = _FakeExchange(
        question="Lib q", answer="Lib a", tenant_id="me"
    )
    ex_other = _FakeExchange(
        question="Other lib", answer="Other a", tenant_id="other"
    )
    chroma_service.upsert_qa_exchange(ex_job, source="job")
    chroma_service.upsert_qa_exchange(ex_lib, source="library")
    chroma_service.upsert_qa_exchange(ex_other, source="library")

    results = chroma_service.query_qa_collection(
        "anything",
        top_k=10,
        where={"source": "library"},
        tenant_id="me",
    )
    # Must NOT include `ex_other` (different tenant) or `ex_job` (different source).
    assert len(results) == 1
    meta = results[0]["metadata"]
    assert meta["source"] == "library"
    assert meta["tenant_id"] == "me"


def test_query_qa_collection_without_tenant_filter_still_returns_all():
    """The legacy `tenant_id=None` call (e.g. backfill / admin) is allowed
    and returns everything — that's the explicit escape hatch documented
    in the function's docstring."""
    ex_a = _FakeExchange(question="q1", answer="a1", tenant_id="u1")
    ex_b = _FakeExchange(question="q2", answer="a2", tenant_id="u2")
    chroma_service.upsert_qa_exchange(ex_a, source="job")
    chroma_service.upsert_qa_exchange(ex_b, source="job")

    results = chroma_service.query_qa_collection("anything", top_k=10)
    tenants = {r["metadata"]["tenant_id"] for r in results}
    assert tenants == {"u1", "u2"}


def test_query_qa_collection_excludes_legacy_no_tenant_rows():
    """A row upserted without a tenant_id (legacy / pre-migration) does
    NOT leak into any tenant-scoped query."""
    ex_legacy = _FakeExchange(question="legacy q", answer="legacy a", tenant_id=None)
    ex_user = _FakeExchange(question="legacy q", answer="user a", tenant_id="u1")
    chroma_service.upsert_qa_exchange(ex_legacy, source="library")
    chroma_service.upsert_qa_exchange(ex_user, source="library")

    results = chroma_service.query_qa_collection(
        "legacy q", top_k=10, tenant_id="u1"
    )
    assert len(results) == 1
    assert results[0]["metadata"]["tenant_id"] == "u1"


# ---------------------------------------------------------------------------
# Backfill propagates tenant_id (and includes QAHistoryExchange now)
# ---------------------------------------------------------------------------


def test_backfill_qa_library_propagates_tenant_id(db, monkeypatch):
    """Seed all three tables with tenant_id set, run backfill, verify
    each Chroma row carries the right tenant_id metadata."""
    from app.models.job import Job
    from app.models.library_qa_exchange import LibraryQAExchange
    from app.models.qa_exchange import QAExchange
    from app.models.qa_history_exchange import QAHistoryExchange

    job = Job(
        id=str(uuid.uuid4()),
        job_type="topic",
        status="completed",
        topic="t",
        tenant_id="tenant-A",
    )
    db.add(job)
    db.commit()

    job_qa = QAExchange(
        job_id=job.id,
        question="Job Q",
        answer="Job A",
        tenant_id="tenant-A",
    )
    lib_qa = LibraryQAExchange(
        question="Lib Q",
        answer="Lib A",
        tenant_id="tenant-A",
    )
    hist_qa = QAHistoryExchange(
        question="Hist Q",
        answer="Hist A",
        tenant_id="tenant-A",
    )
    db.add_all([job_qa, lib_qa, hist_qa])
    db.commit()
    db.refresh(job_qa)
    db.refresh(lib_qa)
    db.refresh(hist_qa)

    # Wire the chroma service's session factory at the test session.
    def _session_factory():
        class _Proxy:
            def query(self, *a, **kw):
                return db.query(*a, **kw)

            def close(self):
                pass

        return _Proxy()

    monkeypatch.setattr("app.database.SessionLocal", _session_factory)

    count = chroma_service.backfill_qa_library()
    assert count == 3  # all three tables now covered

    coll = chroma_service.get_qa_collection()
    all_rows = coll.get(include=["metadatas"])
    sources = {m["source"] for m in all_rows["metadatas"]}
    tenants = {m["tenant_id"] for m in all_rows["metadatas"]}
    assert sources == {"job", "library", "history"}
    assert tenants == {"tenant-A"}


# ---------------------------------------------------------------------------
# End-to-end: meta-chat does not return other users' Q&A
# ---------------------------------------------------------------------------


def test_qa_history_meta_chat_does_not_leak_other_users_qa(client, db, test_user):
    """The integration leak this whole task closes:
    user A asks the meta-chat, user B's similar Q&A is NOT in the result."""
    from app.models.library_qa_exchange import LibraryQAExchange

    # User B's library Q&A — on the SAME topic as A's question.
    other = LibraryQAExchange(
        question="What are tariffs?",
        answer="Other user's notes about tariffs.",
        tenant_id="someone-else",
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    # Upsert user B's row into Chroma (simulate steady state).
    chroma_service.upsert_qa_exchange(other, source="library")

    # Stub the LLM calls so the test doesn't hit real providers.
    with (
        patch(
            "app.agents.qa_history_agent._refine_context",
            return_value="(refined)",
        ),
        patch(
            "app.agents.qa_history_agent._formulate_answer",
            return_value="answer",
        ),
    ):
        r = client.post(
            "/api/v1/qa-history/chat",
            json={"question": "What are tariffs?", "answer_language": "en"},
        )
    assert r.status_code == 200
    refs = r.json().get("references") or []
    # No reference should belong to the other user's exchange.
    other_id = other.id
    for ref in refs:
        assert ref.get("exchange_id") != other_id, (
            "Cross-tenant leak: other user's exchange surfaced in meta-chat"
        )

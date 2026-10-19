"""S-8.2.1 — ``GET /api/v1/search`` at the router: auth, validation, the
`types` filter, two-tenant isolation through the endpoint, and the backend
label on ``/health``. Engine behaviour lives in
``test_services/test_search_service.py``.
"""
from __future__ import annotations

import pytest

from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.services import search_service as svc
from tests.conftest import engine

OTHER = "other-tenant-uuid"


@pytest.fixture
def fts_index(db):
    """Index on the test engine. The app lifespan indexes the scratch schema
    database, not the in-memory one the router reads through `get_db`."""
    assert svc.ensure_index(engine) == svc.BACKEND_FTS5
    yield
    svc.drop_index(engine)


def _seed(db, tenant_id: str, tag: str) -> None:
    doc = Document(
        document_id=f"doc-{tag}", video_id=f"vid{tag}"[:20], title=f"Interest rate cuts {tag}",
        url=f"https://youtu.be/vid{tag}",
    )
    db.add(doc)
    db.commit()
    db.add(DocumentVisibility(video_id=doc.video_id, tenant_id=tenant_id, source="job"))
    db.add(Job(id=f"job-{tag}", tenant_id=tenant_id, job_type="topic", status="completed",
               topic=f"Rate cuts research {tag}"))
    db.add(LibraryQAExchange(id=f"qa-{tag}", tenant_id=tenant_id, question=f"Rate cuts? {tag}", answer="a"))
    db.commit()


def test_search_requires_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/search", params={"q": "rate"}).status_code == 401


def test_search_validates_query_params(client):
    assert client.get("/api/v1/search").status_code == 422
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "rate", "limit": 0}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "rate", "limit": 99}).status_code == 422
    r = client.get("/api/v1/search", params={"q": "rate", "types": "jobs,bogus"})
    assert r.status_code == 400 and "bogus" in r.json()["detail"]


def test_search_returns_requested_groups_in_canonical_order(client, db, test_user, fts_index):
    _seed(db, test_user.id, "mine")
    r = client.get("/api/v1/search", params={"q": "rate cuts", "types": "qa,jobs", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] == "fts5"
    assert [g["type"] for g in data["groups"]] == ["jobs", "qa"]
    assert [i["id"] for i in data["groups"][0]["items"]] == ["job-mine"]
    assert data["groups"][0]["items"][0]["href"] == "/jobs/job-mine"
    assert [i["id"] for i in data["groups"][1]["items"]] == ["qa-mine"]


def test_search_never_returns_another_tenants_rows(client, db, test_user, fts_index):
    """Same words in both tenants' rows; the caller gets only their own, and
    the other tenant's identifiers appear nowhere in the body."""
    _seed(db, test_user.id, "mine")
    _seed(db, OTHER, "SECRET")
    r = client.get("/api/v1/search", params={"q": "rate cuts", "limit": 10})
    assert r.status_code == 200
    assert "SECRET" not in r.text
    found = {g["type"]: [i["id"] for i in g["items"]] for g in r.json()["groups"]}
    assert found["documents"] == ["doc-mine"]
    assert found["jobs"] == ["job-mine"]
    assert found["qa"] == ["qa-mine"]


def test_search_with_no_visible_documents_returns_empty_not_everything(client, db, fts_index):
    """The authenticated user ingested nothing; another tenant did."""
    _seed(db, OTHER, "theirs")
    r = client.get("/api/v1/search", params={"q": "rate cuts"})
    assert r.status_code == 200
    assert all(g["items"] == [] for g in r.json()["groups"])


def test_search_like_fallback_through_the_endpoint(client, db, test_user, monkeypatch):
    monkeypatch.setattr(svc, "_backend", svc.BACKEND_LIKE)
    _seed(db, test_user.id, "mine")
    r = client.get("/api/v1/search", params={"q": "rate cuts", "types": "documents"})
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] == "like"
    assert [i["id"] for i in data["groups"][0]["items"]] == ["doc-mine"]
    assert data["groups"][0]["items"][0]["score"] == 0.0


def test_health_reports_the_search_backend(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["search_backend"] in ("fts5", "like")

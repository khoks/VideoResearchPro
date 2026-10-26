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

The knowledge dataset's document set (S-5.10.5) is tested at the bottom: it
is the caller's visibility grants, driven through the real ingest routes.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.config import settings
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.transcript_cache import TranscriptCache
from app.services import auth_service, visibility_service
from app.services.dataset_service import (
    KNOWLEDGE_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
)
from app.sources.types import ExtractedText


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(db, tenant_id=None):
    """Minimum-viable Job row to satisfy QAExchange.job_id FK."""
    from app.models.job import Job

    job = Job(
        job_type="topic", topic="test", status="completed", num_videos=1,
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_qa_rows(db, tenant_id):
    """Seed two job-scoped and one library-scoped exchange with distinct timestamps
    so the ORDER BY ordering is observable in the streamed output.

    S-5.7.1: exports are tenant-scoped, so every seeded row must be stamped
    with the authenticated caller's tenant or the export correctly yields
    nothing."""
    job = _make_job(db, tenant_id)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    db.add_all([
        QAExchange(
            job_id=job.id,
            question="job question 1",
            answer="job answer 1",
            references="[]",
            created_at=base,
            tenant_id=tenant_id,
        ),
        QAExchange(
            job_id=job.id,
            question="job question 2",
            answer="job answer 2",
            references="[]",
            created_at=base + timedelta(minutes=2),
            tenant_id=tenant_id,
        ),
        LibraryQAExchange(
            question="library question 1",
            answer="library answer 1",
            references_json="[]",
            created_at=base + timedelta(minutes=1),
            tenant_id=tenant_id,
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


def test_qa_openai_returns_valid_jsonl_with_messages_envelope(client, db, test_user):
    _seed_qa_rows(db, test_user.id)

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


def test_qa_openai_is_ordered_by_created_at_ascending(client, db, test_user):
    _seed_qa_rows(db, test_user.id)

    response = client.get("/api/v1/exports/qa-dataset/openai.jsonl")
    records = _parse_jsonl(response.text)
    user_contents = [r["messages"][1]["content"] for r in records]

    # Seed order by created_at: job 1 (t=0), library 1 (t=+1), job 2 (t=+2).
    assert user_contents == ["job question 1", "library question 1", "job question 2"]


# ---------------------------------------------------------------------------
# Q&A dataset — tuple format
# ---------------------------------------------------------------------------


def test_qa_tuple_returns_valid_jsonl_with_flat_keys(client, db, test_user):
    _seed_qa_rows(db, test_user.id)

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

    def fake_iter(_db, _tenant_id):
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


def test_exports_reject_a_query_token(unauthenticated_client, auth_token, db, test_user):
    # T-8.8.1.5: the browser fetches exports with the Authorization header and
    # saves them from a blob: URL, so a JWT in the URL — a log and Referer leak —
    # no longer authenticates any of them, even a valid one.
    _seed_qa_rows(db, test_user.id)
    for path in [
        "/api/v1/exports/qa-dataset/openai.jsonl",
        "/api/v1/exports/qa-dataset/tuple.jsonl",
        "/api/v1/exports/knowledge-dataset/openai.jsonl",
        "/api/v1/exports/knowledge-dataset/tuple.jsonl",
    ]:
        resp = unauthenticated_client.get(path, params={"token": auth_token})
        assert resp.status_code == 401, f"a ?token= authenticated {path}"


def test_exports_stream_with_the_header_token(client, db, test_user):
    # The path the frontend now takes (services/apiFiles.ts): header, no URL token.
    _seed_qa_rows(db, test_user.id)
    response = client.get("/api/v1/exports/qa-dataset/openai.jsonl")
    assert response.status_code == 200
    assert len(_parse_jsonl(response.text)) == 3


# ---------------------------------------------------------------------------
# Knowledge dataset — which documents export (S-5.10.5)
# ---------------------------------------------------------------------------
#
# The export is the caller's visibility grants, keyed on document_id (D-063,
# D-070): the set the library lists and library Q&A retrieves from. Until
# S-5.10.5 it derived ownership from the caller's jobs joined on the legacy
# video_id, and each of the four tests below fails on that rule. They are
# also the first to stream real rows: the entity query raised on its first
# record (the legacy Query's automatic unique() refuses yield_per), which
# the stubbed and empty tests above could not see.

_KNOWLEDGE_PATHS = (
    "/api/v1/exports/knowledge-dataset/openai.jsonl",
    "/api/v1/exports/knowledge-dataset/tuple.jsonl",
)


class _FakeConnector:
    """Stands in for the paste / PDF connector: returns fixed text."""

    def __init__(self, extracted):
        self._extracted = extracted

    def fetch_text(self, candidate, **_kw):
        return self._extracted


def _extracted(text, source="trafilatura"):
    return ExtractedText(
        segments=[{"text": text, "start": 0.0, "duration": 0.0}],
        language="en",
        text_source=source,
        word_count=len(text.split()),
        extra={"extracted_title": text[:40]},
    )


def _paste(client, url, headers=None):
    """Ingest ``url`` through ``POST /library/paste-urls``; the grant is the
    route's own."""
    with (
        patch("app.routers.library._connector_for",
              return_value=_FakeConnector(_extracted(f"The page at {url}."))),
        patch("app.routers.library.chroma_service.insert_chunks"),
    ):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": [url]}, headers=headers)
    assert resp.status_code == 201, resp.text
    row = resp.json()["results"][0]
    assert row["status"] == "created", row
    return row["document_id"]


def _store_knowledge(db, document_id, marker):
    """A knowledge artifact as ``POST /videos/{id}/extract-knowledge`` stores it.

    Set directly for documents that route cannot extract yet: it reads the
    transcript from ``transcript_cache`` by ``video_id``, which only YouTube
    ingest writes, so a pasted page or a PDF gets a 422 there today. The
    YouTube test below goes through the route itself.
    """
    doc = db.get(Document, document_id)
    doc.extracted_knowledge_json = json.dumps(
        {"topics": [f"{marker} topic"], "concepts": [], "events": [], "facts": []}
    )
    doc.knowledge_report_md = f"# {marker}"
    doc.knowledge_extracted_at = datetime.now(timezone.utc)
    db.commit()


def _knowledge_exports(client, headers=None) -> list[str]:
    """Both knowledge formats' bodies, each checked to be valid JSONL."""
    bodies = []
    for path in _KNOWLEDGE_PATHS:
        resp = client.get(path, headers=headers)
        assert resp.status_code == 200, path
        _parse_jsonl(resp.text)
        bodies.append(resp.text)
    return bodies


@pytest.fixture
def user_b_headers(db):
    user_b = auth_service.create_user(db, email="b@example.com", password="testpass123")
    token, _ = auth_service.create_access_token(user_b.id)
    return {"Authorization": f"Bearer {token}"}


def test_knowledge_export_includes_a_pasted_youtube_url(client, db):
    """The case the spec names. A YouTube link pasted into the library is a
    paste-mode document: no job selected it and it has no ``video_id``, so
    the job-derived rule could never export it."""
    doc_id = _paste(client, "https://www.youtube.com/watch?v=pastedVid01")
    doc = db.get(Document, doc_id)
    assert doc.video_id is None
    assert db.query(JobVideo).filter(JobVideo.document_id == doc_id).count() == 0
    _store_knowledge(db, doc_id, "PASTED-YOUTUBE-MARKER")

    for body in _knowledge_exports(client):
        records = _parse_jsonl(body)
        assert len(records) == 1
        assert "PASTED-YOUTUBE-MARKER" in body


def test_knowledge_export_includes_an_uploaded_pdf(client, db, tmp_path, monkeypatch):
    """T-5.10.5.1: a PDF has no job and no ``video_id`` either."""
    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))
    with (
        patch("app.routers.library._connector_for",
              return_value=_FakeConnector(_extracted("A page of the paper.", source="pdf"))),
        patch("app.routers.library.chroma_service.insert_chunks"),
    ):
        resp = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": ("paper.pdf", b"%PDF-1.4 export test bytes", "application/pdf")},
        )
    assert resp.status_code == 201, resp.text
    _store_knowledge(db, resp.json()["document_id"], "PDF-MARKER")

    for body in _knowledge_exports(client):
        assert "PDF-MARKER" in body


def test_knowledge_export_includes_a_video_whose_job_was_deleted(client, db, test_user):
    """Deleting a job drops its links but keeps its documents in the
    caller's library (D-063), so their knowledge reports must keep
    exporting. The job-derived rule lost them with the job."""
    from app.tasks.job_tasks import _grant_job_document_visibility

    job = Job(tenant_id=test_user.id, job_type="topic", topic="t", status="completed")
    video = Document(
        video_id="jobVid00001",
        title="A video",
        url="https://www.youtube.com/watch?v=jobVid00001",
        transcript_status="fetched",
    )
    db.add_all([job, video])
    db.commit()
    db.add_all([
        JobVideo(job_id=job.id, document_id=video.document_id, video_id=video.video_id),
        TranscriptCache(
            document_id=video.document_id,
            video_id=video.video_id,
            segments_json=json.dumps([{"text": "Some speech.", "start": 0.0, "duration": 2.0}]),
            language="en",
        ),
    ])
    db.commit()
    _grant_job_document_visibility(db, job)  # what the job pipeline writes

    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value={"topics": ["speech"], "concepts": [], "events": [], "facts": [],
                      "knowledge_report_md": "# DELETED-JOB-MARKER"},
    ):
        resp = client.post(f"/api/v1/videos/{video.video_id}/extract-knowledge")
    assert resp.status_code == 200, resp.text

    with patch("app.routers.jobs.chroma_service.delete_collection"):
        assert client.delete(f"/api/v1/jobs/{job.id}").status_code == 204
    assert db.query(JobVideo).filter(JobVideo.document_id == video.document_id).count() == 0
    listed = {row["id"] for row in client.get("/api/v1/library/videos").json()}
    assert video.document_id in listed  # still in the caller's library

    for body in _knowledge_exports(client):
        assert "DELETED-JOB-MARKER" in body


def test_knowledge_export_excludes_documents_the_caller_cannot_see(
    client, db, test_user, user_b_headers
):
    """Absence is the direction that matters (S-5.7.1). Three documents with
    knowledge reports that are not visible to the caller, beside one that is,
    so an empty export cannot pass:

    - another tenant's pasted page, ingested through the same route;
    - a document in the shared cache that nobody was granted;
    - a document linked to the caller's own job whose grant was never
      written (the grant is best-effort). Ownership is never derived from
      job links (D-063): the library and Q&A hide such a document, so the
      export must too. The old rule exported it.
    """
    mine = _paste(client, "https://example.com/my-essay")
    _store_knowledge(db, mine, "MINE-MARKER")

    theirs = _paste(client, "https://example.com/their-essay", headers=user_b_headers)
    _store_knowledge(db, theirs, "OTHER-TENANT-MARKER")

    cached = Document(
        video_id="cachedVid01",
        title="Cached",
        url="https://www.youtube.com/watch?v=cachedVid01",
        transcript_status="fetched",
    )
    linked = Document(
        video_id="linkedVid01",
        title="Linked, not granted",
        url="https://www.youtube.com/watch?v=linkedVid01",
        transcript_status="fetched",
    )
    job = Job(tenant_id=test_user.id, job_type="topic", topic="t", status="completed")
    db.add_all([cached, linked, job])
    db.commit()
    db.add(JobVideo(job_id=job.id, document_id=linked.document_id, video_id=linked.video_id))
    db.commit()
    _store_knowledge(db, cached.document_id, "UNGRANTED-CACHE-MARKER")
    _store_knowledge(db, linked.document_id, "JOB-LINK-ONLY-MARKER")
    assert visibility_service.visible_document(db, test_user.id, linked.document_id) is None

    for body in _knowledge_exports(client):
        assert len(_parse_jsonl(body)) == 1
        assert "MINE-MARKER" in body
        for marker in ("OTHER-TENANT-MARKER", "UNGRANTED-CACHE-MARKER", "JOB-LINK-ONLY-MARKER"):
            assert marker not in body, marker

    # And the other tenant gets exactly their own page.
    for body in _knowledge_exports(client, headers=user_b_headers):
        assert len(_parse_jsonl(body)) == 1
        assert "OTHER-TENANT-MARKER" in body
        assert "MINE-MARKER" not in body

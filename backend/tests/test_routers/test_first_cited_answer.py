"""T-8.10.1.6 — the ``first_cited_answer`` activation event (M10's
alternative milestone).

Written once per account, by the job Q&A router (``/qa`` and ``/qa/stream``
share ``_run_qa_and_persist``) and the library Q&A router (library and shelf
questions share ``answer_library_question``), the first time a stored answer
cites at least one source. An answer that cites nothing, or only the
reader's own notes, does not count. Driven through the routes, not the
service, so the test fails if either router stops calling it.
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.job import Job
from app.services import auth_service, visibility_service

EVENT = "first_cited_answer"


def _events(db, user_id):
    return db.query(AuditLog).filter(AuditLog.user_id == user_id, AuditLog.event == EVENT).all()


def _ref(vid="citedvid0001"):
    return {
        "video_id": vid, "video_url": f"https://www.youtube.com/watch?v={vid}", "video_title": "A source",
        "channel_name": "c", "timestamp_seconds": 1, "timestamp_display": "0:01",
        "youtube_link": f"https://www.youtube.com/watch?v={vid}&t=1",
    }


NOTE_REF = {
    "source_type": "note", "note_id": "n1", "note_target_type": "document", "note_target_id": "d1",
    "note_created_at": "2026-10-19", "quote": "my note", "video_url": "", "video_title": "Your note",
    "channel_name": "you", "timestamp_seconds": 0.0, "timestamp_display": "", "youtube_link": "",
}


@pytest.fixture
def job(db, test_user):
    j = Job(job_type="topic", topic="cited", status="completed", num_videos=1, tenant_id=test_user.id)
    db.add(j)
    db.commit()
    return j


@pytest.fixture
def library_doc(db, test_user):
    d = Document(
        video_id="citedvid0001", title="A source", url="https://www.youtube.com/watch?v=citedvid0001",
        duration_seconds=60, transcript_status="fetched", created_at=datetime.now(timezone.utc),
    )
    db.add(d)
    db.commit()
    visibility_service.grant(db, [d.document_id], test_user.id)
    return d


def _ask_job(client, job, refs, headers=None):
    with (
        patch("app.agents.qa_agent.run_qa_agent", return_value=("Answer.", refs)),
        patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ask_library(client, refs, path="/api/v1/library/qa"):
    with (
        patch("app.agents.qa_agent.run_library_qa_agent", return_value={"answer": "Answer.", "references": refs}),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(path, json={"question": "tell me"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_job_qa_writes_it_once_on_the_first_cited_answer(client, db, test_user, job):
    _ask_job(client, job, [])
    _ask_job(client, job, [NOTE_REF])
    assert _events(db, test_user.id) == [], "no citation, or only the reader's own note, is not a cited answer"

    first = _ask_job(client, job, [_ref(), _ref("citedvid0002"), NOTE_REF])
    _ask_job(client, job, [_ref()])
    (row,) = _events(db, test_user.id)
    meta = json.loads(row.metadata_json)
    assert meta == {"surface": "job", "exchange_id": first["id"], "citations": 2, "job_id": job.id}


def test_the_streaming_job_route_writes_it_too(client, db, test_user, job):
    with (
        patch("app.agents.qa_agent.run_qa_agent", return_value=("Answer.", [_ref()])),
        patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(f"/api/v1/jobs/{job.id}/qa/stream", json={"question": "tell me"})
    assert resp.status_code == 200
    assert '"type": "complete"' in resp.text
    (row,) = _events(db, test_user.id)
    assert json.loads(row.metadata_json)["surface"] == "job"


def test_library_qa_writes_it_once_on_the_first_cited_answer(client, db, test_user, library_doc):
    _ask_library(client, [])
    assert _events(db, test_user.id) == []
    first = _ask_library(client, [_ref()])
    _ask_library(client, [_ref()])
    (row,) = _events(db, test_user.id)
    assert json.loads(row.metadata_json) == {"surface": "library", "exchange_id": first["id"], "citations": 1}


def test_once_per_account_across_surfaces(client, db, test_user, job, library_doc):
    _ask_library(client, [_ref()])
    _ask_job(client, job, [_ref()])
    (row,) = _events(db, test_user.id)
    assert json.loads(row.metadata_json)["surface"] == "library"


def test_a_shelf_question_counts_as_library_qa(client, db, test_user, library_doc):
    from app.models.job_video import JobVideo
    from app.services import shelf_service

    run = Job(job_type="topic", topic="t", status="completed", num_videos=1, tenant_id=test_user.id)
    db.add(run)
    db.commit()
    db.add(JobVideo(job_id=run.id, video_id=library_doc.video_id, approved=True))
    db.commit()
    shelf = shelf_service.create_shelf(db, test_user.id, "Rates")
    shelf_service.add_job(db, shelf, run)
    _ask_library(client, [_ref()], path=f"/api/v1/shelves/{shelf.id}/qa")
    (row,) = _events(db, test_user.id)
    assert json.loads(row.metadata_json)["surface"] == "library"


def test_each_account_gets_its_own(client, db, test_user, job, library_doc):
    other = auth_service.create_user(db, email="cited-other@example.com", password="otherpass123")
    token, _ = auth_service.create_access_token(other.id)
    their_job = Job(job_type="topic", topic="theirs", status="completed", num_videos=1, tenant_id=other.id)
    db.add(their_job)
    db.commit()

    _ask_job(client, job, [_ref()])
    _ask_job(client, their_job, [_ref()], headers={"Authorization": f"Bearer {token}"})
    assert len(_events(db, test_user.id)) == 1
    assert len(_events(db, other.id)) == 1


def test_a_failed_audit_write_never_fails_the_answer(client, db, test_user, job):
    with patch("app.services.onboarding_service.audit_service.record", side_effect=RuntimeError("db hiccup")):
        _ask_job(client, job, [_ref()])
    assert _events(db, test_user.id) == []

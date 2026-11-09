"""T-5.2.17: a run the broker refused holds no place under the job limit.

``POST /jobs`` wrote its row ``pending`` and then dispatched. A dispatch that
raised came back as a bare 500 and left the row ``pending``, which
``refuse_if_at_limit`` reads as active, so enough broker outages and a user
could never start another job. The row is failed now, in words the job page
shows, and the answer is a 503 the form can show. ``_dispatch_subscription_sync``
does the same since #424 (T-5.2.15).

Approval resumes a run the user is looking at. Its row was ``awaiting_approval``
before and stays so, picks kept, so Approve works again once the queue is back
and Cancel frees the place; failing it would throw the candidates away. It
answers 503 in words instead of a 500, and grants the approved documents only
once the resume is queued, so a refused approval holds no place under the
document cap.

Mutation checks: remove the ``except`` around ``dispatch_for_user`` in
``create_job`` and ``test_a_run_the_broker_refused_is_failed_and_holds_no_place``
fails on a 500 and a pending row; remove the one around the resume's dispatch
and ``test_an_approval_the_broker_refused_can_be_approved_again`` fails on a 500.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import document_cap_service

BODIES = {
    "topic": {"job_type": "topic", "topic": "tariffs"},
    "channel": {"job_type": "channel", "channel_list": ["UCrefused0001"]},
    "subscription": {"job_type": "subscription", "channel_list": ["UCrefused0001"]},
}
TASKS = {"topic": "execute_topic_job", "channel": "execute_channel_job", "subscription": "execute_subscription_job"}
# What a broker's error can hold: the broker URL, with its password.
BROKER_DOWN = OSError("Error 10061 connecting to redis://:hunter2-secret@localhost:6379/1")


def _hold(db, tenant_id: str, count: int) -> None:
    db.add_all([Job(job_type="topic", topic="held", status="extracting", tenant_id=tenant_id) for _ in range(count)])
    db.commit()


@pytest.mark.parametrize("job_type", sorted(BODIES))
def test_a_run_the_broker_refused_is_failed_and_holds_no_place(client, db, test_user, job_type):
    _hold(db, test_user.id, settings.MAX_CONCURRENT_JOBS - 1)
    with patch(f"app.routers.jobs.{TASKS[job_type]}") as task:
        task.apply_async.side_effect = BROKER_DOWN
        response = client.post("/api/v1/jobs", json=BODIES[job_type])

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Could not queue the run; the task queue is unavailable. Try again in a few minutes."
    )
    assert "hunter2" not in response.text
    db.expire_all()
    refused = db.query(Job).filter(Job.status != "extracting").one()
    assert refused.status == "failed"
    assert refused.error_message == "The run could not be queued, so it never started. Submit it again in a few minutes."
    assert refused.celery_task_id is None

    # The last place is still free.
    again = client.post("/api/v1/jobs", json=BODIES[job_type])
    assert again.status_code == 201, again.text


def test_the_refused_run_reads_as_failed_on_its_page(client, db):
    with patch("app.routers.jobs.execute_topic_job") as task:
        task.apply_async.side_effect = BROKER_DOWN
        client.post("/api/v1/jobs", json=BODIES["topic"])
    job_id = db.query(Job).one().id

    page = client.get(f"/api/v1/jobs/{job_id}").json()
    assert page["status"] == "failed"
    assert page["error_message"].startswith("The run could not be queued")


def test_a_queued_run_is_unchanged(client, db):
    response = client.post("/api/v1/jobs", json=BODIES["topic"])
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    db.expire_all()
    assert db.query(Job).one().celery_task_id == "mock-topic-task-id"


def _awaiting(db, tenant_id: str) -> tuple[Job, Document]:
    job = Job(job_type="topic", topic="tariffs", status="awaiting_approval", num_videos=1, tenant_id=tenant_id)
    doc = Document(video_id="vRefused001", title="A video", url="https://www.youtube.com/watch?v=vRefused001")
    db.add_all([job, doc])
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=False))
    db.commit()
    return job, doc


def test_an_approval_the_broker_refused_can_be_approved_again(client, db, test_user):
    job, doc = _awaiting(db, test_user.id)
    body = {"approved_video_ids": [doc.video_id]}
    with patch("app.routers.jobs.resume_job_after_approval") as task:
        task.apply_async.side_effect = BROKER_DOWN
        refused = client.put(f"/api/v1/jobs/{job.id}/approve", json=body)

    assert refused.status_code == 503
    assert refused.json()["detail"] == (
        "Could not queue the run; the task queue is unavailable. Approve it again in a few minutes."
    )
    assert "hunter2" not in refused.text
    db.expire_all()
    assert db.get(Job, job.id).status == "awaiting_approval"
    assert db.get(JobVideo, (job.id, doc.document_id)).approved is True, "the picks are kept"
    assert document_cap_service.visible_count(db, test_user.id) == 0, "nothing granted for a run that never started"

    with patch("app.routers.jobs.resume_job_after_approval") as task:
        task.apply_async.return_value = MagicMock(id="resume-task")
        approved = client.put(f"/api/v1/jobs/{job.id}/approve", json=body)
    assert approved.status_code == 200
    assert approved.json()["status"] == "extracting"
    # The approval that was queued grants at once (T-5.2.10), as before.
    assert document_cap_service.visible_count(db, test_user.id) == 1


def test_a_refused_approval_can_be_cancelled_to_free_its_place(client, db, test_user):
    """Cancel frees the job-limit place, and the refused approval held no
    place under the document cap (D-115) either: its documents were never
    read, so they were never granted.

    Mutation check: move ``visibility_service.grant`` in ``approve_job`` back
    above the dispatch and the cap count is 1 after the cancel."""
    job, doc = _awaiting(db, test_user.id)
    before = document_cap_service.visible_count(db, test_user.id)
    with patch("app.routers.jobs.resume_job_after_approval") as task:
        task.apply_async.side_effect = BROKER_DOWN
        refused = client.put(f"/api/v1/jobs/{job.id}/approve", json={"approved_video_ids": [doc.video_id]})
    assert refused.status_code == 503

    assert client.post(f"/api/v1/jobs/{job.id}/cancel").status_code == 200
    db.expire_all()
    assert db.get(Job, job.id).status == "cancelled"
    assert document_cap_service.visible_count(db, test_user.id) == before
    assert db.query(DocumentVisibility).filter(DocumentVisibility.document_id == doc.document_id).count() == 0

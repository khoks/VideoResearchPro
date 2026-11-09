"""T-5.2.18: a run already failed stays failed when its task is delivered anyway.

A dispatch can raise after the broker took the message: the publish went out
and the reply was lost. ``POST /jobs`` and ``_dispatch_subscription_sync`` then
fail the row and tell the user it never started (T-5.2.17, T-5.2.15), and the
worker still gets the message. The tasks did not look at the row before they
started, so the run came back to life from ``failed``, spent the owner's
quota and model calls, and published progress for a run its page called
failed.

Each entry point (the first run of a topic or channel job, the resume after an
approval, the subscription sync) now reads the row and returns before the
usage scope opens and before any write or publish.

Nothing runs a failed job again on purpose, so the guard blocks nothing that
should run: no route retries a run in place (a new run is a new row), the
scheduler queues no job tasks, the tasks never call ``self.retry``, and a
redelivery after a worker died mid-run (``task_acks_late``) finds the row in
the state that worker left, never failed. A cancelled row is not read by the
guard (unchanged).

Mutation check: ``test_mutation_without_the_guard_the_run_comes_back`` runs
every case with ``_already_failed`` answering False and sees the work start;
remove the call from any one entry point and that entry point's cases fail.
"""
from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.usage_record import UsageRecord
from app.tasks import job_tasks

# The real tasks, kept before any test patches the module's names.
REAL_TASKS = {
    "execute_topic_job": job_tasks.execute_topic_job,
    "execute_channel_job": job_tasks.execute_channel_job,
    "resume_job_after_approval": job_tasks.resume_job_after_approval,
    "execute_subscription_job": job_tasks.execute_subscription_job,
}
BODIES = {
    "topic": {"job_type": "topic", "topic": "tariffs"},
    "channel": {"job_type": "channel", "channel_list": ["UCdelivered001"]},
    "subscription": {"job_type": "subscription", "channel_list": ["UCdelivered001"]},
}
TASK_FOR = {"topic": "execute_topic_job", "channel": "execute_channel_job", "subscription": "execute_subscription_job"}
CHANNEL = "UCdelivered001"


class _WorkStarted(Exception):
    """Raised by anything a run reaches once it is past the guard."""


@pytest.fixture
def worker(monkeypatch, db):
    """The task module on the test session, with every way out of a run
    recorded: progress published, the usage scope, a connector, the search
    agent. Yields the recorders."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    progress = MagicMock()
    monkeypatch.setattr(job_tasks, "progress_service", progress)
    monkeypatch.setattr("app.services.progress_service.publish_error", progress.publish_error)
    metered = MagicMock(return_value=nullcontext())
    monkeypatch.setattr(job_tasks.usage_service, "metered", metered)
    connector_for = MagicMock(side_effect=_WorkStarted("a connector was asked"))
    monkeypatch.setattr(job_tasks, "connector_for", connector_for)
    search = MagicMock(side_effect=_WorkStarted("the search agent ran"))
    monkeypatch.setattr("app.agents.search_agent.run_search_agent", search)
    return MagicMock(progress=progress, metered=metered, connector_for=connector_for, search=search)


def _snapshot(db, job_id: str) -> dict:
    db.expire_all()
    job = db.get(Job, job_id)
    return {
        "status": job.status,
        "error_message": job.error_message,
        "progress_message": job.progress_message,
        "progress_pct": job.progress_pct,
        "celery_task_id": job.celery_task_id,
        "updated_at": job.updated_at,
    }


def _assert_did_nothing(db, worker, job_id: str, before: dict) -> None:
    assert _snapshot(db, job_id) == before, "the failed row was left exactly as the route wrote it"
    assert worker.progress.mock_calls == [], "a skipped task publishes nothing"
    worker.metered.assert_not_called()
    assert db.query(UsageRecord).count() == 0, "a skipped task charges nothing"
    worker.connector_for.assert_not_called()
    worker.search.assert_not_called()


# ---------------------------------------------------------------- the first run


@pytest.mark.parametrize("job_type", sorted(BODIES))
def test_a_run_failed_by_a_refused_dispatch_does_nothing_when_delivered(client, db, worker, job_type):
    """The broker took the message and the reply was lost: the route failed
    the row, and the worker runs the task anyway."""
    task_name = TASK_FOR[job_type]
    delivered: list[str] = []

    def publish_then_lose_the_reply(args=(), kwargs=None, queue=None):
        delivered.append(args[0])
        raise OSError("connection reset after publish")

    with patch(f"app.routers.jobs.{task_name}") as task:
        task.apply_async.side_effect = publish_then_lose_the_reply
        response = client.post("/api/v1/jobs", json=BODIES[job_type])
    assert response.status_code == 503
    (job_id,) = delivered
    before = _snapshot(db, job_id)
    assert before["status"] == "failed"

    REAL_TASKS[task_name].run(job_id)

    _assert_did_nothing(db, worker, job_id, before)


def test_a_sync_failed_by_a_refused_dispatch_does_nothing_when_delivered(client, db, worker):
    """``_dispatch_subscription_sync``, #424's edge: Sync now fails its row
    when the dispatch raises, and the message may still be on the queue."""
    db.add(Channel(channel_id=CHANNEL, name="Delivered Channel", uploads_playlist_id="UUdelivered001"))
    db.commit()
    delivered: list[str] = []

    def publish_then_lose_the_reply(args=(), kwargs=None, queue=None):
        delivered.append(args[0])
        raise OSError("connection reset after publish")

    with patch("app.tasks.job_tasks.execute_subscription_job") as task:
        task.apply_async.side_effect = publish_then_lose_the_reply
        response = client.post(f"/api/v1/channels/{CHANNEL}/sync")
    assert response.json()["job_id"] is None
    (job_id,) = delivered
    before = _snapshot(db, job_id)
    assert before["status"] == "failed"
    assert before["error_message"] == "The sync could not be queued."

    REAL_TASKS["execute_subscription_job"].run(job_id)

    _assert_did_nothing(db, worker, job_id, before)


# ---------------------------------------------------------------- the resume


def _failed_with_approved_document(db) -> tuple[str, str]:
    job = Job(job_type="topic", topic="tariffs", status="failed", tenant_id="tenant-failed",
              error_message="The run could not be queued, so it never started. Submit it again in a few minutes.")
    doc = Document(video_id="vDelivered01", source_type="video", source_id="vDelivered01",
                   title="A video", url="https://www.youtube.com/watch?v=vDelivered01")
    db.add_all([job, doc])
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
    db.commit()
    return job.id, doc.document_id


def test_a_resume_delivered_for_a_failed_run_does_nothing(db, worker):
    """No grant, no fetch, no status: the approved documents of a run that
    failed never join the library through it."""
    job_id, document_id = _failed_with_approved_document(db)
    before = _snapshot(db, job_id)

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    _assert_did_nothing(db, worker, job_id, before)
    assert db.query(DocumentVisibility).filter(DocumentVisibility.document_id == document_id).count() == 0
    assert db.get(Document, document_id).transcript_status != "fetched"


# ---------------------------------------------------------------- unchanged


def test_a_pending_run_still_runs(db, worker):
    """The guard reads failed only: a row in any other state is a run to do."""
    job = Job(job_type="topic", topic="tariffs", status="pending", tenant_id="tenant-pending")
    db.add(job)
    db.commit()

    REAL_TASKS["execute_topic_job"].run(job.id)

    assert worker.metered.called
    worker.search.assert_called_once()
    worker.progress.publish_status_change.assert_any_call(job.id, "pending", "searching", "Searching for relevant videos...")


def test_a_redelivered_run_a_dead_worker_left_mid_way_still_runs(db, worker):
    """``task_acks_late``: a worker that died mid-run leaves its row where it
    was, never failed, and the redelivered task picks the run up again."""
    job_id, _ = _failed_with_approved_document(db)
    db.get(Job, job_id).status = "extracting"
    db.commit()

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    assert worker.metered.called
    worker.connector_for.assert_called_once_with("video")


def test_a_missing_row_is_still_a_warning_and_nothing_more(db, worker):
    REAL_TASKS["execute_topic_job"].run("no-such-job")

    worker.metered.assert_not_called()
    assert worker.progress.mock_calls == []


# ---------------------------------------------------------------- mutation


@pytest.mark.parametrize("task_name", sorted(REAL_TASKS))
def test_mutation_without_the_guard_the_run_comes_back(db, worker, monkeypatch, task_name):
    """With ``_already_failed`` answering False, each entry point opens the
    usage scope, publishes and rewrites the failed row: the cases above would
    all fail."""
    monkeypatch.setattr(job_tasks, "_already_failed", lambda job, task: False)
    job_type = {"execute_channel_job": "channel", "execute_subscription_job": "subscription"}.get(task_name, "topic")
    job_id, _ = _failed_with_approved_document(db)
    job = db.get(Job, job_id)
    job.job_type = job_type
    job.channel_list = f'["{CHANNEL}"]'
    db.commit()
    before = _snapshot(db, job_id)

    REAL_TASKS[task_name].run(job_id)

    assert worker.metered.called
    assert worker.progress.mock_calls != []
    assert _snapshot(db, job_id) != before

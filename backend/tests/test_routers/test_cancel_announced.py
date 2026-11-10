"""T-5.2.30: a cancel reaches every open page of its run.

``POST /jobs/{id}/cancel`` wrote ``cancelled`` and revoked the task, and
published nothing, so another tab open on the run (or the jobs list) showed it
running until its next refetch. Once the route's conditional write has made
the row cancelled, it now publishes a ``job_status_change`` to ``cancelled``
on ``job_progress:{job_id}``, the event a run's own transitions send and
``useJobProgress`` applies. The write commits first, so no page reads
``cancelled`` before the row says it. A cancel that loses the race to the
run's end (the 400 since T-5.2.22) publishes nothing, and a publish that
fails (Redis down) is logged by the exception's type and never fails the
cancel: the row is the cancel.

Every case runs the real route against the test database, with a fake Redis
client in place of the publisher's (no Redis) and a patched revoke (no
broker). A mutation check sits beside each mechanism.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.models.job import Job
from app.routers import jobs as jobs_router
from app.services import job_service, progress_service
from app.tasks.celery_app import celery_app

CANCELLED_WORDS = "Job cancelled by user"
SECRET = "hunter2"


class _FakeRedis:
    """The publisher's Redis client. Each publish joins the database's
    statements and commits on one timeline; ``fail`` makes it refuse."""

    def __init__(self, timeline: list, fail: Exception | None = None):
        self.timeline = timeline
        self.fail = fail

    def publish(self, channel: str, data: str) -> int:
        if self.fail is not None:
            raise self.fail
        self.timeline.append(("PUBLISH", channel, json.loads(data)))
        return 0


@pytest.fixture
def timeline(db, monkeypatch):
    """Every write to ``jobs``, every COMMIT and every publish, in order."""
    seen: list = []
    engine = db.get_bind()

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE JOBS"):
            seen.append(("UPDATE jobs",))

    def on_commit(conn):
        seen.append(("COMMIT",))

    event.listen(engine, "before_cursor_execute", on_execute)
    event.listen(engine, "commit", on_commit)
    monkeypatch.setattr(progress_service, "_get_redis", lambda: _FakeRedis(seen))
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
        event.remove(engine, "commit", on_commit)


def _publishes(timeline: list) -> list:
    return [entry for entry in timeline if entry[0] == "PUBLISH"]


def _published_after_its_commit(timeline: list) -> bool:
    """Did the one publish follow the COMMIT of the write before it?"""
    at = timeline.index(_publishes(timeline)[0])
    writes = [i for i, entry in enumerate(timeline[:at]) if entry[0] == "UPDATE jobs"]
    if not writes:
        return False
    return any(entry[0] == "COMMIT" for entry in timeline[writes[-1]:at])


def _active_row(db, tenant_id: str, status: str = "generating_report") -> str:
    job = Job(job_type="topic", topic="tariffs", status=status, tenant_id=tenant_id,
              celery_task_id="resume-task-id", progress_message="Generating report...")
    db.add(job)
    db.commit()
    return job.id


def _row(db, job_id: str) -> Job:
    db.expire_all()
    return db.get(Job, job_id)


def _end(db, job_id: str, end: str) -> None:
    """What the worker writes as its run ends, between the route's read and its write."""
    db.query(Job).filter(Job.id == job_id).update(
        {"status": end, "progress_pct": 100, "progress_message": f"Run {end}"}, synchronize_session=False
    )
    db.commit()


def _the_run_ends_first(monkeypatch, db, end: str, *, before=None) -> None:
    real = job_service.update_job_status

    def ended_then_written(db_, job_id, status, *args, **kwargs):
        if before is not None:
            before(job_id)
        _end(db, job_id, end)
        return real(db_, job_id, status, *args, **kwargs)

    monkeypatch.setattr(job_service, "update_job_status", ended_then_written)


def _cancel(client, job_id: str, revoke=None):
    with patch.object(celery_app.control, "revoke", side_effect=revoke) as revoked:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    return response, revoked


# ================================================================ a cancel that takes


@pytest.mark.parametrize("status_before", ["searching", "awaiting_approval", "extracting", "generating_report"])
def test_a_cancel_that_takes_publishes_one_status_change_once_committed(client, db, test_user, timeline,
                                                                        status_before):
    job_id = _active_row(db, test_user.id, status_before)
    response, revoked = _cancel(client, job_id, revoke=lambda *a, **kw: timeline.append(("REVOKE",)))

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    published = _publishes(timeline)
    assert len(published) == 1
    _, channel, payload = published[0]
    assert channel == f"job_progress:{job_id}"
    # The shape useJobProgress applies for a status change: new_status is the
    # run's status from now on, message its progress line.
    assert {k: payload[k] for k in ("type", "job_id", "old_status", "new_status", "message")} == {
        "type": "job_status_change",
        "job_id": job_id,
        "old_status": status_before,
        "new_status": "cancelled",
        "message": CANCELLED_WORDS,
    }
    assert _published_after_its_commit(timeline)
    # Before the revoke, which can wait on a broker that is down.
    assert timeline.index(published[0]) < timeline.index(("REVOKE",))
    revoked.assert_called_once_with("resume-task-id", terminate=True)
    row = _row(db, job_id)
    assert (row.status, row.progress_message) == ("cancelled", CANCELLED_WORDS)


def test_mutation_without_the_announcement_another_tab_hears_nothing(client, db, test_user, timeline, monkeypatch):
    """The route as it was: the cancel took and nothing went out."""
    monkeypatch.setattr(jobs_router, "_announce_cancelled", lambda *a, **kw: None)
    job_id = _active_row(db, test_user.id)
    response, _ = _cancel(client, job_id)

    assert response.status_code == 200
    assert _publishes(timeline) == []


def test_mutation_a_publish_before_the_write_reads_cancelled_before_the_row_says_it(
    client, db, test_user, timeline, monkeypatch
):
    """A route that publishes before its write: the order check catches it."""
    real_write, announce = job_service.update_job_status, jobs_router._announce_cancelled

    def announced_then_written(db_, job_id, status, *args, **kwargs):
        announce(job_id, "generating_report")
        return real_write(db_, job_id, status, *args, **kwargs)

    monkeypatch.setattr(job_service, "update_job_status", announced_then_written)
    monkeypatch.setattr(jobs_router, "_announce_cancelled", lambda *a, **kw: None)
    job_id = _active_row(db, test_user.id)
    response, _ = _cancel(client, job_id)

    assert response.status_code == 200
    assert len(_publishes(timeline)) == 1
    assert not _published_after_its_commit(timeline)


# ================================================================ a cancel that loses the race


ENDS = ["completed", "failed"]


@pytest.mark.parametrize("end", ENDS)
def test_a_cancel_that_loses_the_race_publishes_nothing(client, db, test_user, timeline, monkeypatch, end):
    """The run ended between the route's read and its write: it keeps its end,
    the answer is 400 (T-5.2.22), and no page is told of a cancel that did not
    happen."""
    job_id = _active_row(db, test_user.id)
    _the_run_ends_first(monkeypatch, db, end)
    response, revoked = _cancel(client, job_id)

    assert response.status_code == 400
    assert _publishes(timeline) == []
    assert _row(db, job_id).status == end
    revoked.assert_not_called()


@pytest.mark.parametrize("end", ["completed", "failed", "cancelled"])
def test_a_cancel_after_the_end_publishes_nothing(client, db, test_user, timeline, end):
    job_id = _active_row(db, test_user.id)
    _end(db, job_id, end)
    response, _ = _cancel(client, job_id)

    assert response.status_code == 400
    assert _publishes(timeline) == []


def test_mutation_a_publish_before_the_write_goes_out_for_a_cancel_that_lost(
    client, db, test_user, timeline, monkeypatch
):
    """Published before the conditional write, the event goes out whatever the
    write does: a page would show a completed run as cancelled."""
    announce = jobs_router._announce_cancelled
    _the_run_ends_first(monkeypatch, db, "completed", before=lambda job_id: announce(job_id, "generating_report"))
    monkeypatch.setattr(jobs_router, "_announce_cancelled", lambda *a, **kw: None)
    job_id = _active_row(db, test_user.id)
    response, _ = _cancel(client, job_id)

    assert response.status_code == 400
    assert [payload["new_status"] for _, _, payload in _publishes(timeline)] == ["cancelled"]
    assert _row(db, job_id).status == "completed"


# ================================================================ a publish that fails


def test_a_publish_redis_refuses_still_cancels(client, db, test_user, timeline, monkeypatch):
    """Redis down: the publisher's own guard logs the error by its type, and
    the cancel answers 200 with the row cancelled and the task revoked."""
    refused = ConnectionError(f"Error connecting to redis://:{SECRET}@broker:6379/0")
    monkeypatch.setattr(progress_service, "_get_redis", lambda: _FakeRedis(timeline, fail=refused))
    job_id = _active_row(db, test_user.id)
    with patch("app.services.progress_service.logger") as logger:
        response, revoked = _cancel(client, job_id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _row(db, job_id).status == "cancelled"
    revoked.assert_called_once_with("resume-task-id", terminate=True)
    logger.warning.assert_called_once()
    assert "ConnectionError" in logger.warning.call_args.args
    assert SECRET not in repr(logger.warning.call_args)


def test_a_publisher_that_raises_still_cancels(client, db, test_user, timeline, monkeypatch):
    """Whatever the publisher raises, the route's own guard logs its type and
    the cancel goes on to the revoke and answers 200."""

    def raising(*args, **kwargs):
        raise RuntimeError(f"redis://:{SECRET}@broker:6379/0 refused")

    monkeypatch.setattr(progress_service, "publish_status_change", raising)
    job_id = _active_row(db, test_user.id)
    with patch("app.routers.jobs.logger") as logger:
        response, revoked = _cancel(client, job_id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _row(db, job_id).status == "cancelled"
    revoked.assert_called_once_with("resume-task-id", terminate=True)
    logger.warning.assert_called_once()
    assert "RuntimeError" in logger.warning.call_args.args
    assert SECRET not in repr(logger.warning.call_args)


def test_mutation_an_unguarded_publish_fails_a_cancel_that_took(client, db, test_user, timeline, monkeypatch):
    """Without the guard, a raising publisher turns a cancel that took into a
    500, with the row already cancelled and the task never revoked."""

    def raising(*args, **kwargs):
        raise RuntimeError("refused")

    def unguarded(job_id, status_before):
        progress_service.publish_status_change(job_id, status_before, "cancelled", CANCELLED_WORDS)

    monkeypatch.setattr(progress_service, "publish_status_change", raising)
    monkeypatch.setattr(jobs_router, "_announce_cancelled", unguarded)
    job_id = _active_row(db, test_user.id)
    with pytest.raises(RuntimeError):
        _cancel(client, job_id)

    assert _row(db, job_id).status == "cancelled"


@pytest.mark.parametrize(
    ("publish", "args"),
    [
        (progress_service.publish_progress, ("job-1", "extracting", 40, "Video 2/5")),
        (progress_service.publish_status_change, ("job-1", "extracting", "cancelled", CANCELLED_WORDS)),
        (progress_service.publish_error, ("job-1", "No transcripts available.")),
    ],
)
def test_each_run_event_publisher_logs_a_refusal_by_its_type(monkeypatch, publish, args):
    refused = ConnectionError(f"Error connecting to redis://:{SECRET}@broker:6379/0")
    monkeypatch.setattr(progress_service, "_get_redis", lambda: _FakeRedis([], fail=refused))
    with patch("app.services.progress_service.logger") as logger:
        publish(*args)

    logger.warning.assert_called_once()
    assert "ConnectionError" in logger.warning.call_args.args
    assert SECRET not in repr(logger.warning.call_args)

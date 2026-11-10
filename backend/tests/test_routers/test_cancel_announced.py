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

T-5.2.32: only the cancel whose own conditional write made the row cancelled
announces it. ``job_service.write_job_status`` reports the row count, so a
second cancel that read the run active and found it cancelled by the first
answers 200 as it always has, and publishes nothing.

Every case runs the real route against the test database, with a fake Redis
client in place of the publisher's (no Redis) and a patched revoke (no
broker). Each check is a function the main cases call, and the mutation
cases at the end run the same checks against the production code changed in
place (``_mutant`` recompiles the real function from its own source with one
edit): the route without its announcement, with it before the write, with
its guard taken out or logging the error's text, and each publisher logging
the error's text. Each check must refuse its mutant.
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.models.job import Job
from app.routers import jobs as jobs_router
from app.services import job_service, progress_service
from app.tasks.celery_app import celery_app
from tests.mutation import mutant as _mutant

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


def _the_run_ends_first(monkeypatch, db, end: str) -> None:
    """The run ends, or with ``cancelled`` another cancel's write lands,
    between the route's read and its own write."""
    real = job_service.write_job_status

    def ended_then_written(db_, job_id, status, *args, **kwargs):
        _end(db, job_id, end)
        return real(db_, job_id, status, *args, **kwargs)

    monkeypatch.setattr(job_service, "write_job_status", ended_then_written)


def _cancel(client, job_id: str, revoke=None):
    with patch.object(celery_app.control, "revoke", side_effect=revoke) as revoked:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    return response, revoked


# ================================================================ the checks


def _check_a_cancel_that_takes(client, db, test_user, timeline, status_before="generating_report"):
    """One publish, on the run's channel, in the shape the hook applies, after
    the commit of the cancel's write and before the revoke; the row cancelled."""
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


def _check_a_cancel_that_loses(client, db, test_user, timeline, monkeypatch, end="completed"):
    """The run ended between the route's read and its write: it keeps its end,
    the answer is 400 (T-5.2.22), nothing is revoked, and no page is told of a
    cancel that did not happen."""
    job_id = _active_row(db, test_user.id)
    _the_run_ends_first(monkeypatch, db, end)
    response, revoked = _cancel(client, job_id)

    assert response.status_code == 400
    assert _publishes(timeline) == []
    assert _row(db, job_id).status == end
    revoked.assert_not_called()


def _check_two_racing_cancels_publish_once(client, db, test_user, timeline, monkeypatch):
    """Two cancels race (T-5.2.32): both read the run active, and the other
    one, the real route run in full, writes and announces first. Both answer
    200 with the run cancelled, as before; one event goes out, from the cancel
    whose write took, after that write's commit."""
    job_id = _active_row(db, test_user.id)
    real = job_service.write_job_status
    other: list = []

    def the_other_cancel_lands_first(db_, job_id_, status, *args, **kwargs):
        if not other:
            other.append(None)
            other[0] = jobs_router.cancel_job(job_id_, db=db_, current_user=test_user)
        return real(db_, job_id_, status, *args, **kwargs)

    monkeypatch.setattr(job_service, "write_job_status", the_other_cancel_lands_first)
    response, revoked = _cancel(client, job_id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert other[0]["status"] == "cancelled"
    published = _publishes(timeline)
    assert len(published) == 1
    assert published[0][2]["new_status"] == "cancelled"
    assert _published_after_its_commit(timeline)
    # Each still revokes, as before: the row is what stops a run.
    assert revoked.call_count == 2
    assert _row(db, job_id).status == "cancelled"


def _check_a_cancel_that_finds_it_cancelled(client, db, test_user, timeline, monkeypatch):
    """Another cancel's write landed between this one's read and its write: the
    answer is 200 with the run cancelled, as it always was, and nothing is
    published, since this cancel's write did not take (T-5.2.32)."""
    job_id = _active_row(db, test_user.id)
    _the_run_ends_first(monkeypatch, db, "cancelled")
    response, _ = _cancel(client, job_id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _publishes(timeline) == []
    assert _row(db, job_id).status == "cancelled"


def _check_a_publish_redis_refuses(client, db, test_user, timeline, monkeypatch):
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


def _check_a_publisher_that_raises(client, db, test_user, timeline, monkeypatch):
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


def _check_a_publisher_logs_a_refusal_by_its_type(monkeypatch, publish, args):
    refused = ConnectionError(f"Error connecting to redis://:{SECRET}@broker:6379/0")
    monkeypatch.setattr(progress_service, "_get_redis", lambda: _FakeRedis([], fail=refused))
    with patch("app.services.progress_service.logger") as logger:
        publish(*args)

    logger.warning.assert_called_once()
    assert "ConnectionError" in logger.warning.call_args.args
    assert SECRET not in repr(logger.warning.call_args)


PUBLISHERS = [
    pytest.param(progress_service.publish_progress, ("job-1", "extracting", 40, "Video 2/5"), id="progress"),
    pytest.param(progress_service.publish_status_change, ("job-1", "extracting", "cancelled", CANCELLED_WORDS),
                 id="status_change"),
    pytest.param(progress_service.publish_error, ("job-1", "No transcripts available."), id="error"),
]


# ================================================================ a cancel that takes


@pytest.mark.parametrize("status_before", ["searching", "awaiting_approval", "extracting", "generating_report"])
def test_a_cancel_that_takes_publishes_one_status_change_once_committed(client, db, test_user, timeline,
                                                                        status_before):
    _check_a_cancel_that_takes(client, db, test_user, timeline, status_before)


# ================================================================ a cancel that loses the race


@pytest.mark.parametrize("end", ["completed", "failed"])
def test_a_cancel_that_loses_the_race_publishes_nothing(client, db, test_user, timeline, monkeypatch, end):
    _check_a_cancel_that_loses(client, db, test_user, timeline, monkeypatch, end)


@pytest.mark.parametrize("end", ["completed", "failed", "cancelled"])
def test_a_cancel_after_the_end_publishes_nothing(client, db, test_user, timeline, end):
    """A cancel of a run already over answers 400 at the route's first check,
    a run already cancelled included, as it always has."""
    job_id = _active_row(db, test_user.id)
    _end(db, job_id, end)
    response, _ = _cancel(client, job_id)

    assert response.status_code == 400
    assert _publishes(timeline) == []


# ================================================================ a second cancel (T-5.2.32)


def test_two_racing_cancels_publish_once(client, db, test_user, timeline, monkeypatch):
    _check_two_racing_cancels_publish_once(client, db, test_user, timeline, monkeypatch)


def test_a_cancel_whose_write_finds_the_run_cancelled_answers_200_and_publishes_nothing(
    client, db, test_user, timeline, monkeypatch
):
    _check_a_cancel_that_finds_it_cancelled(client, db, test_user, timeline, monkeypatch)


def test_write_job_status_says_whether_its_own_write_took(db, test_user):
    """The contract the route reads: ``written`` is this call's row count, so a
    status the row already holds tells a refused write from one that took, and
    the conditional write moves ``updated_at`` as the ORM's flush does."""
    job_id = _active_row(db, test_user.id)
    # Long ago, so the move shows whatever the clock's resolution (on Windows
    # two writes a few milliseconds apart can read the same time).
    before = datetime(2000, 1, 1)
    db.query(Job).filter(Job.id == job_id).update({"updated_at": before}, synchronize_session=False)
    db.commit()

    took = job_service.write_job_status(db, job_id, "cancelled", progress_message=CANCELLED_WORDS, unless_ended=True)
    again = job_service.write_job_status(db, job_id, "cancelled", progress_message="again", unless_ended=True)

    assert (took.job.status, took.written) == ("cancelled", True)
    assert (again.job.status, again.written) == ("cancelled", False)
    row = _row(db, job_id)
    assert row.progress_message == CANCELLED_WORDS
    assert row.updated_at > before
    assert job_service.write_job_status(db, "no-such-job", "cancelled", unless_ended=True) == (None, False)
    # The other callers' contract is unchanged: the row, either way.
    assert job_service.update_job_status(db, job_id, "cancelled", unless_ended=True).status == "cancelled"


# ================================================================ a publish that fails


def test_a_publish_redis_refuses_still_cancels(client, db, test_user, timeline, monkeypatch):
    _check_a_publish_redis_refuses(client, db, test_user, timeline, monkeypatch)


def test_a_publisher_that_raises_still_cancels(client, db, test_user, timeline, monkeypatch):
    _check_a_publisher_that_raises(client, db, test_user, timeline, monkeypatch)


@pytest.mark.parametrize(("publish", "args"), PUBLISHERS)
def test_each_run_event_publisher_logs_a_refusal_by_its_type(monkeypatch, publish, args):
    _check_a_publisher_logs_a_refusal_by_its_type(monkeypatch, publish, args)


# ================================================================ mutation checks on the real code

_ANNOUNCE = "    _announce_cancelled(job_id, status_before)\n"
# T-5.2.32: the announcement, only when this cancel's own write took.
_ANNOUNCE_IF_WRITTEN = "    if written:\n        _announce_cancelled(job_id, status_before)\n"
_CONDITIONAL_WRITE = '    job, written = job_service.write_job_status(\n        db, job_id, "cancelled",'
_GUARDED_PUBLISH = (
    "    try:\n"
    '        progress_service.publish_status_change(job_id, status_before, "cancelled", _CANCELLED_WORDS)\n'
    "    except Exception as e:  # noqa: BLE001 - the row already says cancelled\n"
    '        logger.warning("[job:%s] cancelled, but the change could not be published: %s", job_id,'
    " type(e).__name__)\n"
)
_UNGUARDED_PUBLISH = (
    '    progress_service.publish_status_change(job_id, status_before, "cancelled", _CANCELLED_WORDS)\n'
)
_ANNOUNCED_BEFORE_THE_WRITE = ((_ANNOUNCE_IF_WRITTEN, ""), (_CONDITIONAL_WRITE, _ANNOUNCE + _CONDITIONAL_WRITE))
_LOGS_THE_TEXT = ("job_id, type(e).__name__)", "job_id, e)")


def test_mutation_a_route_that_announces_nothing_fails_the_take_check(client, db, test_user, timeline,
                                                                     monkeypatch):
    """The route as it was before T-5.2.30: the cancel took and nothing went out."""
    _mutant(monkeypatch, jobs_router.cancel_job, (_ANNOUNCE_IF_WRITTEN, ""))
    with pytest.raises(AssertionError):
        _check_a_cancel_that_takes(client, db, test_user, timeline)
    assert _publishes(timeline) == []


def test_mutation_a_route_that_announces_before_its_write_fails_the_take_check(client, db, test_user, timeline,
                                                                              monkeypatch):
    """Published before the conditional write: a page reads ``cancelled``
    before the row says it."""
    _mutant(monkeypatch, jobs_router.cancel_job, *_ANNOUNCED_BEFORE_THE_WRITE)
    with pytest.raises(AssertionError):
        _check_a_cancel_that_takes(client, db, test_user, timeline)
    assert len(_publishes(timeline)) == 1


def test_mutation_a_route_that_announces_before_its_write_fails_the_lose_check(client, db, test_user, timeline,
                                                                              monkeypatch):
    """Published before the conditional write, the event goes out whatever the
    write does: a page would show a completed run as cancelled."""
    _mutant(monkeypatch, jobs_router.cancel_job, *_ANNOUNCED_BEFORE_THE_WRITE)
    with pytest.raises(AssertionError):
        _check_a_cancel_that_loses(client, db, test_user, timeline, monkeypatch)
    assert [payload["new_status"] for _, _, payload in _publishes(timeline)] == ["cancelled"]


def test_mutation_a_route_that_announces_whatever_its_write_did_fails_the_second_cancel_checks(
    client, db, test_user, timeline, monkeypatch
):
    """The route as #453 left it: announced once the row says cancelled, by
    whichever cancel wrote it. The race publishes twice, and a cancel whose
    write found the run cancelled publishes the other's event again."""
    _mutant(monkeypatch, jobs_router.cancel_job, (_ANNOUNCE_IF_WRITTEN, _ANNOUNCE))
    with pytest.raises(AssertionError):
        _check_two_racing_cancels_publish_once(client, db, test_user, timeline, monkeypatch)
    assert len(_publishes(timeline)) == 2


def test_mutation_a_route_that_announces_whatever_its_write_did_fails_the_found_cancelled_check(
    client, db, test_user, timeline, monkeypatch
):
    _mutant(monkeypatch, jobs_router.cancel_job, (_ANNOUNCE_IF_WRITTEN, _ANNOUNCE))
    with pytest.raises(AssertionError):
        _check_a_cancel_that_finds_it_cancelled(client, db, test_user, timeline, monkeypatch)
    assert len(_publishes(timeline)) == 1


def test_mutation_a_write_that_always_says_written_fails_the_second_cancel_checks(
    client, db, test_user, timeline, monkeypatch
):
    """``write_job_status`` reporting a write it did not make, so the route
    cannot tell the cancels apart."""
    _mutant(monkeypatch, job_service.write_job_status,
            ("written = query.update(values, synchronize_session=False) == 1",
             "query.update(values, synchronize_session=False)"))
    with pytest.raises(AssertionError):
        _check_a_cancel_that_finds_it_cancelled(client, db, test_user, timeline, monkeypatch)


def test_mutation_an_unguarded_announcement_fails_the_raising_publisher_check(client, db, test_user, timeline,
                                                                             monkeypatch):
    """Without the route's guard, a raising publisher turns a cancel that took
    into a 500 (the test client re-raises the route's error), with the row
    already cancelled and the task never revoked."""
    _mutant(monkeypatch, jobs_router._announce_cancelled, (_GUARDED_PUBLISH, _UNGUARDED_PUBLISH))
    with pytest.raises(RuntimeError):
        _check_a_publisher_that_raises(client, db, test_user, timeline, monkeypatch)


def test_mutation_a_guard_that_logs_the_error_text_fails_the_raising_publisher_check(
    client, db, test_user, timeline, monkeypatch
):
    _mutant(monkeypatch, jobs_router._announce_cancelled, _LOGS_THE_TEXT)
    with pytest.raises(AssertionError):
        _check_a_publisher_that_raises(client, db, test_user, timeline, monkeypatch)


def test_mutation_a_publisher_that_logs_the_error_text_fails_the_redis_check(client, db, test_user, timeline,
                                                                            monkeypatch):
    _mutant(monkeypatch, progress_service.publish_status_change, _LOGS_THE_TEXT)
    with pytest.raises(AssertionError):
        _check_a_publish_redis_refuses(client, db, test_user, timeline, monkeypatch)


@pytest.mark.parametrize(("publish", "args"), PUBLISHERS)
def test_mutation_each_publisher_logging_the_error_text_fails_its_check(monkeypatch, publish, args):
    _mutant(monkeypatch, publish, _LOGS_THE_TEXT)
    with pytest.raises(AssertionError):
        _check_a_publisher_logs_a_refusal_by_its_type(monkeypatch, publish, args)

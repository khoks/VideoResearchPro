"""Run stops, the three edges T-5.2.20 left (D-161's consequences).

T-5.2.21: a progress publish that is not tied to a status write could go out
after a stop. The sync's "N videos ingested so far" had no check before it at
all, and the per-channel and per-phase publishes followed an ``_is_stopped``
read that a stop could land just after. Each is now written first, in the
run's one conditional write, and published only once written
(``job_tasks._report_progress``); "Indexed N new chunks" rides on the write
it already followed.

T-5.2.22: ``POST /jobs/{id}/cancel`` wrote ``cancelled`` unconditionally, so a
run that completed or failed between the route's read and its write was
turned into a cancelled one. The write is now conditional on the run not
having ended (``update_job_status(..., unless_ended=True)``); a run that
ended first keeps its end, the route answers what a cancel a moment later
answers (400, with what it ended as), and nothing is revoked.

T-5.2.23: tasks ack late (``task_acks_late``), so a worker that died after a
run's last write and before the ack had its task delivered again, and
``completed`` was not a stopped status: the whole run ran a second time. A
completed row now reads as over everywhere a stopped one does. A first
phase (topic search, channel listing) ends at ``awaiting_approval``, so it
also leaves alone a row there or past it, where the resume may be running,
and its orphan backstop fails only the two states it writes itself.

Every case runs the real task or route with the test database, an
in-memory Chroma and fakes for every connector, the search agent, the era
call and the report (the fixtures of ``test_stopped_run_stays_stopped``): no
network and no model. A mutation check sits beside each mechanism.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import chroma_service, job_service
from app.sources.types import Candidate
from app.tasks import job_tasks
from app.tasks.celery_app import celery_app
from tests.test_tasks import test_stopped_run_stays_stopped as stopped
from tests.test_tasks.test_stopped_run_stays_stopped import (
    CANCELLED_WORDS,
    CHANNEL,
    PICKED,
    REAL_TASKS,
    _cancel,
    _job_with_videos,
    _snapshot,
    _status_changes,
)

# The T-5.2.20 cases' fixtures: the test database, an in-memory Chroma, and
# every way out of a run faked or recorded.
ephemeral_chroma = stopped.ephemeral_chroma
worker = stopped.worker

UPLOAD = "vRunStops001"


def _progress_messages(worker) -> list[str]:
    return [c.args[3] for c in worker.progress.publish_progress.call_args_list]


def _published_after(worker, mark: int) -> list:
    """Every progress-service call made after the first ``mark`` ones."""
    return worker.progress.mock_calls[mark:]


def _progress_after(worker, mark: int) -> list[str]:
    """The progress messages published after the first ``mark`` calls."""
    return [c.args[3] for c in _published_after(worker, mark) if c[0] == "publish_progress"]


def _channel(db) -> None:
    db.add(Channel(channel_id=CHANNEL, name="Stopped Channel", uploads_playlist_id="UUstoppedRun0001"))
    db.commit()


def _sync_row(db, tenant_id: str, status: str = "pending") -> str:
    job = Job(job_type="subscription", status=status, topic="Sync Stopped Channel",
              channel_list=json.dumps([CHANNEL]), num_videos=0, tenant_id=tenant_id)
    db.add(job)
    db.commit()
    return job.id


def _publish_without_its_write(db, job, stage, pct, message, data=None):
    """``_report_progress`` as the publishes were before T-5.2.21: sent
    whatever the row says. The mutation the T-5.2.21 cases must catch."""
    job_tasks.progress_service.publish_progress(job.id, stage, pct, message, data=data)


# ================================================================ T-5.2.21: a stopped run publishes nothing more


def _sync_cancelled_during_its_walk(client, db, worker, tenant_id: str) -> tuple[str, list[int]]:
    """The user cancels while the sync lists the channel's uploads (the
    YouTube call a walk spends its time in). Returns the job and how many
    progress-service calls had been made when the cancel landed."""
    _channel(db)
    job_id = _sync_row(db, tenant_id)
    mark: list[int] = []

    def uploads(channel_id, job_id=None, uploads_playlist_id=None):
        _cancel(client, job_id)
        mark.append(len(worker.progress.mock_calls))
        return [UPLOAD]

    worker.uploads.side_effect = uploads
    REAL_TASKS["execute_subscription_job"].run(job_id)
    return job_id, mark


def test_a_sync_cancelled_during_its_walk_publishes_nothing_more(client, db, worker, test_user):
    """The walk in hand finishes its database work, and its "N videos
    ingested so far" is refused at its write, so the page that shows the run
    cancelled gets no event that shows it searching again, and the sync stops
    there: nothing is read."""
    job_id, mark = _sync_cancelled_during_its_walk(client, db, worker, test_user.id)

    assert _published_after(worker, mark[0]) == []
    assert not any("ingested so far" in m for m in _progress_messages(worker))
    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"]) == ("cancelled", CANCELLED_WORDS)
    assert "fetch_text" not in worker.connector.calls


def test_mutation_the_walks_publish_without_its_write_goes_out_after_the_cancel(
    client, db, worker, test_user, monkeypatch
):
    """The publish as it was: one event after the cancel. (The extraction's
    first status write still stops the run, so the row stays cancelled.)"""
    monkeypatch.setattr(job_tasks, "_report_progress", _publish_without_its_write)

    job_id, mark = _sync_cancelled_during_its_walk(client, db, worker, test_user.id)

    after = _progress_after(worker, mark[0])
    assert after == ["1 videos ingested so far..."]
    assert _snapshot(db, job_id)["status"] == "cancelled"


SECOND_CHANNEL = "UCstoppedRun0002"


def _channel_job_cancelled_on_its_first_channel(client, db, worker, test_user) -> tuple[str, list[int]]:
    job = Job(job_type="channel", status="pending", topic=None, tenant_id=test_user.id,
              channel_list=json.dumps([CHANNEL, SECOND_CHANNEL]), videos_per_channel=5)
    db.add(job)
    db.commit()
    mark: list[int] = []

    def list_items(creator_id, limit=10, job_id=""):
        worker.connector.calls.append("list_creator_items")
        _cancel(client, job.id)
        mark.append(len(worker.progress.mock_calls))
        return []

    worker.connector.list_creator_items = list_items
    REAL_TASKS["execute_channel_job"].run(job.id)
    return job.id, mark


def test_a_channel_job_cancelled_on_one_channel_publishes_nothing_more(client, db, worker, test_user):
    """The next channel's progress is the check: refused, it is not published,
    and the second channel is never resolved or listed."""
    job_id, mark = _channel_job_cancelled_on_its_first_channel(client, db, worker, test_user)

    assert _published_after(worker, mark[0]) == []
    assert worker.connector.calls == ["resolve_creator_id", "list_creator_items"]
    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"]) == ("cancelled", CANCELLED_WORDS)


def test_mutation_a_channel_publish_without_its_write_goes_out_and_the_job_runs_on(
    client, db, worker, test_user, monkeypatch
):
    monkeypatch.setattr(job_tasks, "_report_progress", _publish_without_its_write)

    job_id, mark = _channel_job_cancelled_on_its_first_channel(client, db, worker, test_user)

    after = _progress_after(worker, mark[0])
    assert after == [f"Processing channel 2/2: {SECOND_CHANNEL}"]
    assert worker.connector.calls.count("list_creator_items") == 2
    assert _snapshot(db, job_id)["status"] == "cancelled"


def test_a_resume_cancelled_while_its_chunks_go_in_publishes_no_indexed_event(
    client, db, worker, test_user, monkeypatch
):
    """'Indexed N new chunks' rides on the write that follows the insert,
    so a cancel during the insert gets no event and no report."""
    job_id = _job_with_videos(db, test_user.id, ["vIndexed0001"])
    real_insert = chroma_service.insert_chunks

    def cancel_then_insert(chunks):
        _cancel(client, job_id)
        return real_insert(chunks)

    monkeypatch.setattr(chroma_service, "insert_chunks", cancel_then_insert)

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    assert not any(m.startswith("Indexed") for m in _progress_messages(worker))
    worker.report.assert_not_called()
    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"]) == ("cancelled", CANCELLED_WORDS)


def test_a_sync_that_is_not_stopped_publishes_every_progress_and_keeps_it(client, db, worker, test_user):
    """The other side: nothing a running sync reported before is lost, in
    order, and each report is on the row when it goes out."""
    _channel(db)
    job_id = _sync_row(db, test_user.id)
    worker.uploads.return_value = [UPLOAD]
    on_the_row: list[tuple[str, str]] = []

    def publish(job_id_, stage, pct, message, data=None):
        db.expire_all()
        on_the_row.append((message, db.get(Job, job_id_).progress_message))

    worker.progress.publish_progress.side_effect = publish

    REAL_TASKS["execute_subscription_job"].run(job_id)

    messages = [m for m, _ in on_the_row]
    assert messages[:4] == [
        f"Resolving channel 1/1: {CHANNEL}",
        "Resolved 1 channel(s). Walking uploads...",
        "Walking uploads for Stopped Channel (1/1)",
        "1 videos ingested so far...",
    ]
    assert messages[4].startswith("Video 1/1: 1 fetched")
    assert messages[5].startswith("Indexed ")
    assert all(published == stored for published, stored in on_the_row)
    assert _snapshot(db, job_id)["status"] == "completed"


def _statements(db, call) -> list[str]:
    """The statements ``call`` sends the database, by their first word, and
    each COMMIT."""
    seen: list[str] = []
    engine = db.get_bind()

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement.split(None, 1)[0].upper())

    def on_commit(conn):
        seen.append("COMMIT")

    event.listen(engine, "before_cursor_execute", on_execute)
    event.listen(engine, "commit", on_commit)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
        event.remove(engine, "commit", on_commit)
    return seen


def test_a_gate_costs_a_write_and_a_read_where_the_check_was_one_read(db, worker, test_user):
    """What ``_report_progress``'s docstring says each gate costs, held to the
    code. The ``_is_stopped`` read it replaced was one SELECT. The gate is a
    conditional UPDATE, its COMMIT (on SQLite, the writer lock until then)
    and the SELECT that refreshes the job; when a commit since the run's last
    write has expired the job (the gate after a channel's walk follows the
    walk's commits), reading its id first is one SELECT more. Refused, it
    costs the same and publishes nothing."""
    job_id = _sync_row(db, test_user.id, status="searching")
    job = db.get(Job, job_id)

    assert _statements(db, lambda: job_tasks._is_stopped(db, job_id)) == ["SELECT"]
    fresh = _statements(db, lambda: job_tasks._report_progress(db, job, "searching", 18, "Walking uploads..."))
    assert fresh == ["UPDATE", "COMMIT", "SELECT"]

    db.commit()  # as the walk's own commits do: the job is expired
    after_commit = _statements(db, lambda: job_tasks._report_progress(db, job, "searching", 25, "1 videos..."))
    assert after_commit == ["SELECT", "UPDATE", "COMMIT", "SELECT"]
    assert worker.progress.publish_progress.call_count == 2

    db.query(Job).filter(Job.id == job_id).update({"status": "cancelled"}, synchronize_session=False)
    db.commit()

    def stopped_gate():
        with pytest.raises(job_tasks._RunStopped):
            job_tasks._report_progress(db, job, "searching", 25, "2 videos ingested so far...")

    assert _statements(db, stopped_gate) == ["SELECT", "UPDATE", "COMMIT", "SELECT"]
    assert worker.progress.publish_progress.call_count == 2


# ================================================================ T-5.2.22: cancel never writes over an ended run


def _end(db, job_id: str, end: str) -> None:
    """What the worker writes as its run ends, landing between the cancel
    route's read and its write."""
    fields = {"status": end, "progress_pct": 100}
    if end == "completed":
        fields.update(progress_message="Job completed successfully!", report_path="report.html")
    else:
        fields.update(progress_message="Failed", error_message="No transcripts could be fetched for any video.")
    db.query(Job).filter(Job.id == job_id).update(fields, synchronize_session=False)
    db.commit()


def _active_row(db, tenant_id: str) -> str:
    job = Job(job_type="topic", topic="tariffs", status="generating_report", tenant_id=tenant_id,
              celery_task_id="resume-task-id", progress_message="Generating report...")
    db.add(job)
    db.commit()
    return job.id


def _the_run_ends_first(monkeypatch, db, end: str, *, conditional: bool = True) -> None:
    real = job_service.update_job_status

    def ended_then_written(db_, job_id, status, *args, **kwargs):
        _end(db, job_id, end)
        if not conditional:
            kwargs.pop("unless_ended", None)
        return real(db_, job_id, status, *args, **kwargs)

    monkeypatch.setattr(job_service, "update_job_status", ended_then_written)


ENDED_ANSWER = {
    "completed": "This run has already completed, so there is nothing to cancel.",
    "failed": "This run has already failed, so there is nothing to cancel.",
}


@pytest.mark.parametrize("end", sorted(ENDED_ANSWER))
def test_a_cancel_that_loses_the_race_leaves_the_end_and_revokes_nothing(client, db, test_user, monkeypatch, end):
    job_id = _active_row(db, test_user.id)
    _the_run_ends_first(monkeypatch, db, end)
    with patch.object(celery_app.control, "revoke") as revoke:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 400
    assert response.json()["detail"] == ENDED_ANSWER[end]
    row = _snapshot(db, job_id)
    assert row["status"] == end
    assert row["progress_message"] != CANCELLED_WORDS
    revoke.assert_not_called()


@pytest.mark.parametrize("end", sorted(ENDED_ANSWER))
def test_a_cancel_after_the_end_answers_the_same(client, db, test_user, end):
    """The route's first check and its conditional write give one answer:
    the reader cannot tell, and need not care, which of them saw the end."""
    job_id = _active_row(db, test_user.id)
    _end(db, job_id, end)
    with patch.object(celery_app.control, "revoke") as revoke:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert (response.status_code, response.json()["detail"]) == (400, ENDED_ANSWER[end])
    revoke.assert_not_called()


def test_mutation_an_unconditional_cancel_write_covers_the_completed_run(client, db, test_user, monkeypatch):
    """The cancel's write as it was: ``cancelled`` over ``completed``, a 200,
    and a revoke for a task that had finished."""
    job_id = _active_row(db, test_user.id)
    _the_run_ends_first(monkeypatch, db, "completed", conditional=False)
    with patch.object(celery_app.control, "revoke") as revoke:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert _snapshot(db, job_id)["status"] == "cancelled"
    revoke.assert_called_once()


def test_a_cancel_that_takes_revokes_the_task_once_the_row_says_cancelled(client, db, test_user):
    job_id = _active_row(db, test_user.id)
    seen: list[str] = []

    def revoke(task_id, terminate=False):
        db.expire_all()
        seen.append(db.get(Job, job_id).status)

    with patch.object(celery_app.control, "revoke", side_effect=revoke) as revoked:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    revoked.assert_called_once_with("resume-task-id", terminate=True)
    assert seen == ["cancelled"]


def test_a_revoke_the_broker_refuses_still_cancels(client, db, test_user):
    """The row stops the run (T-5.2.20); the broker's error, which can quote
    its URL and password, goes to the log by its type alone."""
    job_id = _active_row(db, test_user.id)
    with (
        patch.object(celery_app.control, "revoke",
                     side_effect=ConnectionError("redis://:hunter2@broker:6379/1 refused")),
        patch("app.routers.jobs.logger") as logger,
    ):
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert _snapshot(db, job_id)["status"] == "cancelled"
    logger.warning.assert_called_once()
    assert "hunter2" not in repr(logger.warning.call_args)
    assert "ConnectionError" in logger.warning.call_args.args


def _cancel_entry() -> str:
    """The API reference's entry for the cancel route, up to the next one."""
    text = (Path(__file__).resolve().parents[3] / "docs" / "api-reference.md").read_text(encoding="utf-8")
    start = text.index("### `POST /api/v1/jobs/{job_id}/cancel`")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def test_the_api_reference_names_every_status_a_run_will_not_write_over():
    """The cancel entry states the condition on a run's writes; it names each
    status ``_write_unless_stopped`` refuses, ``completed`` included since
    T-5.2.23, so a reader does not take a redelivered task on a completed
    run to be free to write."""
    entry = _cancel_entry()
    condition = entry[entry.index("conditional on the row being"):entry.index("so a cancel that lands")]
    missing = [status for status in job_tasks._STOPPED_STATUSES if status not in condition]
    assert missing == [], f"the cancel entry's condition leaves out {missing}: {condition!r}"


# ================================================================ T-5.2.23: a finished run is not run again


def _reset(worker) -> None:
    worker.progress.reset_mock()
    worker.metered.reset_mock()
    worker.connector.calls.clear()
    worker.connector.fetched.clear()
    worker.search.reset_mock()
    worker.uploads.reset_mock()
    worker.report.reset_mock()


def _assert_left_alone(db, worker, job_id: str, before: dict) -> None:
    assert _snapshot(db, job_id) == before, "the row is exactly as the first delivery left it"
    assert worker.progress.mock_calls == [], "nothing is published"
    worker.metered.assert_not_called()
    assert worker.connector.calls == []
    worker.search.assert_not_called()
    worker.uploads.assert_not_called()
    worker.report.assert_not_called()


def _completed_resume(db, worker, tenant_id: str) -> str:
    job_id = _job_with_videos(db, tenant_id, ["vDone000001"])
    REAL_TASKS["resume_job_after_approval"].run(job_id)
    assert _snapshot(db, job_id)["status"] == "completed"
    return job_id


def test_a_resume_delivered_again_after_completing_does_nothing(db, worker, test_user):
    """The worker died between writing ``completed`` and the ack, and the
    broker delivered the resume again: no fetch, no model, no report, no
    event, no usage, and the report the first delivery wrote stays."""
    job_id = _completed_resume(db, worker, test_user.id)
    before = _snapshot(db, job_id)
    _reset(worker)

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    _assert_left_alone(db, worker, job_id, before)
    assert os.path.exists(before["report_path"])


def test_a_sync_delivered_again_after_completing_does_nothing(db, worker, test_user):
    _channel(db)
    job_id = _sync_row(db, test_user.id)
    worker.uploads.return_value = [UPLOAD]
    REAL_TASKS["execute_subscription_job"].run(job_id)
    before = _snapshot(db, job_id)
    assert before["status"] == "completed"
    _reset(worker)

    REAL_TASKS["execute_subscription_job"].run(job_id)

    _assert_left_alone(db, worker, job_id, before)


def test_mutation_with_completed_not_stopped_the_resume_runs_again(db, worker, test_user, monkeypatch):
    """``_STOPPED_STATUSES`` as it was: the second delivery opens the usage
    scope, publishes the run's phases over the finished page and builds the
    report again."""
    job_id = _completed_resume(db, worker, test_user.id)
    _reset(worker)
    monkeypatch.setattr(job_tasks, "_STOPPED_STATUSES", ("failed", "cancelled"))

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    assert worker.metered.called
    assert _status_changes(worker) == ["extracting", "building_rag", "generating_report", "completed"]
    worker.report.assert_called_once()


def _topic_run_at_approval(db, worker, tenant_id: str) -> str:
    job = Job(job_type="topic", topic="tariffs", status="pending", tenant_id=tenant_id, num_videos=5)
    db.add(job)
    db.commit()
    worker.search.return_value = ([dict(PICKED)], ["tariffs"], [])
    REAL_TASKS["execute_topic_job"].run(job.id)
    assert _snapshot(db, job.id)["status"] == "awaiting_approval"
    return job.id


def test_a_topic_search_delivered_again_at_approval_does_nothing(db, worker, test_user):
    """The search's run ends at the approval. Delivered again, it searched
    again, spent the planner, YouTube and the ranking call, and wrote
    ``searching`` over the user's review."""
    job_id = _topic_run_at_approval(db, worker, test_user.id)
    before = _snapshot(db, job_id)
    _reset(worker)

    REAL_TASKS["execute_topic_job"].run(job_id)

    _assert_left_alone(db, worker, job_id, before)


def test_mutation_without_the_first_phase_guard_the_search_runs_again(db, worker, test_user, monkeypatch):
    job_id = _topic_run_at_approval(db, worker, test_user.id)
    _reset(worker)
    monkeypatch.setattr(job_tasks, "_PAST_THE_FIRST_PHASE", ())

    REAL_TASKS["execute_topic_job"].run(job_id)

    worker.search.assert_called_once()
    assert _status_changes(worker)[0] == "searching"


FIRST_PHASES = ["execute_channel_job", "execute_topic_job"]


@pytest.mark.parametrize("task_name", FIRST_PHASES)
@pytest.mark.parametrize("status", ["awaiting_approval", "extracting", "building_rag", "generating_report", "completed"])
def test_a_first_phase_delivered_past_its_approval_leaves_the_row(db, worker, test_user, task_name, status):
    """Past the approval the row is the resume's, which may be running right
    now: the first phase neither runs nor fails it."""
    job_type = "channel" if task_name == "execute_channel_job" else "topic"
    job = Job(job_type=job_type, topic="tariffs", status=status, tenant_id=test_user.id,
              channel_list=json.dumps([CHANNEL]), celery_task_id="resume-task-id",
              progress_message="Video 3/9: 3 fetched")
    db.add(job)
    db.commit()
    before = _snapshot(db, job.id)

    REAL_TASKS[task_name].run(job.id)

    _assert_left_alone(db, worker, job.id, before)


def test_mutation_a_backstop_over_every_state_fails_the_running_resume(db, worker, test_user, monkeypatch):
    """The start guard returns, and the first phase's backstop, scoped as
    every task's was, takes the resume's ``extracting`` for its own orphan."""
    monkeypatch.setattr(job_tasks, "_FIRST_PHASE_STATUSES", tuple(job_tasks._TRANSIENT_STATUSES))
    job = Job(job_type="topic", topic="tariffs", status="extracting", tenant_id=test_user.id)
    db.add(job)
    db.commit()

    REAL_TASKS["execute_topic_job"].run(job.id)

    assert _snapshot(db, job.id)["status"] == "failed"


def test_a_completed_row_keeps_the_report_another_delivery_wrote(client, db, worker, test_user):
    """Two deliveries of one resume running at once (a broker that gave the
    message out again while the first still ran): the first completes the
    row while the second writes its report. The second's ``completed`` write
    is refused, and the file it would discard is the one the row points at,
    ``report_<job_id>.html`` for both, so it stays."""
    job_id = _job_with_videos(db, test_user.id, ["vTwice00001"])

    def report(**kwargs):
        path = job_tasks.save_report(job_id, "<html>the other delivery's report</html>")
        db.query(Job).filter(Job.id == job_id).update(
            {"status": "completed", "report_path": path}, synchronize_session=False)
        db.commit()
        return {}, "<p>report</p>"

    worker.report.side_effect = report

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    row = _snapshot(db, job_id)
    assert row["status"] == "completed"
    assert os.path.exists(row["report_path"])
    assert _status_changes(worker).count("completed") == 0, "the refused write publishes nothing"


def test_mutation_discarding_regardless_deletes_the_completed_rows_report(client, db, worker, test_user, monkeypatch):
    monkeypatch.setattr(job_tasks, "_same_file", lambda a, b: False)
    job_id = _job_with_videos(db, test_user.id, ["vTwice00002"])

    def report(**kwargs):
        path = job_tasks.save_report(job_id, "<html>the other delivery's report</html>")
        db.query(Job).filter(Job.id == job_id).update(
            {"status": "completed", "report_path": path}, synchronize_session=False)
        db.commit()
        return {}, "<p>report</p>"

    worker.report.side_effect = report

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    assert not os.path.exists(_snapshot(db, job_id)["report_path"])


# ---------------------------------------------------------------- every path that starts a run on purpose still runs


@pytest.mark.parametrize(
    ("task_name", "job_type", "status", "ends"),
    [
        ("execute_topic_job", "topic", "searching", "awaiting_approval"),
        ("resume_job_after_approval", "topic", "generating_report", "completed"),
        ("resume_job_after_approval", "topic", "awaiting_approval", "completed"),
        ("execute_subscription_job", "subscription", "extracting", "completed"),
    ],
)
def test_a_redelivery_mid_run_still_runs_the_run_again(db, worker, test_user, task_name, job_type, status, ends):
    """A worker that died mid-run left the row in a state its run writes on
    the way; the task delivered again runs the run from the start, as
    before (D-158). The resume from ``awaiting_approval`` is the approval's
    own dispatch reaching the worker before the route's ``extracting``."""
    _channel(db)
    job_id = _job_with_videos(db, test_user.id, ["vMidway00001"], status=status, job_type=job_type)
    worker.search.return_value = ([dict(PICKED)], ["tariffs"], [])
    worker.uploads.return_value = []

    REAL_TASKS[task_name].run(job_id)

    assert _snapshot(db, job_id)["status"] == ends
    assert worker.metered.called


def test_sync_now_after_a_completed_sync_runs_a_new_one(client, db, worker, test_user):
    """Sync now on a channel whose last sync completed makes a new row, and
    its task runs; the completed row is left as it was."""
    _channel(db)
    done = _sync_row(db, test_user.id)
    worker.uploads.return_value = [UPLOAD]
    REAL_TASKS["execute_subscription_job"].run(done)
    done_before = _snapshot(db, done)
    assert done_before["status"] == "completed"
    _reset(worker)

    with patch("app.tasks.job_tasks.execute_subscription_job") as task:
        task.apply_async.return_value = MagicMock(id="sync-again-task-id")
        response = client.post(f"/api/v1/channels/{CHANNEL}/sync")
    new_id = response.json()["job_id"]
    assert new_id and new_id != done

    REAL_TASKS["execute_subscription_job"].run(new_id)

    assert _snapshot(db, new_id)["status"] == "completed"
    assert worker.metered.called
    assert _snapshot(db, done) == done_before


def test_an_approval_still_runs_its_resume(client, db, worker, test_user):
    job_id = _job_with_videos(db, test_user.id, ["vApproved001"], status="awaiting_approval")
    approved = client.put(f"/api/v1/jobs/{job_id}/approve", json={"approved_video_ids": ["vApproved001"]})
    assert approved.json()["status"] == "extracting"

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    assert _snapshot(db, job_id)["status"] == "completed"
    assert db.query(JobVideo).filter(JobVideo.job_id == job_id).count() == 1


def test_a_channel_job_from_pending_still_reaches_approval(db, worker, test_user):
    """The channel first phase's own start, with its listing answering."""
    from app.sources.types import SourceMetadata

    _channel(db)
    job = Job(job_type="channel", status="pending", tenant_id=test_user.id,
              channel_list=json.dumps([CHANNEL]), videos_per_channel=5)
    db.add(job)
    db.commit()

    def list_items(creator_id, limit=10, job_id=""):
        return [Candidate(source_type="video", source_id="vListed00001", title="Listed",
                          source_url="https://www.youtube.com/watch?v=vListed00001")]

    def fetch_metadata(ids, job_id=""):
        return {vid: SourceMetadata(title="Listed", creator_external_id=CHANNEL, creator_name="Stopped Channel",
                                    duration_seconds=600,
                                    extra={"url": f"https://www.youtube.com/watch?v={vid}"}) for vid in ids}

    worker.connector.list_creator_items = list_items
    worker.connector.fetch_metadata = fetch_metadata

    REAL_TASKS["execute_channel_job"].run(job.id)

    assert _snapshot(db, job.id)["status"] == "awaiting_approval"
    assert db.query(Document).filter(Document.video_id == "vListed00001").count() == 1

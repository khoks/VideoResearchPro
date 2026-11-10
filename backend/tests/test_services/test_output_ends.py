"""T-5.2.34: an Author output's end goes out after the write that ends it, and
never over an output that already ended.

Outputs stop as runs do: an output in ``TERMINAL_STATUSES`` (completed,
failed, cancelled, skipped) is not run again (``generate_output``'s start
guard), a cancel refuses it, and a cancel that lands during generation wins
over the run's own end, since the user was told it stopped. But every write
was a read and then an unconditional ORM write. ``report_progress`` read the
status, committed, then published, so a cancel landing after the read was
followed by a progress event naming ``generating``; the run's ``completed``
followed a read too, and a cancel landing after it was overwritten; and the
cancel route wrote ``cancelled`` over an output that finished after its read.

Every status and progress write is now one conditional ``UPDATE`` that refuses
an ended row (``output_service._write_unless_ended``), with the run's own
pending changes in the same transaction, and its event is published only
once it has committed. The open page drops events for an output it holds as
ended (``useOutputsProgress``), which is sound only while that holds.

The cases run the real service and the real cancel route against the test
database, with a fake Redis client in place of the publisher's and a scripted
outputter in place of the book's. The API's cancel lands from a session of
its own, as from another process. Each check is a function the main cases
call; the mutation cases run the same checks against the production code
with its condition, or its order, changed (``tests.mutation.mutant``).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event

from app.models.job import Job
from app.models.output import Output
from app.models.output_citation import OutputCitation
from app.services import (
    auth_service,
    output_artifacts,
    output_citation_service,
    output_service,
    progress_service,
    task_routing_service,
)
from app.services.output_citation_service import CitationSpec
from app.services.output_service import OutputError, OutputStatus
from app.tasks.celery_app import celery_app
from tests.conftest import TestingSessionLocal
from tests.mutation import mutant

CANCELLED_WORDS = "Cancelled by user"


class _FakeRedis:
    """The publisher's Redis client: each publish joins the timeline."""

    def __init__(self, timeline: list):
        self.timeline = timeline

    def publish(self, channel: str, data: str) -> int:
        self.timeline.append(("PUBLISH", channel, json.loads(data)))
        return 0


@pytest.fixture
def timeline(db, monkeypatch):
    """Every write to ``outputs``, every COMMIT, every publish and the moment
    the API's cancel committed, in order."""
    seen: list = []
    engine = db.get_bind()

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE OUTPUTS"):
            seen.append(("UPDATE outputs",))

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


@pytest.fixture
def discarded(monkeypatch):
    """The outputs whose files were removed."""
    removed: list[str] = []
    monkeypatch.setattr(output_artifacts, "delete_artifacts", lambda output: removed.append(output.id) or True)
    return removed


def _publishes(timeline: list) -> list:
    return [entry for entry in timeline if entry[0] == "PUBLISH"]


def _statuses_published(timeline: list) -> list[str]:
    return [payload["new_status"] for _, _, payload in _publishes(timeline) if payload["type"] == "job_status_change"]


def _each_publish_follows_its_commit(timeline: list) -> bool:
    """Every publish follows a write to ``outputs`` made since the action began
    (``START``, so the test's own setup does not count) and a COMMIT after it."""
    start = timeline.index(("START",))
    for at, entry in enumerate(timeline):
        if entry[0] != "PUBLISH":
            continue
        writes = [i for i, e in enumerate(timeline[start:at], start) if e[0] == "UPDATE outputs"]
        if not writes or not any(e[0] == "COMMIT" for e in timeline[writes[-1]:at]):
            return False
    return True


def _published_after(timeline: list, marker: str) -> list:
    at = timeline.index((marker,))
    return [entry for entry in timeline[at:] if entry[0] == "PUBLISH"]


def _user(db, email: str = "ends@x.com"):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"
    db.commit()
    return user


def _row(db, user, status: str = OutputStatus.PENDING.value, task_id: str | None = "gen-task-id") -> Output:
    row = output_service.create_output(db, user_id=user.id, kind="book", title="B", source_ids=["j"])
    row.status = status
    row.celery_task_id = task_id
    db.commit()
    return row


def _fresh(db, output_id: str) -> Output:
    db.expire_all()
    return db.get(Output, output_id)


def _elsewhere(timeline: list, output_id: str, marker: str, **values) -> None:
    """Another process writes the row (the API's cancel, or another delivery
    of the task) and commits, from a session of its own."""
    other = TestingSessionLocal()
    try:
        other.query(Output).filter(Output.id == output_id).update(values, synchronize_session=False)
        other.commit()
    finally:
        other.close()
    timeline.append((marker,))


class _Scripted:
    """An outputter that does what its test says, step by step."""

    kind = "book"

    def __init__(self, *steps):
        self.steps = steps

    def generate(self, db, user, output):
        for step in self.steps:
            step(db, output)


def _progress(pct: int, message: str):
    return lambda db, output: output_service.report_progress(db, output, pct, message)


def _content(text: str):
    def step(db, output):
        output.content_text = text
    return step


def _cancel_lands(timeline: list):
    return lambda db, output: _elsewhere(
        timeline, output.id, "CANCEL", status=OutputStatus.CANCELLED.value, progress_message=CANCELLED_WORDS
    )


def _another_delivery_completes(timeline: list):
    return lambda db, output: _elsewhere(
        timeline, output.id, "COMPLETED ELSEWHERE", status=OutputStatus.COMPLETED.value, content_text="theirs"
    )


def _fails(message: str):
    def step(db, output):
        raise OutputError(message)
    return step


def _cites(*labels: str):
    """The outputter records its citations, uncommitted: they go in with the
    next write, as ``record_citations`` says."""
    def step(db, output):
        output_citation_service.record_citations(
            db, output, [CitationSpec(label=label, href=None, url=None, seconds=None) for label in labels]
        )
    return step


def _file(fmt: str):
    """The outputter writes a file into the output's folder, as
    ``write_artifact`` does: the row points at it from its next write."""
    def step(db, output):
        output.content_path = f"{output.user_id}/{output.id}/artifact.{fmt}"
    return step


def _book_up_to_its_pdf() -> tuple:
    """The book outputter's order: the manuscript and its citations are set,
    then the EPUB and PDF progress reports commit them with the EPUB's path
    (``BookMarkdownOutputter._write_files``)."""
    return (
        _progress(40, "Chapter 1 of 1"),
        _content("# B"),
        _cites("one", "two"),
        _progress(92, "Building the EPUB"),
        _file("epub"),
        _progress(95, "Printing the PDF"),
    )


def _another_delivery_fails(timeline: list):
    return lambda db, output: _elsewhere(
        timeline, output.id, "FAILED ELSEWHERE", status=OutputStatus.FAILED.value,
        error_message="Their PDF failed.", progress_message="Failed",
    )


def _citations(db, output_id: str) -> int:
    db.expire_all()
    return db.query(OutputCitation).filter(OutputCitation.output_id == output_id).count()


def _leftovers(db, output_id: str) -> tuple:
    """What an output that did not complete must not keep: its text, its file
    and its citations."""
    row = _fresh(db, output_id)
    return row.content_text, row.content_path, _citations(db, output_id)


def _generate(db, monkeypatch, timeline, user, row, *steps) -> Output:
    monkeypatch.setitem(output_service._OUTPUTTERS, "book", _Scripted(*steps))
    timeline.append(("START",))
    return output_service.run_generation(db, user, row)


def _cancel(client, timeline, user, output_id: str, revoke=None):
    token, _ = auth_service.create_access_token(user.id)
    with patch.object(celery_app.control, "revoke", side_effect=revoke) as revoked:
        timeline.append(("START",))
        response = client.post(
            f"/api/v1/author/outputs/{output_id}/cancel", headers={"Authorization": f"Bearer {token}"}
        )
    return response, revoked


# ================================================================ the checks: the worker


def _check_a_run_that_completes(db, monkeypatch, timeline, discarded):
    """Each event, the end included, goes out after the commit of its write."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(db, monkeypatch, timeline, user, row, _progress(40, "Chapter 1 of 1"), _content("# B"))

    assert result.status == OutputStatus.COMPLETED.value
    assert _statuses_published(timeline) == ["generating", "completed"]
    assert [payload["progress_pct"] for _, _, payload in _publishes(timeline) if payload["type"] == "job_progress"] == [5, 40]
    assert _each_publish_follows_its_commit(timeline)
    done = _fresh(db, row.id)
    assert (done.status, done.content_text, done.progress_pct) == ("completed", "# B", 100)
    assert discarded == []


def _check_a_cancel_after_the_last_report_wins(db, monkeypatch, timeline, discarded):
    """The API's cancel commits after the outputter's last progress report and
    before the run writes ``completed``: the output stays cancelled, with none
    of this run's content and no files, and no end goes out after the cancel."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(
        db, monkeypatch, timeline, user, row, _progress(40, "Chapter 1 of 1"), _content("# B"), _cancel_lands(timeline)
    )

    assert result.status == OutputStatus.CANCELLED.value
    assert _published_after(timeline, "CANCEL") == []
    assert "completed" not in _statuses_published(timeline)
    done = _fresh(db, row.id)
    assert (done.status, done.content_text, done.progress_message) == ("cancelled", None, CANCELLED_WORDS)
    assert discarded == [row.id]


def _check_a_cancel_before_a_report_stops_it(db, monkeypatch, timeline, discarded):
    """A progress report after the cancel is neither written nor published: the
    run stops there, cancelled, and the page is told nothing more."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(
        db, monkeypatch, timeline, user, row, _progress(40, "Chapter 1 of 2"), _cancel_lands(timeline),
        _progress(70, "Chapter 2 of 2"), _content("# B"),
    )

    assert result.status == OutputStatus.CANCELLED.value
    assert _published_after(timeline, "CANCEL") == []
    done = _fresh(db, row.id)
    assert (done.status, done.progress_pct, done.content_text) == ("cancelled", 40, None)
    assert discarded == [row.id]


def _check_a_failure_after_a_cancel_keeps_the_cancel(db, monkeypatch, timeline, discarded):
    """The outputter fails after the cancel landed: the output stays cancelled,
    with its words, and no ``failed`` goes out."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(db, monkeypatch, timeline, user, row, _cancel_lands(timeline), _fails("The outline failed."))

    assert result.status == OutputStatus.CANCELLED.value
    assert _published_after(timeline, "CANCEL") == []
    done = _fresh(db, row.id)
    assert (done.status, done.error_message, done.progress_message) == ("cancelled", None, CANCELLED_WORDS)
    assert discarded == [row.id]


def _check_another_delivery_that_completed_it_is_left_alone(db, monkeypatch, timeline, discarded):
    """Another delivery of the task completed the output while this one ran:
    this run stops at its next report, leaving the end, the content and the
    files that delivery wrote, and publishes nothing after it."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(
        db, monkeypatch, timeline, user, row, _another_delivery_completes(timeline), _progress(40, "Chapter 1 of 1"),
        _content("# mine"),
    )

    assert result.status == OutputStatus.COMPLETED.value
    assert _published_after(timeline, "COMPLETED ELSEWHERE") == []
    done = _fresh(db, row.id)
    assert (done.status, done.content_text) == ("completed", "theirs")
    assert discarded == []


def _check_a_refused_report_commits_none_of_this_runs_content(db, monkeypatch, timeline, discarded):
    """Another delivery completed the output; this run set its own text and
    citations and then reported progress. The refused report rolls them back:
    the row keeps the other delivery's text, and no citation of this run's."""
    user = _user(db)
    row = _row(db, user)
    _generate(
        db, monkeypatch, timeline, user, row, _another_delivery_completes(timeline), _content("# mine"),
        _cites("mine"), _progress(40, "Chapter 1 of 1"),
    )

    done = _fresh(db, row.id)
    assert (done.status, done.content_text) == ("completed", "theirs")
    assert _citations(db, row.id) == 0
    assert discarded == []


def _check_a_cancel_after_the_book_commits_its_manuscript(db, monkeypatch, timeline, discarded):
    """A cancel lands while the book's PDF prints, after its last progress
    report, which committed the manuscript, its citations and the EPUB's path.
    The cancel here is a bare write of the status, so the run's own clear is
    what is tested: the output ends cancelled with no text, file or citation,
    and its files removed, though ``completed`` found nothing to roll back."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(
        db, monkeypatch, timeline, user, row, *_book_up_to_its_pdf(), _cancel_lands(timeline), _file("pdf"),
    )

    assert result.status == OutputStatus.CANCELLED.value
    assert _published_after(timeline, "CANCEL") == []
    assert _fresh(db, row.id).progress_message == CANCELLED_WORDS
    assert _leftovers(db, row.id) == (None, None, 0)
    assert discarded == [row.id]


def _check_the_cancel_clears_what_the_run_committed(db, monkeypatch, timeline, discarded):
    """The API's real cancel lands at the same point. Its own write clears the
    manuscript, the EPUB's path and the citations, so the cancelled output
    serves none of them while the PDF still prints (up to
    ``AUTHOR_PDF_TIMEOUT_SEC``), not only once the run notices."""
    user = _user(db)
    row = _row(db, user)
    seen_right_after_the_cancel: list = []

    def the_api_cancels(db_, output):
        other = TestingSessionLocal()
        try:
            with patch.object(celery_app.control, "revoke"):
                assert output_service.cancel_output(other, user.id, output.id).status == "cancelled"
        finally:
            other.close()
        timeline.append(("CANCEL",))
        look = TestingSessionLocal()
        try:
            seen = look.get(Output, output.id)
            cited = look.query(OutputCitation).filter(OutputCitation.output_id == output.id).count()
            seen_right_after_the_cancel.append((seen.status, seen.content_text, seen.content_path, cited))
        finally:
            look.close()

    result = _generate(db, monkeypatch, timeline, user, row, *_book_up_to_its_pdf(), the_api_cancels, _file("pdf"))

    assert seen_right_after_the_cancel == [("cancelled", None, None, 0)]
    assert result.status == OutputStatus.CANCELLED.value
    assert _leftovers(db, row.id) == (None, None, 0)
    assert discarded == [row.id]


def _raises(kind: str):
    def step(db, output):
        if kind == "failed":
            raise OutputError("The PDF could not be printed.")
        if kind == "skipped":
            raise output_service.OutputSkipped("Nothing new since the last issue.")
        raise RuntimeError("the renderer crashed")
    return step


def _check_an_end_after_the_book_commits_its_manuscript(db, monkeypatch, timeline, discarded, kind: str):
    """The PDF fails after the book's last report committed its manuscript,
    citations and EPUB path (or the run skips, or crashes, there). The end's
    own write clears them, so the row never reads ended with them, and the
    end goes out after that commit."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(db, monkeypatch, timeline, user, row, *_book_up_to_its_pdf(), _raises(kind))

    end = "skipped" if kind == "skipped" else "failed"
    assert result.status == end
    assert _statuses_published(timeline) == ["generating", end]
    assert _each_publish_follows_its_commit(timeline)
    assert _leftovers(db, row.id) == (None, None, 0)
    assert discarded == [row.id]


def _check_another_delivery_that_failed_it_keeps_nothing(db, monkeypatch, timeline, discarded, when: str):
    """Another delivery of the task failed the output after this run's reports
    committed the manuscript. This run then writes a file into the shared
    folder, either before its next report (which stops it) or after its last
    one (its ``completed`` is refused). The failed row keeps the other
    delivery's end and words, and no text, citation or file: the folder is
    removed, this run's file included, not left on a failed row."""
    user = _user(db)
    row = _row(db, user)
    if when == "before-a-report":
        steps = (*_book_up_to_its_pdf()[:4], _file("epub"), _another_delivery_fails(timeline),
                 _progress(95, "Printing the PDF"))
    else:
        steps = (*_book_up_to_its_pdf(), _another_delivery_fails(timeline), _file("pdf"))
    result = _generate(db, monkeypatch, timeline, user, row, *steps)

    assert result.status == OutputStatus.FAILED.value
    assert _published_after(timeline, "FAILED ELSEWHERE") == []
    done = _fresh(db, row.id)
    assert (done.error_message, done.progress_message) == ("Their PDF failed.", "Failed")
    assert _leftovers(db, row.id) == (None, None, 0)
    assert discarded == [row.id]


# ================================================================ the checks: the cancel route


def _check_a_cancel_that_takes(client, db, timeline):
    """One status change to ``cancelled``, after the commit of its write and
    before the revoke; the row cancelled."""
    user = _user(db)
    row = _row(db, user, OutputStatus.GENERATING.value)
    response, revoked = _cancel(client, timeline, user, row.id, revoke=lambda *a, **k: timeline.append(("REVOKE",)))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    published = _publishes(timeline)
    assert len(published) == 1
    _, channel, payload = published[0]
    assert channel == f"job_progress:{row.id}"
    assert (payload["type"], payload["new_status"], payload["message"]) == ("job_status_change", "cancelled", CANCELLED_WORDS)
    assert _each_publish_follows_its_commit(timeline)
    assert timeline.index(published[0]) < timeline.index(("REVOKE",))
    revoked.assert_called_once_with("gen-task-id", terminate=True)
    assert _fresh(db, row.id).status == "cancelled"


def _the_output_ends_first(monkeypatch, timeline, end: str, **values) -> None:
    """The output ends between the cancel's read and its write."""
    real = output_service._write_unless_ended

    def ended_then_written(db_, output, values_, **kwargs):
        _elsewhere(timeline, output.id, "ENDED", status=end, **values)
        return real(db_, output, values_, **kwargs)

    monkeypatch.setattr(output_service, "_write_unless_ended", ended_then_written)


def _check_a_cancel_that_loses(client, db, timeline, monkeypatch, end: str):
    """The output finished between the route's read and its write: it keeps its
    end, the answer is 400 with that end, nothing is revoked, and no page is
    told of a cancel that did not happen."""
    user = _user(db)
    row = _row(db, user, OutputStatus.GENERATING.value)
    _the_output_ends_first(monkeypatch, timeline, end, content_text="# B")
    response, revoked = _cancel(client, timeline, user, row.id)

    assert response.status_code == 400
    assert end in response.json()["detail"]
    assert _publishes(timeline) == []
    revoked.assert_not_called()
    done = _fresh(db, row.id)
    assert (done.status, done.content_text) == (end, "# B")


def _check_a_cancel_that_finds_it_cancelled(client, db, timeline, monkeypatch):
    """Another cancel's write landed between this one's read and its write: the
    answer is the cancelled row, as before, and nothing is published."""
    user = _user(db)
    row = _row(db, user, OutputStatus.GENERATING.value)
    _the_output_ends_first(monkeypatch, timeline, OutputStatus.CANCELLED.value, progress_message=CANCELLED_WORDS)
    response, _ = _cancel(client, timeline, user, row.id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert _publishes(timeline) == []


# ================================================================ the checks: the create route


def _check_queued_never_lands_on_an_output_that_ended(client, db, timeline, monkeypatch):
    """The worker takes the task and fails the output before the route records
    the dispatch: the route keeps the task's id and writes no ``Queued`` over
    the failed row's words."""
    user = _user(db)
    job = Job(id="job-for-the-book", job_type="topic", status="completed", topic="T", tenant_id=user.id)
    db.add(job)
    db.commit()

    def the_worker_is_faster(task, user_, output_id, **kwargs):
        _elsewhere(
            timeline, output_id, "FAILED BY THE WORKER", status=OutputStatus.FAILED.value,
            error_message="No chapters.", progress_message="Failed",
        )
        return MagicMock(id="gen-task-id")

    monkeypatch.setattr(task_routing_service, "dispatch_for_user", the_worker_is_faster)
    token, _ = auth_service.create_access_token(user.id)
    response = client.post(
        "/api/v1/author/outputs",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "book", "title": "B", "source_ids": [job.id], "parameters": {"include_qa": False}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["progress_message"], body["celery_task_id"]) == ("failed", "Failed", "gen-task-id")
    done = _fresh(db, body["id"])
    assert (done.status, done.progress_message, done.celery_task_id) == ("failed", "Failed", "gen-task-id")


# ================================================================ the worker


def test_a_run_that_completes_publishes_each_event_after_its_commit(db, monkeypatch, timeline, discarded):
    _check_a_run_that_completes(db, monkeypatch, timeline, discarded)


def test_a_cancel_after_the_last_report_wins_over_completed(db, monkeypatch, timeline, discarded):
    _check_a_cancel_after_the_last_report_wins(db, monkeypatch, timeline, discarded)


def test_a_cancel_before_a_progress_report_stops_the_run_unpublished(db, monkeypatch, timeline, discarded):
    _check_a_cancel_before_a_report_stops_it(db, monkeypatch, timeline, discarded)


def test_a_failure_after_a_cancel_keeps_the_cancel(db, monkeypatch, timeline, discarded):
    _check_a_failure_after_a_cancel_keeps_the_cancel(db, monkeypatch, timeline, discarded)


def test_another_delivery_that_completed_the_output_is_left_alone(db, monkeypatch, timeline, discarded):
    _check_another_delivery_that_completed_it_is_left_alone(db, monkeypatch, timeline, discarded)


@pytest.mark.parametrize("end", ["cancelled", "completed", "failed", "skipped"])
def test_an_output_that_ended_before_the_run_starts_is_left_alone(db, monkeypatch, timeline, discarded, end):
    """Not even the 5 % goes out, and the output keeps what it had."""
    user = _user(db)
    row = _row(db, user, end)
    row.content_text = "kept"
    db.commit()
    result = _generate(db, monkeypatch, timeline, user, row, _content("# mine"))

    assert result.status == end
    assert _publishes(timeline) == []
    assert _fresh(db, row.id).content_text == "kept"
    assert discarded == []


def test_a_skipped_run_publishes_its_end_after_its_commit(db, monkeypatch, timeline, discarded):
    user = _user(db)
    row = _row(db, user)

    def nothing_new(db_, output):
        raise output_service.OutputSkipped("Nothing new since the last issue.")

    result = _generate(db, monkeypatch, timeline, user, row, nothing_new)

    assert result.status == OutputStatus.SKIPPED.value
    assert _statuses_published(timeline) == ["generating", "skipped"]
    assert _each_publish_follows_its_commit(timeline)
    assert discarded == [row.id]


def test_a_failed_run_publishes_its_end_after_its_commit(db, monkeypatch, timeline, discarded):
    user = _user(db)
    row = _row(db, user)
    result = _generate(db, monkeypatch, timeline, user, row, _fails("The outline failed."))

    assert result.status == OutputStatus.FAILED.value
    assert _statuses_published(timeline) == ["generating", "failed"]
    assert _each_publish_follows_its_commit(timeline)
    assert _fresh(db, row.id).error_message == "The outline failed."
    assert discarded == [row.id]


def test_a_refused_report_commits_none_of_this_runs_content(db, monkeypatch, timeline, discarded):
    _check_a_refused_report_commits_none_of_this_runs_content(db, monkeypatch, timeline, discarded)


def test_a_cancel_after_the_book_commits_its_manuscript_leaves_nothing(db, monkeypatch, timeline, discarded):
    _check_a_cancel_after_the_book_commits_its_manuscript(db, monkeypatch, timeline, discarded)


def test_the_cancel_clears_what_the_run_committed_at_once(db, monkeypatch, timeline, discarded):
    _check_the_cancel_clears_what_the_run_committed(db, monkeypatch, timeline, discarded)


@pytest.mark.parametrize("kind", ["failed", "skipped", "crashed"])
def test_an_end_after_the_book_commits_its_manuscript_leaves_nothing(db, monkeypatch, timeline, discarded, kind):
    _check_an_end_after_the_book_commits_its_manuscript(db, monkeypatch, timeline, discarded, kind)


@pytest.mark.parametrize("when", ["before-a-report", "after-the-last-report"])
def test_another_delivery_that_failed_the_output_leaves_it_nothing(db, monkeypatch, timeline, discarded, when):
    _check_another_delivery_that_failed_it_keeps_nothing(db, monkeypatch, timeline, discarded, when)


def test_a_completed_output_keeps_its_citations_and_files(db, monkeypatch, timeline, discarded):
    """The book's order, run to the end: nothing is cleared or removed."""
    user = _user(db)
    row = _row(db, user)
    result = _generate(db, monkeypatch, timeline, user, row, *_book_up_to_its_pdf(), _file("pdf"))

    assert result.status == OutputStatus.COMPLETED.value
    assert _leftovers(db, row.id) == ("# B", f"{user.id}/{row.id}/artifact.pdf", 2)
    assert discarded == []


# ================================================================ the create route


def test_queued_never_lands_on_an_output_that_ended(client, db, timeline, monkeypatch):
    _check_queued_never_lands_on_an_output_that_ended(client, db, timeline, monkeypatch)


# ================================================================ the cancel route


def test_a_cancel_that_takes_publishes_once_committed_and_before_the_revoke(client, db, timeline):
    _check_a_cancel_that_takes(client, db, timeline)


@pytest.mark.parametrize("end", ["completed", "failed", "skipped"])
def test_a_cancel_that_loses_the_race_publishes_nothing(client, db, timeline, monkeypatch, end):
    _check_a_cancel_that_loses(client, db, timeline, monkeypatch, end)


def test_a_cancel_that_finds_the_output_cancelled_publishes_nothing(client, db, timeline, monkeypatch):
    _check_a_cancel_that_finds_it_cancelled(client, db, timeline, monkeypatch)


def test_a_cancel_of_an_ended_output_is_400_and_publishes_nothing(client, db, timeline):
    user = _user(db)
    row = _row(db, user, OutputStatus.COMPLETED.value)
    response, revoked = _cancel(client, timeline, user, row.id)

    assert response.status_code == 400
    assert _publishes(timeline) == []
    revoked.assert_not_called()


def test_the_task_does_not_fail_an_ended_output_whose_owner_is_gone(db, timeline):
    """``generate_output``'s missing-owner write is conditional too."""
    from app.tasks import output_tasks

    row = output_service.create_output(db, user_id="ghost-user", kind="book", title="B", source_ids=["j"])
    row.status = OutputStatus.CANCELLED.value
    db.commit()
    with patch.object(output_tasks, "SessionLocal", TestingSessionLocal):
        assert output_tasks.generate_output.run(row.id) == "cancelled"
    assert _publishes(timeline) == []


# ================================================================ mutation checks on the real code

_CONDITION = ".filter(Output.id == output.id, Output.status.notin_(TERMINAL_STATUSES))"
_NO_CONDITION = ".filter(Output.id == output.id)"
_ROLLBACK_ON_REFUSAL = "    if written != 1:\n        db.rollback()\n"
_COMMIT_ON_REFUSAL = "    if written != 1:\n        db.commit()\n"
_PUBLISH_LAST = (
    "    _publish_status(output.id, old, output.status, output.progress_message or output.status)\n    return True\n"
)
_STATUS_WRITE = "    if not _write_unless_ended(db, output, values, drop_content=drop_content):\n        logger.info(\n"
_PUBLISH_FIRST = (
    "    _publish_status(output.id, old, values['status'], values.get('progress_message') or values['status'])\n"
)
_PROGRESS_WRITE = "    if not _write_unless_ended(db, output, values):\n        if output.status =="
_PROGRESS_PUBLISHED_FIRST = (
    "    from app.services import progress_service as _ps\n"
    "    _ps.publish_progress(output.id, output.status, values['progress_pct'], values['progress_message'])\n"
)
_CANCEL_WRITE = (
    '    transition_to(db, row, OutputStatus.CANCELLED, progress_message="Cancelled by user", drop_content=True)\n'
)
_CANCEL_KEEPS_CONTENT = '    transition_to(db, row, OutputStatus.CANCELLED, progress_message="Cancelled by user")\n'
_END_DROPS_CONTENT = "    if transition_to(db, output, status, drop_content=True, **fields):\n"
_END_KEEPS_CONTENT = "    if transition_to(db, output, status, **fields):\n"
_REFUSED_COMPLETE_CLEARS = (
    '    if not transition_to(db, output, OutputStatus.COMPLETED, progress_message="Done"):\n'
    "        _clear_unfinished(db, output)\n"
)
_REFUSED_COMPLETE_DISCARDS_ON_CANCEL = (
    '    if not transition_to(db, output, OutputStatus.COMPLETED, progress_message="Done"):\n'
    "        if output.status == OutputStatus.CANCELLED.value:\n"
    "            _discard_artifacts(output)\n"
)
_QUEUED_ONLY_WHILE_PENDING = (
    "    db.query(Output).filter(Output.id == output.id, Output.status == OutputStatus.PENDING.value).update(\n"
)
_QUEUED_WHATEVER_THE_STATUS = "    db.query(Output).filter(Output.id == output.id).update(\n"
_REVOKE_FIRST = (
    "    from app.tasks.celery_app import celery_app\n"
    "    celery_app.control.revoke(row.celery_task_id, terminate=True)\n"
)


def _unconditional_writes(monkeypatch):
    """The writes as they were: whatever the row's status."""
    mutant(monkeypatch, output_service._write_unless_ended, (_CONDITION, _NO_CONDITION))


@pytest.mark.parametrize(
    "check",
    [
        _check_a_cancel_after_the_last_report_wins,
        _check_a_cancel_before_a_report_stops_it,
        _check_a_failure_after_a_cancel_keeps_the_cancel,
        _check_another_delivery_that_completed_it_is_left_alone,
    ],
    ids=["cancel-then-complete", "cancel-then-report", "cancel-then-fail", "completed-elsewhere"],
)
def test_mutation_unconditional_writes_fail_each_worker_check(db, monkeypatch, timeline, discarded, check):
    _unconditional_writes(monkeypatch)
    with pytest.raises(AssertionError):
        check(db, monkeypatch, timeline, discarded)


def test_mutation_unconditional_writes_fail_the_lose_check(client, db, timeline, monkeypatch):
    _unconditional_writes(monkeypatch)
    with pytest.raises(AssertionError):
        _check_a_cancel_that_loses(client, db, timeline, monkeypatch, "completed")


def test_mutation_unconditional_writes_fail_the_found_cancelled_check(client, db, timeline, monkeypatch):
    _unconditional_writes(monkeypatch)
    with pytest.raises(AssertionError):
        _check_a_cancel_that_finds_it_cancelled(client, db, timeline, monkeypatch)


def test_mutation_a_refused_write_that_commits_fails_the_refused_report_check(db, monkeypatch, timeline, discarded):
    """Committing the run's pending changes when its write is refused puts this
    run's text over the output another delivery completed. (On a cancelled
    output the clear that follows the refusal now removes them, so the
    cancel-after-the-last-report check no longer sees this.)"""
    mutant(monkeypatch, output_service._write_unless_ended, (_ROLLBACK_ON_REFUSAL, _COMMIT_ON_REFUSAL))
    with pytest.raises(AssertionError):
        _check_a_refused_report_commits_none_of_this_runs_content(db, monkeypatch, timeline, discarded)


def _status_published_before_its_write(monkeypatch):
    """``transition_to`` publishing first, then writing: a page reads the end
    before the row says it, and an end that is then refused goes out anyway."""
    mutant(
        monkeypatch,
        output_service.transition_to,
        (_PUBLISH_LAST, "    return True\n"),
        (_STATUS_WRITE, _PUBLISH_FIRST + _STATUS_WRITE),
    )


def test_mutation_a_status_published_before_its_write_fails_the_take_check(client, db, timeline, monkeypatch):
    _status_published_before_its_write(monkeypatch)
    with pytest.raises(AssertionError):
        _check_a_cancel_that_takes(client, db, timeline)


def test_mutation_a_status_published_before_its_write_fails_the_lose_check(client, db, timeline, monkeypatch):
    _status_published_before_its_write(monkeypatch)
    with pytest.raises(AssertionError):
        _check_a_cancel_that_loses(client, db, timeline, monkeypatch, "completed")


def test_mutation_progress_published_before_its_write_fails_the_report_check(db, monkeypatch, timeline, discarded):
    """``report_progress`` publishing what it is about to write before writing
    it: the line goes out after the cancel."""
    mutant(
        monkeypatch,
        output_service.report_progress,
        (_PROGRESS_WRITE, _PROGRESS_PUBLISHED_FIRST + _PROGRESS_WRITE),
    )
    with pytest.raises(AssertionError):
        _check_a_cancel_before_a_report_stops_it(db, monkeypatch, timeline, discarded)


def test_mutation_a_cancel_that_revokes_first_fails_the_lose_check(client, db, timeline, monkeypatch):
    """The revoke before the write, as it was: a cancel that loses the race
    terminates a task that is closing a finished output."""
    mutant(monkeypatch, output_service.cancel_output, (_CANCEL_WRITE, _REVOKE_FIRST + _CANCEL_WRITE))
    with pytest.raises(AssertionError):
        _check_a_cancel_that_loses(client, db, timeline, monkeypatch, "completed")


# ---------------------------------------------------------------- what an output that did not complete keeps

_STOPPED_CLEARS = "        _clear_unfinished(db, output)\n        return output\n    except OutputSkipped"
_STOPPED_LEAVES = "        return output\n    except OutputSkipped"


def test_mutation_a_cancel_that_keeps_the_content_fails_the_cancel_clears_check(db, monkeypatch, timeline, discarded):
    """The cancel's write leaving the content, as it did: the cancelled output
    serves the manuscript until the run notices, which can be minutes."""
    mutant(monkeypatch, output_service.cancel_output, (_CANCEL_WRITE, _CANCEL_KEEPS_CONTENT))
    with pytest.raises(AssertionError):
        _check_the_cancel_clears_what_the_run_committed(db, monkeypatch, timeline, discarded)


@pytest.mark.parametrize("kind", ["failed", "skipped", "crashed"])
def test_mutation_an_end_that_keeps_the_content_fails_the_end_check(db, monkeypatch, timeline, discarded, kind):
    """The run's own failed or skipped write leaving what its reports committed."""
    mutant(monkeypatch, output_service._end_unfinished, (_END_DROPS_CONTENT, _END_KEEPS_CONTENT))
    with pytest.raises(AssertionError):
        _check_an_end_after_the_book_commits_its_manuscript(db, monkeypatch, timeline, discarded, kind)


def test_mutation_a_refused_completed_that_only_discards_on_a_cancel_fails_the_book_cancel_check(
    db, monkeypatch, timeline, discarded
):
    """The refused ``completed`` as the PR first had it: files removed on a
    cancel, the committed manuscript and citations left on the cancelled row."""
    mutant(monkeypatch, output_service._run_generation, (_REFUSED_COMPLETE_CLEARS, _REFUSED_COMPLETE_DISCARDS_ON_CANCEL))
    with pytest.raises(AssertionError):
        _check_a_cancel_after_the_book_commits_its_manuscript(db, monkeypatch, timeline, discarded)


def test_mutation_a_refused_completed_that_only_discards_on_a_cancel_fails_the_failed_elsewhere_check(
    db, monkeypatch, timeline, discarded
):
    """The same, after another delivery failed the output: this run's PDF and
    the manuscript stay on the failed row."""
    mutant(monkeypatch, output_service._run_generation, (_REFUSED_COMPLETE_CLEARS, _REFUSED_COMPLETE_DISCARDS_ON_CANCEL))
    with pytest.raises(AssertionError):
        _check_another_delivery_that_failed_it_keeps_nothing(db, monkeypatch, timeline, discarded, "after-the-last-report")


def test_mutation_a_stopped_run_that_clears_nothing_fails_the_failed_elsewhere_check(
    db, monkeypatch, timeline, discarded
):
    """A run stopped by a refused report leaving the failed row as it found
    it: the manuscript its reports committed, and the EPUB it wrote."""
    mutant(monkeypatch, output_service._run_generation, (_STOPPED_CLEARS, _STOPPED_LEAVES))
    with pytest.raises(AssertionError):
        _check_another_delivery_that_failed_it_keeps_nothing(db, monkeypatch, timeline, discarded, "before-a-report")


def test_mutation_queued_written_whatever_the_status_fails_the_create_check(client, db, timeline, monkeypatch):
    """``Queued`` written as it was, over whatever the worker had written."""
    mutant(monkeypatch, output_service.record_queued, (_QUEUED_ONLY_WHILE_PENDING, _QUEUED_WHATEVER_THE_STATUS))
    with pytest.raises(AssertionError):
        _check_queued_never_lands_on_an_output_that_ended(client, db, timeline, monkeypatch)

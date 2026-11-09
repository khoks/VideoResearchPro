"""T-5.2.20: a cancelled run stays cancelled, and a failed run is never written over.
T-8.8.6.12: the subscription sync picks its documents by ``document_id``.

Two edges T-5.2.18 left:

* A cancelled run whose task was delivered anyway came back. ``POST
  /jobs/{id}/cancel`` writes ``cancelled`` and revokes the task, but a revoke
  reaches only the workers alive at that moment and lives in their memory, and
  each entry point wrote ``searching`` or ``extracting`` before it read the
  row. The start guard (``_already_stopped``) now reads ``cancelled`` beside
  ``failed``, before the usage scope opens.
* A worker that picked a task up before the route marked the row failed (a
  dispatch whose reply was lost after a fast pickup) ran on and wrote over
  ``failed`` at its next status change. Every status write a run makes is now
  one conditional ``UPDATE ... WHERE status NOT IN ('failed', 'cancelled')``
  (``_write_unless_stopped``): a refused one raises ``_RunStopped``, which each
  entry point catches before its ``except Exception``, so neither
  ``_handle_failure`` nor the publish after the write runs. The per-item and
  per-phase checks (``_is_stopped``) read ``failed`` beside ``cancelled``, so
  a run stops at its next check. Progress writes go through the same
  condition and are published only when written; ``_handle_failure`` and the
  orphan backstop are conditional too; and ``PUT /jobs/{id}/approve``, which
  writes ``extracting`` after it has queued the resume, writes it only over
  ``awaiting_approval``.

From the review: the topic search stops where a stop lands. A refused
progress write ends the search agent (``SearchStopped``), a check after the
agent stops the run before it keeps anything or fetches a non-video post (each
fetch classifies inline, D-023, model calls charged to the owner), the 'Found
N videos' progress is a guarded write, and each post is committed and checked
before the next fetch. And a document is flagged ``embedded_in_chroma`` only
once its chunks are in Chroma, so a stopped run leaves nothing flagged without
its chunks.

Every case runs the real task, with the test database, an in-memory Chroma and
fakes for every connector, the search agent, the era call and the report: no
network and no model.

Mutation checks, one per mechanism, each beside the case it breaks:
``_already_stopped`` answering False opens the usage scope; ``_is_stopped``
reading ``cancelled`` alone fetches the next document; an unconditional
``_write_unless_stopped`` (the write before this change) turns the row back;
``update_job_status`` without ``only_from`` covers the resume's failure; and
the subscription sync joined on ``video_id`` picks the wrong documents;
without the check after the search its pool is kept, and without any stop it
fetches every post; an unguarded 'Found' write publishes after the cancel;
without the per-candidate check every post is fetched; and a flag set as each
document is chunked strands it for every later job.
"""
from __future__ import annotations

import json
import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_search_candidate import JobSearchCandidate
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.agents.search_agent import SearchStopped
from app.models.usage_record import UsageRecord
from app.routers.jobs import _NOT_QUEUED
from app.services import chroma_service, job_service, temporal_service
from app.services.connector_dispatch import DispatchResult
from app.sources.types import Candidate, CreatorMetadata, ExtractedText
from app.tasks import job_tasks
from app.tasks.celery_app import celery_app

# The real tasks, kept before any test patches the module's names.
REAL_TASKS = {
    "execute_topic_job": job_tasks.execute_topic_job,
    "execute_channel_job": job_tasks.execute_channel_job,
    "resume_job_after_approval": job_tasks.resume_job_after_approval,
    "execute_subscription_job": job_tasks.execute_subscription_job,
}
CHANNEL = "UCstoppedRun0001"
BODIES = {
    "topic": {"job_type": "topic", "topic": "tariffs"},
    "channel": {"job_type": "channel", "channel_list": [CHANNEL]},
    "subscription": {"job_type": "subscription", "channel_list": [CHANNEL]},
}
TASK_FOR = {"topic": "execute_topic_job", "channel": "execute_channel_job", "subscription": "execute_subscription_job"}
CANCELLED_WORDS = "Job cancelled by user"  # what POST /jobs/{id}/cancel writes
SYNC_NOT_QUEUED = "The sync could not be queued."  # what _dispatch_subscription_sync writes
SEGMENTS = [
    {"text": f"The railways reshaped the subcontinent and its trade routes, part {i}.",
     "start": float(i * 5), "duration": 5.0}
    for i in range(6)
]


class _FakeConnector:
    """Every connector call a run can make, recorded and answered offline."""

    def __init__(self):
        self.calls: list[str] = []
        self.fetched: list[str] = []
        self.on_fetch = None  # called with the source id before answering

    def resolve_creator_id(self, value, job_id=""):
        self.calls.append("resolve_creator_id")
        return CHANNEL

    def fetch_creator(self, creator_id, job_id=""):
        self.calls.append("fetch_creator")
        return CreatorMetadata(creator_external_id=creator_id, name="Stopped Channel",
                               extra={"uploads_playlist_id": "UUstoppedRun0001"})

    def list_creator_items(self, creator_id, limit=10, job_id=""):
        self.calls.append("list_creator_items")
        return []

    def fetch_metadata(self, ids, job_id=""):
        self.calls.append("fetch_metadata")
        return {}

    def fetch_text(self, candidate, **kwargs):
        self.calls.append("fetch_text")
        self.fetched.append(candidate.source_id)
        if self.on_fetch is not None:
            self.on_fetch(candidate.source_id)
        return ExtractedText(segments=SEGMENTS, language="en", text_source="youtube",
                             word_count=60)


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def worker(monkeypatch, db, ephemeral_chroma, tmp_path):
    """The task module on the test session, with every way out of a run faked
    or recorded: progress published, the usage scope, the connectors, the
    YouTube uploads listing, the search agent, the era call and the report."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    progress = MagicMock()
    monkeypatch.setattr(job_tasks, "progress_service", progress)
    monkeypatch.setattr("app.services.progress_service.publish_error", progress.publish_error)
    metered = MagicMock(return_value=nullcontext())
    monkeypatch.setattr(job_tasks.usage_service, "metered", metered)
    connector = _FakeConnector()
    monkeypatch.setattr(job_tasks, "connector_for", lambda source_type: connector)
    uploads = MagicMock(return_value=[])
    monkeypatch.setattr(job_tasks.youtube_service, "get_channel_videos_all", uploads)
    search = MagicMock(return_value=([], [], []))
    monkeypatch.setattr("app.agents.search_agent.run_search_agent", search)
    monkeypatch.setattr(temporal_service, "extract_discussed_era", lambda *a, **k: None)
    report = MagicMock(return_value=({}, "<p>report</p>"))
    monkeypatch.setattr("app.agents.report_agent.run_report_agent", report)
    monkeypatch.setattr(job_tasks, "build_report_html", lambda **kwargs: "<html>report</html>")
    monkeypatch.setattr(job_tasks.settings, "REPORTS_DIR", str(tmp_path / "reports"))
    return SimpleNamespace(progress=progress, metered=metered, connector=connector,
                           uploads=uploads, search=search, report=report)


def _snapshot(db, job_id: str) -> dict:
    db.expire_all()
    job = db.get(Job, job_id)
    return {
        "status": job.status,
        "error_message": job.error_message,
        "progress_message": job.progress_message,
        "progress_pct": job.progress_pct,
        "celery_task_id": job.celery_task_id,
        "report_path": job.report_path,
        "updated_at": job.updated_at,
    }


def _status_changes(worker) -> list[str]:
    return [c.args[2] for c in worker.progress.publish_status_change.call_args_list]


def _route_fails(db, job_id: str, words: str, *, progress_message: str | None = "Failed") -> None:
    """What ``POST /jobs`` (or Sync now, with ``progress_message=None``)
    writes when its dispatch raised: the broker took the message, the reply
    was lost, and the worker had already picked the task up."""
    db.expire_all()
    job = db.get(Job, job_id)
    job.status = "failed"
    job.error_message = words
    if progress_message is not None:
        job.progress_message = progress_message
    db.commit()


def _cancel(client, job_id: str) -> MagicMock:
    """The real cancel route, with a revoke that reaches no live worker (or,
    on a solo pool, cannot stop the task it reaches). Returns the revoke."""
    with patch.object(celery_app.control, "revoke") as revoke:
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    return revoke


def _unguarded_write(db, job, **fields) -> bool:
    """``_write_unless_stopped`` as every run wrote before T-5.2.20: whatever
    the row says. The mutation the cases below must catch."""
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return True


def _video(db, video_id: str, **extra) -> Document:
    doc = Document(video_id=video_id, source_type="video", source_id=video_id,
                   title=f"Video {video_id}", url=f"https://www.youtube.com/watch?v={video_id}", **extra)
    db.add(doc)
    db.flush()
    return doc


def _job_with_videos(db, tenant_id: str, video_ids: list[str], *, status: str = "extracting",
                     job_type: str = "topic") -> str:
    job = Job(job_type=job_type, topic="tariffs", status=status, tenant_id=tenant_id,
              channel_list=f'["{CHANNEL}"]')
    db.add(job)
    db.flush()
    for video_id in video_ids:
        doc = _video(db, video_id)
        db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=video_id, approved=True))
    db.commit()
    return job.id


# ---------------------------------------------------------------- first edge: a cancelled run is delivered


def _assert_did_nothing(db, worker, job_id: str, before: dict) -> None:
    assert _snapshot(db, job_id) == before, "the cancelled row was left exactly as the route wrote it"
    assert worker.progress.mock_calls == [], "a skipped task publishes nothing"
    worker.metered.assert_not_called()
    assert db.query(UsageRecord).count() == 0, "a skipped task charges nothing"
    assert worker.connector.calls == []
    worker.search.assert_not_called()
    worker.uploads.assert_not_called()


@pytest.mark.parametrize("job_type", sorted(BODIES))
def test_a_cancelled_run_whose_task_is_delivered_does_nothing(client, db, worker, job_type):
    """``POST /jobs`` queued it, ``POST /jobs/{id}/cancel`` cancelled it and
    revoked the task, and the revoke reached no live worker: the queued task
    is delivered later anyway."""
    response = client.post("/api/v1/jobs", json=BODIES[job_type])
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    _cancel(client, job_id).assert_called_once_with(f"mock-{job_type}-task-id", terminate=True)
    before = _snapshot(db, job_id)
    assert before["status"] == "cancelled"
    assert before["progress_message"] == CANCELLED_WORDS

    REAL_TASKS[TASK_FOR[job_type]].run(job_id)

    _assert_did_nothing(db, worker, job_id, before)


def test_a_cancelled_sync_whose_task_is_delivered_does_nothing(client, db, worker):
    """Sync now queued it and the user cancelled it from its job page."""
    db.add(Channel(channel_id=CHANNEL, name="Stopped Channel", uploads_playlist_id="UUstoppedRun0001"))
    db.commit()
    with patch("app.tasks.job_tasks.execute_subscription_job") as task:
        task.apply_async.return_value = MagicMock(id="sync-task-id")
        response = client.post(f"/api/v1/channels/{CHANNEL}/sync")
    job_id = response.json()["job_id"]
    assert job_id
    _cancel(client, job_id).assert_called_once_with("sync-task-id", terminate=True)
    before = _snapshot(db, job_id)
    assert before["status"] == "cancelled"

    REAL_TASKS["execute_subscription_job"].run(job_id)

    _assert_did_nothing(db, worker, job_id, before)


def test_a_cancelled_approval_whose_resume_is_delivered_does_nothing(client, db, worker, test_user):
    """Approved, then cancelled before the resume ran: no fetch, no status."""
    job_id = _job_with_videos(db, test_user.id, ["vApprove0001"], status="awaiting_approval")
    approved = client.put(f"/api/v1/jobs/{job_id}/approve", json={"approved_video_ids": ["vApprove0001"]})
    assert approved.status_code == 200, approved.text
    _cancel(client, job_id).assert_called_once_with("mock-resume-task-id", terminate=True)
    before = _snapshot(db, job_id)
    assert before["status"] == "cancelled"

    REAL_TASKS["resume_job_after_approval"].run(job_id)

    _assert_did_nothing(db, worker, job_id, before)


def test_mutation_without_the_start_guard_a_cancelled_run_opens_its_scope(client, db, worker, monkeypatch):
    """With ``_already_stopped`` answering False the usage scope opens, which
    the cases above forbid; the refused first write still keeps the row."""
    monkeypatch.setattr(job_tasks, "_already_stopped", lambda job, task: False)
    job_id = client.post("/api/v1/jobs", json=BODIES["topic"]).json()["id"]
    _cancel(client, job_id)
    before = _snapshot(db, job_id)

    REAL_TASKS["execute_topic_job"].run(job_id)

    assert worker.metered.called
    assert _snapshot(db, job_id) == before


# ---------------------------------------------------------------- second edge: failed after pickup


PICKED = {"video_id": "vPicked00001", "title": "Picked", "channel_id": CHANNEL,
          "channel_name": "Stopped Channel", "url": "https://www.youtube.com/watch?v=vPicked00001"}


def _picked_video_search(stop, raised: list[Exception] | None = None):
    """A search agent during which ``stop()`` lands, between two progress
    reports, and which then returns one video. What the second report raised
    goes to ``raised`` and on out, as ``run_search_agent`` lets
    ``SearchStopped`` through its ``_notify``."""
    def search(**kwargs):
        kwargs["progress_callback"](10, "Planning searches...")
        stop()
        try:
            kwargs["progress_callback"](12, "Ranking candidates...")
        except Exception as e:
            if raised is not None:
                raised.append(e)
            raise
        return ([dict(PICKED)], ["tariffs"], [])
    return search


def _topic_run_failed_mid_search(db, worker, raised: list[Exception] | None = None) -> str:
    job = Job(job_type="topic", topic="tariffs", status="pending", tenant_id="tenant-mid-search")
    db.add(job)
    db.commit()
    worker.search.side_effect = _picked_video_search(lambda: _route_fails(db, job.id, _NOT_QUEUED), raised)
    REAL_TASKS["execute_topic_job"].run(job.id)
    return job.id


def test_a_topic_run_failed_after_pickup_is_not_written_over(db, worker):
    """The worker wrote ``searching`` before the route's failure landed. The
    agent's next progress report is not written or published, and it raises
    ``SearchStopped``, which ends the search there (the agent's remaining
    nodes never run) and the run with it: nothing it found is kept, and the
    row keeps the route's words."""
    raised: list[Exception] = []
    job_id = _topic_run_failed_mid_search(db, worker, raised)

    row = _snapshot(db, job_id)
    assert (row["status"], row["error_message"], row["progress_message"]) == ("failed", _NOT_QUEUED, "Failed")
    assert _status_changes(worker) == ["searching"], "never awaiting_approval"
    reported = [c.args[3] for c in worker.progress.publish_progress.call_args_list if c.args[1] == "searching"]
    assert reported == ["Planning searches..."]
    assert [type(e) for e in raised] == [SearchStopped]
    assert db.query(Document).filter(Document.video_id == PICKED["video_id"]).count() == 0
    worker.progress.publish_error.assert_not_called()


def test_mutation_an_unguarded_write_takes_the_failed_topic_run_to_approval(db, worker, monkeypatch):
    """With the checks gone too, so that only the conditional write could
    have held the row."""
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)
    monkeypatch.setattr(job_tasks, "_is_stopped", lambda db_, job_id: False)

    job_id = _topic_run_failed_mid_search(db, worker)

    assert _snapshot(db, job_id)["status"] == "awaiting_approval"
    assert "awaiting_approval" in _status_changes(worker)


# ---------------------------------------------------------------- the topic search stops where a stop lands
#
# The search is the multi-minute part of a topic run, so a cancel most likely
# lands there. Every non-video candidate's fetch classifies inline (D-023),
# model calls charged to the run's owner, so a run stopped during the search
# must not reach them; and a progress event after the cancel would show the
# page searching again.


def _reddit(source_id: str) -> Candidate:
    return Candidate(source_type="reddit_post", source_id=source_id, title=f"Post {source_id}",
                     source_url=f"https://www.reddit.com/r/test/comments/{source_id}/")


def _topic_run_with_posts(client, db, worker, monkeypatch, test_user, source_types: list[str], *,
                          during_search=None, on_fetch=None) -> str:
    """A topic run over ``source_types`` whose Reddit search found two posts.
    ``during_search(job_id)`` lands while the (fake) YouTube search agent
    runs, after its last progress report, as during ``rank_and_curate``;
    ``on_fetch(job_id, source_id)`` during a post's fetch."""
    job = Job(job_type="topic", topic="tariffs", status="pending", tenant_id=test_user.id, num_videos=10,
              source_types_json=json.dumps(source_types))
    db.add(job)
    db.commit()
    if on_fetch is not None:
        worker.connector.on_fetch = lambda source_id: on_fetch(job.id, source_id)
    monkeypatch.setattr(job_tasks, "_search_non_video_sources", lambda job_, types, shares: DispatchResult(
        candidates_by_source_type={"reddit_post": [_reddit("t3_post01"), _reddit("t3_post02")]}))
    monkeypatch.setattr("app.sources.registry.connector_for", lambda source_type: worker.connector)

    def search(**kwargs):
        kwargs["progress_callback"](10, "Planning searches...")
        kwargs["candidates_out"].append(dict(PICKED))
        if during_search is not None:
            during_search(job.id)
        return ([dict(PICKED)], ["tariffs"], [])

    worker.search.side_effect = search
    REAL_TASKS["execute_topic_job"].run(job.id)
    return job.id


def _searching_reports(worker) -> list[str]:
    return [c.args[3] for c in worker.progress.publish_progress.call_args_list if c.args[1] == "searching"]


def test_a_topic_run_cancelled_during_its_search_fetches_nothing(client, db, worker, monkeypatch, test_user):
    """The agent finishes (its ranking reports no progress), the check after
    it stops the run: nothing it found is persisted, no post is fetched, and
    the page gets no event after the cancel."""
    job_id = _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["video", "reddit_post"],
                                   during_search=lambda job_id: _cancel(client, job_id))

    assert worker.connector.fetched == []
    assert _searching_reports(worker) == ["Planning searches..."]
    assert _status_changes(worker) == ["searching"]
    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"]) == ("cancelled", CANCELLED_WORDS)
    assert db.query(Document).filter(Document.video_id == PICKED["video_id"]).count() == 0
    assert db.query(JobVideo).filter(JobVideo.job_id == job_id).count() == 0
    assert db.query(JobSearchCandidate).filter(JobSearchCandidate.job_id == job_id).count() == 0


def test_mutation_without_the_check_after_the_search_its_pool_is_kept(client, db, worker, monkeypatch, test_user):
    """Only the check after the agent keeps a stopped run's candidate pool
    out of the database. (The guarded write after it still stops the
    fetches.)"""
    monkeypatch.setattr(job_tasks, "_is_stopped", lambda db_, job_id: False)

    job_id = _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["video", "reddit_post"],
                                   during_search=lambda job_id: _cancel(client, job_id))

    assert db.query(JobSearchCandidate).filter(JobSearchCandidate.job_id == job_id).count() == 1
    assert worker.connector.fetched == []


def test_mutation_without_any_stop_a_cancelled_search_fetches_every_post(client, db, worker, monkeypatch, test_user):
    """The run as the review found it: the search runs to its end and the
    run goes on through the 'Found' event to every post's fetch."""
    monkeypatch.setattr(job_tasks, "_is_stopped", lambda db_, job_id: False)
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)

    _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["video", "reddit_post"],
                          during_search=lambda job_id: _cancel(client, job_id))

    assert worker.connector.fetched == ["t3_post01", "t3_post02"]
    assert "Found 1 videos. Fetching details..." in _searching_reports(worker)


def _cancel_while_persisting(client, monkeypatch):
    """The cancel lands just after the check that follows the agent."""
    real = job_tasks._persist_search_candidates

    def cancel_then_persist(db_, job_id, pool, curated):
        _cancel(client, job_id)
        return real(db_, job_id, pool, curated)

    monkeypatch.setattr(job_tasks, "_persist_search_candidates", cancel_then_persist)


def test_a_cancel_after_the_check_stops_at_the_found_write(client, db, worker, monkeypatch, test_user):
    """The 'Found N videos' progress is written first and published only when
    it was, so a cancel that lands after the check still gets no event."""
    _cancel_while_persisting(client, monkeypatch)

    job_id = _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["video", "reddit_post"])

    assert _searching_reports(worker) == ["Planning searches..."]
    assert worker.connector.fetched == []
    assert (_snapshot(db, job_id)["status"]) == "cancelled"


def test_mutation_an_unguarded_found_write_publishes_searching_after_the_cancel(
    client, db, worker, monkeypatch, test_user
):
    """And the per-candidate check is what still keeps the posts unfetched."""
    _cancel_while_persisting(client, monkeypatch)
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)

    _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["video", "reddit_post"])

    assert "Found 1 videos. Fetching details..." in _searching_reports(worker)
    assert worker.connector.fetched == []


def _cancel_on_the_first_post(client):
    def on_fetch(job_id, source_id):
        if source_id == "t3_post01":
            _cancel(client, job_id)
    return on_fetch


def test_a_run_cancelled_during_a_fetch_fetches_no_further_post(client, db, worker, monkeypatch, test_user):
    """Each candidate is committed and the next one checked first: the post in
    hand finishes, the next is never fetched, and the run never reaches
    approval."""
    job_id = _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["reddit_post"],
                                   on_fetch=_cancel_on_the_first_post(client))

    assert worker.connector.fetched == ["t3_post01"]
    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"]) == ("cancelled", CANCELLED_WORDS)
    assert "awaiting_approval" not in _status_changes(worker)
    assert db.get(JobVideo, (job_id, _document_id(db, "t3_post01"))) is not None, "the post in hand was kept"


def test_mutation_without_the_per_candidate_check_every_post_is_fetched(client, db, worker, monkeypatch, test_user):
    """The approval write is still refused: the check saves the fetches."""
    monkeypatch.setattr(job_tasks, "_is_stopped", lambda db_, job_id: False)

    job_id = _topic_run_with_posts(client, db, worker, monkeypatch, test_user, ["reddit_post"],
                                   on_fetch=_cancel_on_the_first_post(client))

    assert worker.connector.fetched == ["t3_post01", "t3_post02"]
    assert _snapshot(db, job_id)["status"] == "cancelled"


def _document_id(db, source_id: str) -> str:
    return db.query(Document.document_id).filter(Document.source_id == source_id).scalar()


def _sync_failed_mid_walk(db, worker, tenant_id: str) -> str:
    """Sync now's dispatch raised after the broker took the message, and the
    worker had already started: the route's failure lands during the walk."""
    db.add(Channel(channel_id=CHANNEL, name="Stopped Channel", uploads_playlist_id="UUstoppedRun0001"))
    job = Job(job_type="subscription", status="pending", topic="Sync Stopped Channel",
              channel_list=json.dumps([CHANNEL]), num_videos=0, tenant_id=tenant_id)
    db.add(job)
    db.commit()

    def uploads(channel_id, job_id=None, uploads_playlist_id=None):
        _route_fails(db, job.id, SYNC_NOT_QUEUED, progress_message=None)
        return ["vSyncUpload1"]

    worker.uploads.side_effect = uploads
    REAL_TASKS["execute_subscription_job"].run(job.id)
    return job.id


def test_a_sync_failed_after_pickup_is_not_written_over(db, worker, test_user):
    job_id = _sync_failed_mid_walk(db, worker, test_user.id)

    row = _snapshot(db, job_id)
    assert (row["status"], row["error_message"]) == ("failed", SYNC_NOT_QUEUED)
    assert "fetch_text" not in worker.connector.calls, "extraction never started"
    assert set(_status_changes(worker)) == {"searching"}
    worker.progress.publish_error.assert_not_called()


def test_mutation_an_unguarded_write_completes_the_failed_sync(db, worker, monkeypatch, test_user):
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)

    job_id = _sync_failed_mid_walk(db, worker, test_user.id)

    assert _snapshot(db, job_id)["status"] == "completed"


def _resume_failed_mid_extraction(db, worker) -> str:
    job_id = _job_with_videos(db, "tenant-mid-extraction", ["vMidRun00001", "vMidRun00002"])

    def first_fetch_fails_the_row(source_id):
        if source_id == "vMidRun00001":
            _route_fails(db, job_id, "Stopped elsewhere.")

    worker.connector.on_fetch = first_fetch_fails_the_row
    REAL_TASKS["resume_job_after_approval"].run(job_id)
    return job_id


def test_a_row_failed_mid_extraction_stops_at_the_next_check(db, worker):
    """The video in hand finishes, its progress is neither written nor
    published, and the next video's check stops the run: no second fetch, no
    RAG build, no report, and the row keeps its words."""
    job_id = _resume_failed_mid_extraction(db, worker)

    assert worker.connector.fetched == ["vMidRun00001"]
    row = _snapshot(db, job_id)
    assert (row["status"], row["error_message"], row["progress_message"]) == ("failed", "Stopped elsewhere.", "Failed")
    assert _status_changes(worker) == ["extracting"]
    worker.progress.publish_progress.assert_not_called()
    worker.report.assert_not_called()
    worker.progress.publish_error.assert_not_called()


def test_mutation_a_check_that_reads_cancelled_alone_fetches_the_next_video(db, worker, monkeypatch):
    """``_is_stopped`` as it read before T-5.2.20: the run fetches the second
    video. Its ``building_rag`` write is still refused, so the row stays
    failed: the checks save the spend, the conditional write the row."""
    def cancelled_only(db_, job_id):
        db_.expire_all()
        job = db_.get(Job, job_id)
        return job is not None and job.status == "cancelled"

    monkeypatch.setattr(job_tasks, "_is_stopped", cancelled_only)

    job_id = _resume_failed_mid_extraction(db, worker)

    assert worker.connector.fetched == ["vMidRun00001", "vMidRun00002"]
    assert _snapshot(db, job_id)["status"] == "failed"


def test_mutation_without_any_stop_the_failed_resume_completes(db, worker, monkeypatch):
    monkeypatch.setattr(job_tasks, "_STOPPED_STATUSES", ("no-such-status",))

    job_id = _resume_failed_mid_extraction(db, worker)

    assert _snapshot(db, job_id)["status"] == "completed"


# ---------------------------------------------------------------- a cancelled run still ends cancelled


def _resume_stopped_during_the_report(client, db, worker, test_user, stop: str) -> str:
    job_id = _job_with_videos(db, test_user.id, ["vReport00001"])

    def report(**kwargs):
        if stop == "cancelled":
            _cancel(client, job_id)
        else:
            _route_fails(db, job_id, "Stopped elsewhere.")
        return {}, "<p>report</p>"

    worker.report.side_effect = report
    REAL_TASKS["resume_job_after_approval"].run(job_id)
    return job_id


@pytest.mark.parametrize("stop", ["cancelled", "failed"])
def test_a_run_stopped_during_its_report_is_not_completed(client, db, worker, test_user, stop):
    """On a solo pool a revoke cannot stop a running task, so a cancel during
    the report reached ``completed``. The completed write is refused, the row
    keeps the stop's words, and the report file, which no row would point
    at, is removed."""
    job_id = _resume_stopped_during_the_report(client, db, worker, test_user, stop)

    row = _snapshot(db, job_id)
    assert row["status"] == stop
    assert row["progress_message"] == (CANCELLED_WORDS if stop == "cancelled" else "Failed")
    assert row["report_path"] is None
    assert "completed" not in _status_changes(worker)
    assert not os.path.exists(os.path.join(job_tasks.settings.REPORTS_DIR, f"report_{job_id}.html"))
    worker.progress.publish_error.assert_not_called()


def test_mutation_an_unguarded_write_completes_a_run_cancelled_during_its_report(
    client, db, worker, test_user, monkeypatch
):
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)

    job_id = _resume_stopped_during_the_report(client, db, worker, test_user, "cancelled")

    assert _snapshot(db, job_id)["status"] == "completed"


def _resume_cancelled_then_raising(client, db, worker, test_user) -> str:
    job_id = _job_with_videos(db, test_user.id, ["vRaises00001"])

    def cancel_then_raise(source_id):
        _cancel(client, job_id)
        raise RuntimeError("connection reset by peer")

    worker.connector.on_fetch = cancel_then_raise
    REAL_TASKS["resume_job_after_approval"].run(job_id)
    return job_id


def test_a_cancelled_run_that_then_raises_stays_cancelled(client, db, worker, test_user):
    """The failure belongs to a run that had already ended: ``_handle_failure``
    leaves the row and says nothing on the socket."""
    job_id = _resume_cancelled_then_raising(client, db, worker, test_user)

    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"], row["error_message"]) == ("cancelled", CANCELLED_WORDS, None)
    worker.progress.publish_error.assert_not_called()


def test_mutation_an_unguarded_failure_write_fails_the_cancelled_run(client, db, worker, test_user, monkeypatch):
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)

    job_id = _resume_cancelled_then_raising(client, db, worker, test_user)

    assert _snapshot(db, job_id)["status"] == "failed"
    worker.progress.publish_error.assert_called_once()


def _sync_cancelled_mid_extraction(client, db, worker, test_user) -> str:
    db.add(Channel(channel_id=CHANNEL, name="Stopped Channel", uploads_playlist_id="UUstoppedRun0001"))
    db.commit()
    job_id = _job_with_videos(db, test_user.id, ["vSyncCancel1", "vSyncCancel2"],
                              status="pending", job_type="subscription")

    def cancel_on_first(source_id):
        if source_id == "vSyncCancel1":
            _cancel(client, job_id)

    worker.connector.on_fetch = cancel_on_first
    REAL_TASKS["execute_subscription_job"].run(job_id)
    return job_id


def test_a_sync_cancelled_mid_extraction_ends_cancelled(client, db, worker, test_user):
    """The upload in hand finishes; its progress does not cover the cancel's
    words, and the next upload's check stops the sync before its fetch."""
    job_id = _sync_cancelled_mid_extraction(client, db, worker, test_user)

    assert worker.connector.fetched == ["vSyncCancel1"]
    row = _snapshot(db, job_id)
    assert (row["status"], row["progress_message"]) == ("cancelled", CANCELLED_WORDS)
    assert "completed" not in _status_changes(worker)


def test_mutation_an_unguarded_progress_write_covers_the_cancel(client, db, worker, test_user, monkeypatch):
    monkeypatch.setattr(job_tasks, "_write_unless_stopped", _unguarded_write)

    job_id = _sync_cancelled_mid_extraction(client, db, worker, test_user)

    assert _snapshot(db, job_id)["progress_message"].startswith("Video 1/2")


# ---------------------------------------------------------------- the approval's own write


def _approve_while_the_resume_fails_at_once(client, db, test_user) -> tuple[str, dict]:
    """The resume was queued, ran and failed (nothing to read) before the
    route reached its ``extracting`` write."""
    job_id = _job_with_videos(db, test_user.id, ["vApprove0002"], status="awaiting_approval")

    def queued_and_already_failed(args=(), kwargs=None, queue=None):
        _route_fails(db, args[0], "No transcripts could be fetched for any video.", progress_message=None)
        return MagicMock(id="resume-task-id")

    with patch("app.routers.jobs.resume_job_after_approval") as task:
        task.apply_async.side_effect = queued_and_already_failed
        response = client.put(f"/api/v1/jobs/{job_id}/approve", json={"approved_video_ids": ["vApprove0002"]})
    assert response.status_code == 200, response.text
    return job_id, response.json()


def test_approve_never_writes_extracting_over_what_the_resume_wrote(client, db, test_user):
    job_id, body = _approve_while_the_resume_fails_at_once(client, db, test_user)

    assert body["status"] == "failed"
    row = _snapshot(db, job_id)
    assert (row["status"], row["error_message"]) == ("failed", "No transcripts could be fetched for any video.")
    assert row["celery_task_id"] == "resume-task-id"


def test_approve_still_writes_extracting_when_the_resume_has_not_run(client, db, test_user):
    job_id = _job_with_videos(db, test_user.id, ["vApprove0003"], status="awaiting_approval")

    response = client.put(f"/api/v1/jobs/{job_id}/approve", json={"approved_video_ids": ["vApprove0003"]})

    assert response.json()["status"] == "extracting"
    assert _snapshot(db, job_id)["progress_message"] == "Starting transcript extraction..."


def test_mutation_an_unconditional_approval_write_strands_the_failed_run(client, db, test_user, monkeypatch):
    """Without ``only_from`` the route writes ``extracting`` over the failure,
    and nothing would ever move the row again."""
    real = job_service.update_job_status

    def unconditional(*args, only_from=None, **kwargs):
        return real(*args, **kwargs)

    monkeypatch.setattr(job_service, "update_job_status", unconditional)

    job_id, _ = _approve_while_the_resume_fails_at_once(client, db, test_user)

    assert _snapshot(db, job_id)["status"] == "extracting"


# ---------------------------------------------------------------- T-8.8.6.12: the sync joins on document_id


def _cached(db, doc: Document) -> None:
    db.add(TranscriptCache(document_id=doc.document_id, video_id=doc.video_id,
                           segments_json=json.dumps(SEGMENTS), language="en", source="youtube"))


def _sync_with_linked_documents(db, test_user) -> dict:
    """A sync redelivered after a partial run: its links are already there,
    and the uploads walk finds nothing new.

    * A, a library video, fetched and embedded. Its link's back-compat
      ``video_id`` names B, which this job never linked.
    * B, another library video, not in this job.
    * C, a document with no ``video_id`` (an episode, as a non-video source
      has), fetched and embedded, its text cached under its document id only.
    * D, a video never fetched, read through the connector and embedded.
    """
    db.add(Channel(channel_id=CHANNEL, name="Stopped Channel", uploads_playlist_id="UUstoppedRun0001"))
    a = _video(db, "vDocIdA00001", transcript_status="fetched", embedded_in_chroma=True)
    b = _video(db, "vDocIdB00001", transcript_status="fetched", embedded_in_chroma=True)
    c = Document(video_id=None, source_type="podcast", source_id="https://feeds.example/ep/1",
                 url="https://feeds.example/ep/1",
                 title="An episode", transcript_status="fetched", embedded_in_chroma=True)
    db.add(c)
    db.flush()
    d = _video(db, "vDocIdD00001")
    for doc in (a, b, c):
        _cached(db, doc)
    job = Job(job_type="subscription", status="pending", topic="Sync Stopped Channel",
              channel_list=json.dumps([CHANNEL]), num_videos=0, tenant_id=test_user.id)
    db.add(job)
    db.flush()
    db.add_all([
        JobVideo(job_id=job.id, document_id=a.document_id, video_id=b.video_id, approved=True,
                 selection_reason="subscription"),
        JobVideo(job_id=job.id, document_id=c.document_id, video_id=None, approved=True,
                 selection_reason="subscription"),
        JobVideo(job_id=job.id, document_id=d.document_id, video_id=d.video_id, approved=True,
                 selection_reason="subscription"),
    ])
    db.commit()
    return {"job": job.id, "a": a.document_id, "b": b.document_id, "c": c.document_id, "d": d.document_id}


def _run_sync_recording_chunked(db, worker, monkeypatch, test_user) -> tuple[dict, list[str]]:
    ids = _sync_with_linked_documents(db, test_user)
    chunked: list[str] = []
    real_chunk = job_tasks.chunk_transcript

    def recording_chunk(segments, **kwargs):
        chunked.append(kwargs["video_metadata"]["document_id"])
        return real_chunk(segments, **kwargs)

    monkeypatch.setattr(job_tasks, "chunk_transcript", recording_chunk)
    REAL_TASKS["execute_subscription_job"].run(ids["job"])
    return ids, chunked


def test_the_sync_extracts_its_documents_by_document_id(db, worker, monkeypatch, test_user):
    ids, chunked = _run_sync_recording_chunked(db, worker, monkeypatch, test_user)

    assert sorted(chunked) == sorted([ids["a"], ids["c"], ids["d"]])
    assert worker.connector.fetched == ["vDocIdD00001"], "A and C reused from their cache, D read"
    assert _snapshot(db, ids["job"])["status"] == "completed"
    assert _chunk_ids(ids["d"]), "D's chunks are in the library"
    assert _flagged_embedded(db, ids["d"]), "and D is flagged so, once they are"


def test_mutation_the_sync_joined_on_video_id_picks_the_wrong_documents(db, worker, monkeypatch, test_user):
    """The join before T-8.8.6.12: B instead of A, and no C."""
    def by_video_id(db_, job_id):
        return (
            db_.query(Document)
            .join(JobVideo, JobVideo.video_id == Document.video_id)
            .filter(JobVideo.job_id == job_id, JobVideo.approved.is_(True))
            .all()
        )

    monkeypatch.setattr(job_tasks, "_approved_documents", by_video_id)

    ids, chunked = _run_sync_recording_chunked(db, worker, monkeypatch, test_user)

    assert ids["b"] in chunked
    assert ids["a"] not in chunked and ids["c"] not in chunked


# ---------------------------------------------------------------- the embedded flag follows the chunks
#
# A document is flagged embedded only once its chunks are in Chroma. Both
# extraction loops used to commit the flag as each document was chunked, while
# the chunks reached Chroma only at the RAG build: a run stopped (or raising)
# between the two left documents flagged with no chunks, and every later job
# reused them without inserting anything, so no Q&A could retrieve them.


def _chunk_ids(document_id: str) -> list[str]:
    return chroma_service.get_global_collection().get(where={"document_id": document_id})["ids"]


def _flagged_embedded(db, document_id: str) -> bool:
    db.expire_all()
    return bool(db.get(Document, document_id).embedded_in_chroma)


def _document_of(db, video_id: str) -> Document:
    db.expire_all()
    return db.query(Document).filter(Document.video_id == video_id).one()


def _next_job_selects(db, worker, video_id: str) -> str:
    """A later run, after an approval, whose selection includes the video.
    Its transcript is cached, as ``youtube_service`` caches every fetch (the
    fake connector does not), so a flagged document reads as fully reused."""
    doc = _document_of(db, video_id)
    if db.get(TranscriptCache, doc.document_id) is None:
        _cached(db, doc)
    job = Job(job_type="topic", topic="tariffs", status="extracting", tenant_id="tenant-next-job")
    db.add(job)
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=video_id, approved=True))
    db.commit()
    worker.connector.on_fetch = None
    REAL_TASKS["resume_job_after_approval"].run(job.id)
    return job.id


def test_a_stopped_run_leaves_the_document_it_chunked_unflagged(db, worker):
    """The route failed the row while the first video was read: its text is
    kept, but its chunks never reached Chroma, so it is not flagged."""
    _resume_failed_mid_extraction(db, worker)

    doc = _document_of(db, "vMidRun00001")
    assert doc.transcript_status == "fetched"
    assert not doc.embedded_in_chroma
    assert _chunk_ids(doc.document_id) == []


def test_the_next_job_embeds_what_a_stopped_run_chunked(db, worker):
    _resume_failed_mid_extraction(db, worker)

    job_id = _next_job_selects(db, worker, "vMidRun00001")

    doc = _document_of(db, "vMidRun00001")
    assert _snapshot(db, job_id)["status"] == "completed"
    assert _chunk_ids(doc.document_id), "its chunks are in the library now"
    assert doc.embedded_in_chroma


def test_mutation_a_flag_set_as_each_document_is_chunked_strands_it(db, worker, monkeypatch):
    """The flag committed before the RAG build, as both loops did: the next
    job takes the document as fully reused and inserts nothing for it."""
    real = job_tasks._ensure_era

    def flag_while_chunking(db_, video, segments, job_id):
        real(db_, video, segments, job_id)
        video.embedded_in_chroma = True
        db_.commit()

    monkeypatch.setattr(job_tasks, "_ensure_era", flag_while_chunking)
    _resume_failed_mid_extraction(db, worker)
    monkeypatch.setattr(job_tasks, "_ensure_era", real)

    _next_job_selects(db, worker, "vMidRun00001")

    doc = _document_of(db, "vMidRun00001")
    assert doc.embedded_in_chroma
    assert _chunk_ids(doc.document_id) == [], "flagged, and nothing any Q&A could retrieve"


def test_an_insert_that_raises_leaves_its_documents_unflagged(db, worker, monkeypatch):
    job_id = _job_with_videos(db, "tenant-insert-fails", ["vInsertFail1"])

    def insert_fails(chunks):
        raise RuntimeError("chroma is unavailable")

    monkeypatch.setattr(chroma_service, "insert_chunks", insert_fails)
    REAL_TASKS["resume_job_after_approval"].run(job_id)

    assert _snapshot(db, job_id)["status"] == "failed"
    doc = _document_of(db, "vInsertFail1")
    assert doc.transcript_status == "fetched"
    assert not doc.embedded_in_chroma


def test_a_sync_cancelled_mid_extraction_leaves_its_upload_unflagged(client, db, worker, test_user):
    _sync_cancelled_mid_extraction(client, db, worker, test_user)

    doc = _document_of(db, "vSyncCancel1")
    assert doc.transcript_status == "fetched"
    assert not doc.embedded_in_chroma
    assert _chunk_ids(doc.document_id) == []

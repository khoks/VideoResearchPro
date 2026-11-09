"""T-5.6.17: a failed run stores and publishes no key, at the four tasks.

D-151 scrubs each log record as it is made, but ``jobs.error_message`` and
the socket's error event are not log records. Every orchestrator's last
``except`` wrote ``str(e)`` to both through ``_handle_failure``, and the owner
of the run reads them: an OpenAI refusal quotes the key it refused, which can
be the install's, and a YouTube ``HttpError`` carries the install's key in
its URL. These run the real task bodies on the test session with a failure
that quotes a key in each shape ``provider_error_text`` knows, then read the
row and the published event. No request reaches a provider.

Mutation checks: put ``str(e)`` back at any of the four ``_handle_failure``
calls and ``test_a_failed_run_keeps_no_key`` fails for that task on eight of
the nine cases: the refusals keep their key, whose shape the sink's
``scrub_keys`` does not know, and the others lose their class. Drop that
``scrub_keys`` as well and the ninth fails too.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import auth_service, quota_service
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import ExtractedText
from app.tasks import job_tasks
from tests.provider_errors import CASES, KeyBearing, assert_kept_out


class _Unclosable:
    """The test session, which the task's ``db.close()`` must not end."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture
def progress(db, monkeypatch):
    """The tasks on the test session. Yields the progress publisher, so a test
    can read what went out on the socket."""
    session = _Unclosable(db)
    publisher = MagicMock()
    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(job_tasks, "progress_service", publisher)
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    monkeypatch.setattr(quota_service, "get_today_usage", lambda: 0)
    return publisher


def _job(db, **fields) -> Job:
    owner = auth_service.create_user(db, email=f"run-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    job = Job(num_videos=1, tenant_id=owner.id, **fields)
    db.add(job)
    db.commit()
    return job


_TASKS = {
    "topic": (job_tasks.execute_topic_job, {"job_type": "topic", "topic": "tariffs"}),
    "channel": (job_tasks.execute_channel_job, {"job_type": "channel", "channel_list": '["UCkeys0000001"]'}),
    "subscription": (job_tasks.execute_subscription_job, {"job_type": "subscription", "channel_list": '["UCkeys0000001"]'}),
    "resume": (job_tasks.resume_job_after_approval, {"job_type": "topic", "topic": "tariffs", "status": "awaiting_approval"}),
}


def _failed(db, progress, job_id: str) -> str:
    """The stored message, after checking the socket said the same."""
    db.expire_all()
    job = db.get(Job, job_id)
    assert job.status == "failed"
    (published_job, published), _ = progress.publish_error.call_args
    assert published_job == job_id and published == job.error_message
    return job.error_message


@pytest.mark.parametrize("task", sorted(_TASKS))
@pytest.mark.parametrize("case", CASES)
def test_a_failed_run_keeps_no_key(db, progress, task: str, case: KeyBearing):
    """Raised inside each task's own ``try``, at its first word to the socket,
    so the failure reaches that task's last ``except``."""
    run, fields = _TASKS[task]
    job = _job(db, **fields)
    progress.publish_status_change.side_effect = case.make()

    run.run(job.id)

    assert_kept_out(case, _failed(db, progress, job.id))


@pytest.mark.parametrize("case", [c for c in CASES if c.id != "youtube-403"])
def test_a_refusal_in_the_search_agents_model_keeps_no_key(db, progress, case):
    """Where it really comes from: the search agent's model, with nothing else
    found, so the run fails as itself. A YouTube ``HttpError`` takes the other
    road, YouTube being unavailable, which never kept its words."""
    job = _job(db, job_type="topic", topic="tariffs")
    with patch("app.agents.search_agent.run_search_agent", side_effect=case.make()):
        job_tasks.execute_topic_job.run(job.id)

    assert_kept_out(case, _failed(db, progress, job.id))


class _Thread(BaseConnector):
    source_type = "hn_story"

    def search(self, *a, **kw):  # pragma: no cover
        return []

    def list_creator_items(self, *a, **kw):  # pragma: no cover
        return []

    def fetch_metadata(self, *a, **kw):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id="", query="", **kwargs):
        return ExtractedText(
            segments=[{"text": "a thread about tariffs " * 20, "start": 0.0, "duration": 0.0}],
            language="en",
            text_source="hn",
            word_count=80,
        )


@pytest.fixture
def one_thread():
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    registry.register(_Thread())
    yield
    registry._reset_for_tests()
    for connector in snapshot.values():
        registry.register(connector)


@pytest.mark.parametrize("case", CASES)
def test_a_refusal_while_the_report_is_written_keeps_no_key(db, progress, one_thread, case):
    """The report's models fail after the text was read and embedded."""
    job = _job(db, job_type="topic", topic="tariffs", status="awaiting_approval")
    doc = Document(source_type="hn_story", source_id="hn:1", title="A thread", url="https://news.example/1")
    db.add(doc)
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=None, approved=True))
    db.commit()

    with (
        patch.object(job_tasks, "chroma_service"),
        patch.object(job_tasks, "language_mix_service", MagicMock(ensure=lambda *a, **k: None)),
        patch("app.agents.report_agent.run_report_agent", side_effect=case.make()),
    ):
        job_tasks.resume_job_after_approval.run(job.id)

    assert_kept_out(case, _failed(db, progress, job.id))

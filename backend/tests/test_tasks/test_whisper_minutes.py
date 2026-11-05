"""T-1.7.1.1: ``WHISPER_MAX_MINUTES_PER_JOB``, at the tasks that spend Whisper.

``WHISPER_MAX_PER_JOB`` counts recordings, and one recording can be a 3-minute
clip or a 76-minute show. These run the real extraction tasks over approved
documents, with the connector or the OpenAI client as the only fake.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.user import User
from app.services import youtube_service
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.podcast import connector as podcast_connector
from app.sources.types import ExtractedText
from app.tasks import job_tasks
from tests.usage_helpers import (
    FakeWhisperApi,  # noqa: F401  (documents what `whisper_api` yields)
    whisper_api,  # noqa: F401  (fixture)
    youtube_network,  # noqa: F401  (fixture)
)

MINUTE = 60.0


class _Podcasts(BaseConnector):
    """Each document transcribes to its declared length, if Whisper is allowed."""

    source_type = "podcast_episode"
    text_source = "podcast_whisper"

    def __init__(self, heard: dict[str, float] | None = None):
        self.calls: list[tuple[str, bool]] = []
        self.heard = heard or {}

    def search(self, *a, **kw):  # pragma: no cover
        return []

    def list_creator_items(self, *a, **kw):  # pragma: no cover
        return []

    def fetch_metadata(self, *a, **kw):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id="", query="", allow_whisper=True):
        self.calls.append((candidate.source_id, allow_whisper))
        if not allow_whisper:
            return None
        return ExtractedText(
            segments=[{"text": "words", "start": 0.0, "duration": self.heard.get(candidate.source_id, 1.0)}],
            language="en",
            text_source=self.text_source,
            word_count=1,
        )


class _Videos(_Podcasts):
    """A subscription job reads YouTube, whose documents carry a video_id."""

    source_type = "video"
    text_source = "whisper"


@pytest.fixture
def podcasts():
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    fake = _Podcasts()
    registry.register(fake)
    yield fake
    registry._reset_for_tests()
    for connector in snapshot.values():
        registry.register(connector)


@pytest.fixture
def tasks(db, monkeypatch):
    """The extraction task on the test session, with its report stubbed.
    Yields the progress messages it publishes."""
    from tests import conftest as _conftest

    published: list[str] = []
    progress = MagicMock()
    progress.publish_progress.side_effect = lambda job_id, stage, pct, message, **kw: published.append(message)
    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(job_tasks, "progress_service", progress)
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    monkeypatch.setattr(job_tasks, "language_mix_service", MagicMock(ensure=lambda *a, **k: None))
    return published


def _resume(job_id: str) -> None:
    with (
        patch.object(job_tasks, "chroma_service") as chroma,
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.resume_job_after_approval.run(job_id)


def _approved(db, lengths: list[float | None], *, videos: bool = False) -> str:
    """A job awaiting extraction, one approved episode per declared length."""
    owner = User(email="owner@example.com", password_hash="x")
    db.add(owner)
    db.flush()
    job = Job(job_type="topic", topic="tariffs", num_videos=len(lengths), status="awaiting_approval", tenant_id=owner.id)
    db.add(job)
    db.flush()
    for i, seconds in enumerate(lengths):
        doc = Document(
            source_type="video" if videos else "podcast_episode",
            source_id=f"vid{i}" if videos else f"podcast:ep-{i}",
            video_id=f"vid{i}" if videos else None,
            title=f"Episode {i}",
            url=f"https://example.com/{i}",
            channel_id=None if videos else "https://example.com/feed.xml",
            duration_seconds=seconds,
        )
        db.add(doc)
        db.flush()
        db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
    db.commit()
    return job.id


def _notes(db, job_id: str) -> list[dict]:
    db.expire_all()
    raw = db.get(Job, job_id).run_notes_json
    return json.loads(raw) if raw else []


def test_with_no_minute_cap_nothing_changes(db, podcasts, tasks, monkeypatch):
    """The default, so today's spend stands until the owner sets one."""
    assert settings.WHISPER_MAX_MINUTES_PER_JOB == 0
    job_id = _approved(db, [3600.0] * 4)

    _resume(job_id)

    assert [allowed for _, allowed in podcasts.calls] == [True] * 4
    assert _notes(db, job_id) == []
    assert not any("Whisper" in m for m in tasks)


def test_the_cap_stops_before_the_next_transcription_once_spent(db, podcasts, tasks, monkeypatch):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 10)
    job_id = _approved(db, [6 * MINUTE] * 4)

    _resume(job_id)

    assert [allowed for _, allowed in podcasts.calls] == [True, True, False, False]
    db.expire_all()
    assert db.get(Job, job_id).status == "completed"
    note = next(n for n in _notes(db, job_id) if n["kind"] == "whisper_minutes_spent")
    assert note["text"] == (
        "Whisper stopped after 12 minutes of audio, the limit is 10 "
        "(WHISPER_MAX_MINUTES_PER_JOB). 2 sources could not be read."
    )


def test_the_run_says_so_while_it_is_happening(db, podcasts, tasks, monkeypatch):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    _resume(_approved(db, [6 * MINUTE] * 2))

    assert any("Whisper minutes spent" in m for m in tasks)


def test_a_cap_never_reached_says_nothing(db, podcasts, tasks, monkeypatch):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 60)
    job_id = _approved(db, [6 * MINUTE] * 3)

    _resume(job_id)

    assert [allowed for _, allowed in podcasts.calls] == [True] * 3
    assert _notes(db, job_id) == []


def test_the_recording_count_still_applies_on_its_own(db, podcasts, tasks, monkeypatch):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 600)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    job_id = _approved(db, [MINUTE] * 3)

    _resume(job_id)

    assert [allowed for _, allowed in podcasts.calls] == [True, False, False]
    assert any("Whisper budget exhausted" in m for m in tasks)
    assert not any("Whisper minutes spent" in m for m in tasks)
    assert _notes(db, job_id) == [], "the minute limit cost this run nothing"


def test_length_comes_from_the_transcript_when_the_feed_declares_none(db, podcasts, tasks, monkeypatch):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    podcasts.heard = {"podcast:ep-0": 6 * MINUTE}
    _resume(_approved(db, [None, None]))

    assert [allowed for _, allowed in podcasts.calls] == [True, False]


def test_a_declared_length_past_the_last_word_counts_in_full(db, podcasts, tasks, monkeypatch):
    """Whisper is paid for the whole file, music at the end included."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    podcasts.heard = {"podcast:ep-0": MINUTE}
    _resume(_approved(db, [6 * MINUTE, 6 * MINUTE]))

    assert [allowed for _, allowed in podcasts.calls] == [True, False]


@pytest.mark.parametrize("cap_minutes, requests", [(14, 3), (15, 6)])
def test_a_split_file_counts_its_whole_length_once(
    db, tasks, whisper_api, monkeypatch, tmp_path, cap_minutes, requests  # noqa: F811
):
    """Through the real connector and the real chunked path. Three chunks of
    300 s, 285 s apart, are 870 s of audio, and the episode counts as that:
    past a 14-minute cap, so the next episode is not sent, and short of a
    15-minute one, which the 900 s of the chunks added up would have spent."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)

    feed_url = "https://example.com/feed.xml"
    entries = [
        {"id": f"ep-{i}", "title": f"Episode {i}", "enclosures": [{"href": f"https://example.com/{i}.mp3"}]}
        for i in range(2)
    ]

    def writes(url, path):
        with open(path, "wb") as f:
            f.write(b"far too many mp3 bytes")
        return 22

    monkeypatch.setattr(podcast_connector.settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        podcast_connector.podcast_client,
        "get_client",
        lambda: SimpleNamespace(
            fetch_feed=lambda url: {"feed": {}, "entries": entries if url == feed_url else []},
            fetch_audio_to_file=writes,
        ),
    )
    chunks = [tmp_path / f"chunk{i}.m4a" for i in range(3)]
    for chunk in chunks:
        chunk.write_bytes(b"x")
    monkeypatch.setattr(youtube_service, "WHISPER_MAX_FILE_BYTES", 4)
    monkeypatch.setattr(
        youtube_service,
        "_split_audio_for_whisper",
        lambda path, tmpdir, tag: [(str(c), i * 285.0) for i, c in enumerate(chunks)],
    )
    whisper_api.seconds = 300.0
    whisper_api.segment_start = 100.0
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == requests


def test_a_subscription_walk_honours_the_cap_too(db, tasks, monkeypatch):
    """Its extraction loop is its own, it never had a recording cap, and a
    channel's history is the longest audio a job can reach."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    fake = _Videos()
    job_id = _approved(db, [6 * MINUTE] * 2, videos=True)
    db.expire_all()
    job = db.get(Job, job_id)
    job.job_type = "subscription"
    db.commit()

    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    registry.register(fake)
    try:
        with patch.object(job_tasks, "chroma_service") as chroma:
            chroma.insert_chunks = MagicMock(return_value=1)
            job_tasks._run_extraction_and_rag(SimpleNamespace(request=SimpleNamespace(id="t")), db, job)
    finally:
        registry._reset_for_tests()
        for connector in snapshot.values():
            registry.register(connector)

    assert fake.calls == [("vid0", True), ("vid1", False)]
    assert any(n["kind"] == "whisper_minutes_spent" for n in _notes(db, job_id))


def test_a_subscription_with_no_cap_calls_the_connector_as_before(db, tasks):
    """No ``allow_whisper`` at all, so a connector without the argument is fine."""

    class Plain(_Videos):
        def fetch_text(self, candidate, *, job_id="", query=""):
            return None

    job_id = _approved(db, [MINUTE], videos=True)
    db.expire_all()
    job = db.get(Job, job_id)
    job.job_type = "subscription"
    db.commit()

    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    registry.register(Plain())
    try:
        with patch.object(job_tasks, "chroma_service"):
            job_tasks._run_extraction_and_rag(SimpleNamespace(request=SimpleNamespace(id="t")), db, job)
    finally:
        registry._reset_for_tests()
        for connector in snapshot.values():
            registry.register(connector)
    db.expire_all()
    assert db.get(Job, job_id).status == "failed"
    assert _notes(db, job_id) == []

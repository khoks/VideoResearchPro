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
from app.services import source_failure, youtube_service
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.podcast import connector as podcast_connector
from app.sources.types import ExtractedText
from app.tasks import job_tasks
from tests.test_tasks.test_usage_metering_tasks import _channel_responses, _owner
from tests.test_tasks.test_usage_whisper_and_crash import (
    _run_sync,
    _split_into,
    _sync_job,
    no_captions,  # noqa: F401  (fixture)
)
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
        "Whisper stopped after 12 minutes of audio, past the 10-minute limit "
        "(WHISPER_MAX_MINUTES_PER_JOB), so 2 sources could not be read."
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


def _split_episodes(monkeypatch, tmp_path, whisper_api, *, episodes: int = 2) -> None:  # noqa: F811
    """Every episode reaches the real connector and splits into three chunks
    of 300 s, 285 s apart."""
    feed_url = "https://example.com/feed.xml"
    entries = [
        {"id": f"ep-{i}", "title": f"Episode {i}", "enclosures": [{"href": f"https://example.com/{i}.mp3"}]}
        for i in range(episodes)
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


@pytest.mark.parametrize("cap_minutes, requests", [(14, 3), (15, 6)])
def test_a_split_file_counts_its_whole_length_once(
    db, tasks, whisper_api, monkeypatch, tmp_path, cap_minutes, requests  # noqa: F811
):
    """Through the real connector and the real chunked path. Three chunks of
    300 s, 285 s apart, are 870 s of audio, and the episode counts as that:
    past a 14-minute cap, so the next episode is not sent, and short of a
    15-minute one, which the 900 s of the chunks added up would have spent."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == requests


def test_a_subscription_walk_honours_the_cap_too(db, tasks, monkeypatch):
    """Its extraction loop is its own, and a channel's history is the longest
    audio a job can reach."""
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


def _walk(db, job_id: str, fake: BaseConnector) -> None:
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


def test_a_subscription_walk_honours_the_recording_count_too(db, tasks, monkeypatch):
    """Both limits apply to it, as to an approved run, and the note names the
    one that stopped it."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 600)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    fake = _Videos()
    job_id = _approved(db, [MINUTE] * 3, videos=True)

    _walk(db, job_id, fake)

    assert [allowed for _, allowed in fake.calls] == [True, False, False]
    assert any("Whisper budget exhausted" in m for m in tasks)
    assert [n["kind"] for n in _notes(db, job_id)] == ["whisper_budget_spent"]


def test_when_both_limits_are_spent_the_run_says_so_once(db, tasks, monkeypatch):
    """Minutes first, as the progress line does: one reason for one lost source."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    fake = _Videos()
    job_id = _approved(db, [6 * MINUTE] * 2, videos=True)

    _walk(db, job_id, fake)

    assert [allowed for _, allowed in fake.calls] == [True, False]
    assert any("Whisper minutes spent" in m for m in tasks)
    assert [n["kind"] for n in _notes(db, job_id)] == ["whisper_minutes_spent"]


# ---------------------------------------------------------------------------
# T-1.7.1.5: a transcription that fails part-way
#
# Its finished chunks were billed and it leaves no text, so `fetch_text`
# returned None like a failed download and neither limit heard about it. The
# job learns from the connector's own `TranscriptionCutShort`, never from the
# usage meter (D-111). Mutation check: make `_transcribe_in_chunks` return None
# where it raises, and `test_a_part_paid_episode_counts_against_the_minute_cap`
# and `test_a_part_paid_episode_counts_as_a_recording` both send the next
# episode to Whisper.
# ---------------------------------------------------------------------------


def _fail_once_at(whisper_api, nth: int) -> None:  # noqa: F811
    """Request ``nth`` is refused, once, with what a provider's error can hold."""
    failed: list[bool] = []

    def before_send(api):
        if api.sent == nth - 1 and not failed:
            failed.append(True)
            raise RuntimeError("Incorrect API key provided: sk-tenant-secret")

    whisper_api.before_send = before_send


@pytest.mark.parametrize("cap_minutes, requests", [(9, 2), (10, 5)])
def test_a_part_paid_episode_counts_against_the_minute_cap(
    db, tasks, whisper_api, monkeypatch, tmp_path, cap_minutes, requests  # noqa: F811
):
    """Two chunks finish, the third fails: the transcript reached 585 s. That
    is past a 9-minute cap, so the next episode is not sent, and short of a
    10-minute one, which the 600 s of the two chunks added up would have spent
    (D-141: an overlap counts once). With 10 minutes the next episode runs."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    _fail_once_at(whisper_api, 3)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == requests


def test_a_part_paid_episode_counts_as_a_recording(db, tasks, whisper_api, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    _fail_once_at(whisper_api, 2)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == 1, "the next episode stayed behind the limit"
    db.expire_all()
    assert db.get(Job, job_id).status == "failed", "nothing was read, so the run has nothing"


def test_a_failure_on_the_first_chunk_was_not_billed_and_is_not_charged(
    db, tasks, whisper_api, monkeypatch, tmp_path  # noqa: F811
):
    """Nothing came back, so the limit keeps its room for the next episode."""
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    _fail_once_at(whisper_api, 1)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == 3, "the second episode, in full"
    db.expire_all()
    statuses = [d.transcript_status for d in db.query(Document).order_by(Document.source_id)]
    assert statuses == ["unavailable", "fetched"]


def test_a_part_paid_episode_leaves_it_unavailable_and_the_run_goes_on(
    db, tasks, whisper_api, monkeypatch, tmp_path  # noqa: F811
):
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    _fail_once_at(whisper_api, 2)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    db.expire_all()
    assert db.get(Job, job_id).status == "completed"
    statuses = [d.transcript_status for d in db.query(Document).order_by(Document.source_id)]
    assert statuses == ["unavailable", "fetched"]


def test_the_limits_do_not_read_the_usage_meter(db, tasks, whisper_api, monkeypatch, tmp_path):  # noqa: F811
    """D-111: with the meter silent the cap still hears, from the connector."""
    monkeypatch.setattr(youtube_service.usage_service, "record_whisper", lambda seconds: None)
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    _fail_once_at(whisper_api, 2)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == 1


class _CutShort(_Videos):
    """Whisper reaches ``seconds`` into ``vid0`` and fails."""

    seconds = 120.0

    def fetch_text(self, candidate, *, job_id="", query="", allow_whisper=True):
        if candidate.source_id == "vid0":
            self.calls.append((candidate.source_id, allow_whisper))
            raise source_failure.TranscriptionCutShort(self.seconds)
        return super().fetch_text(candidate, job_id=job_id, query=query, allow_whisper=allow_whisper)


def test_a_subscription_walk_hears_the_same(db, tasks, monkeypatch):
    """The sync loop charges both limits as the approved run does. Whether the
    count applies to syncs at all is OQ-36, and this leaves that as it was."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 600)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    fake = _CutShort()
    job_id = _approved(db, [MINUTE] * 3, videos=True)

    _walk(db, job_id, fake)

    assert [allowed for _, allowed in fake.calls] == [True, False, False]
    assert [n["kind"] for n in _notes(db, job_id)] == ["whisper_budget_spent"]


def test_a_subscription_walk_charges_what_was_heard_not_what_was_declared(db, tasks, monkeypatch):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    fake = _CutShort()
    job_id = _approved(db, [60 * MINUTE, MINUTE], videos=True)

    _walk(db, job_id, fake)

    assert [allowed for _, allowed in fake.calls] == [True, True], "2 of 5 minutes: not spent"


def test_the_exception_carries_nothing_a_provider_said(db, whisper_api, monkeypatch, tmp_path):  # noqa: F811
    """A Whisper failure's text can quote a tenant's key, and this one travels
    further than the log line that names it by type (T-5.6.16)."""
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    _fail_once_at(whisper_api, 2)
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"x" * 9)

    with pytest.raises(source_failure.TranscriptionCutShort) as caught:
        youtube_service._transcribe_in_chunks(whisper_api.client, str(audio), str(tmp_path), "ep", "")

    assert caught.value.seconds == 300.0
    assert "sk-tenant-secret" not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


# ---------------------------------------------------------------------------
# The same, down YouTube's own path
#
# Most of a sync is YouTube, and every layer between the exception and the loop
# otherwise fails soft. The tests above fake the connector or take the podcast
# path, so a try/except around the fallback would turn the cut into None with
# all of them still passing. Here only the network is fake: the real
# `YouTubeConnector`, `fetch_transcript` and chunked path, with captions failing
# and the OpenAI client failing on the second chunk. Mutation check: catch
# Exception around `_transcribe_with_whisper` in `fetch_transcript`, or around
# `fetch_transcript` in `YouTubeConnector.fetch_text`, and these fail.
# ---------------------------------------------------------------------------


@pytest.fixture
def youtube_path(db, tasks, no_captions, whisper_api, monkeypatch, tmp_path):  # noqa: F811
    """Recordings that split in three, 300 s each, the second request failing
    once. Yields the ``allow_whisper`` of each ``fetch_transcript``, in order."""
    _split_into(monkeypatch, tmp_path, 3)
    whisper_api.seconds = 300.0
    _fail_once_at(whisper_api, 2)
    real = youtube_service.fetch_transcript
    asked: list[bool] = []

    def fetch_transcript(video_id, **kwargs):
        asked.append(kwargs.get("allow_whisper", True))
        return real(video_id, **kwargs)

    monkeypatch.setattr(youtube_service, "fetch_transcript", fetch_transcript)
    return asked


def _run_two_videos(db, kind: str, youtube_network) -> str:  # noqa: F811
    """Two videos declared at 10 minutes, through the task that runs them."""
    if kind == "sync":
        youtube_network.responses = _channel_responses(["vid0", "vid1"])
        job = _sync_job(db, _owner(db))
        _run_sync(job)
        return job.id
    job_id = _approved(db, [10 * MINUTE] * 2, videos=True)
    _resume(job_id)
    return job_id


@pytest.mark.parametrize("kind", ["sync", "approved"])
@pytest.mark.parametrize("cap_minutes, next_allowed, requests", [(5, False, 1), (6, True, 4)])
def test_a_part_paid_video_reaches_the_minute_cap_through_the_real_connector(
    db, youtube_path, youtube_network, whisper_api, monkeypatch,  # noqa: F811
    kind, cap_minutes, next_allowed, requests,
):
    """One 300 s chunk finished. That spends a 5-minute cap and leaves room
    under a 6-minute one, which the declared 10 minutes would have spent."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)

    job_id = _run_two_videos(db, kind, youtube_network)

    assert youtube_path == [True, next_allowed]
    assert whisper_api.sent == requests
    if not next_allowed:
        assert "after 5 minutes of audio" in _notes(db, job_id)[0]["text"]


@pytest.mark.parametrize("kind", ["sync", "approved"])
def test_a_part_paid_video_counts_as_a_recording_through_the_real_connector(
    db, youtube_path, youtube_network, whisper_api, monkeypatch, kind  # noqa: F811
):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 600)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)

    _run_two_videos(db, kind, youtube_network)

    assert youtube_path == [True, False]
    assert whisper_api.sent == 1


# ---------------------------------------------------------------------------
# T-1.7.1.7: Whisper that answered and left no text
#
# Every chunk merged to nothing, or a single file came back with no words. It
# was billed in full, and it read as a failed download, so neither limit heard
# about it. The connector now says so the way a cut-short one does
# (`TranscriptionEmpty`, a `PaidTranscriptionLost`), and the job charges one
# recording and what Whisper reported hearing, never from the usage meter
# (D-111). Mutation check: make the single-file paths (YouTube's and the
# podcast's) and `_transcribe_in_chunks` return None where they raise
# `TranscriptionEmpty`, and every test below that counts requests sends the
# next recording to Whisper.
# ---------------------------------------------------------------------------


def _single_episodes(monkeypatch, whisper_api, *, episodes: int = 2) -> None:  # noqa: F811
    """Every episode reaches the real connector as one file under the upload
    cap, and Whisper reports hearing 300 s of it."""
    feed_url = "https://example.com/feed.xml"
    entries = [
        {"id": f"ep-{i}", "title": f"Episode {i}", "enclosures": [{"href": f"https://example.com/{i}.mp3"}]}
        for i in range(episodes)
    ]

    def writes(url, path):
        with open(path, "wb") as f:
            f.write(b"mp3 bytes")
        return 9

    monkeypatch.setattr(podcast_connector.settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        podcast_connector.podcast_client,
        "get_client",
        lambda: SimpleNamespace(
            fetch_feed=lambda url: {"feed": {}, "entries": entries if url == feed_url else []},
            fetch_audio_to_file=writes,
        ),
    )
    whisper_api.seconds = 300.0


def _episodes(kind: str, monkeypatch, tmp_path, whisper_api) -> int:  # noqa: F811
    """Episodes of ``kind``; returns the requests one of them takes."""
    if kind == "split":
        _split_episodes(monkeypatch, tmp_path, whisper_api)
        return 3
    _single_episodes(monkeypatch, whisper_api)
    return 1


def _silent_first(whisper_api, requests: int) -> None:  # noqa: F811
    """The first recording's ``requests`` answers have no words; the rest do."""

    def before_send(api):
        api.silent = api.sent < requests

    whisper_api.before_send = before_send


@pytest.mark.parametrize("kind", ["single", "split"])
def test_a_silent_episode_counts_as_a_recording(db, tasks, whisper_api, monkeypatch, tmp_path, kind):  # noqa: F811
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    per_episode = _episodes(kind, monkeypatch, tmp_path, whisper_api)
    whisper_api.silent = True
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == per_episode, "the next episode stayed behind the limit"
    db.expire_all()
    assert db.get(Job, job_id).status == "failed", "nothing was read, so the run has nothing"


@pytest.mark.parametrize(
    "kind, cap_minutes, requests",
    # One file: 300 s heard spends a 5-minute cap, not a 6-minute one.
    # Three chunks 285 s apart reach 870 s: past 14 minutes, short of 15.
    [("single", 5, 1), ("single", 6, 2), ("split", 14, 3), ("split", 15, 6)],
)
def test_a_silent_episode_counts_against_the_minute_cap(
    db, tasks, whisper_api, monkeypatch, tmp_path, kind, cap_minutes, requests  # noqa: F811
):
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)
    _episodes(kind, monkeypatch, tmp_path, whisper_api)
    whisper_api.silent = True
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == requests


@pytest.mark.parametrize("kind", ["single", "split"])
def test_a_silent_episode_is_unavailable_and_the_run_goes_on(
    db, tasks, whisper_api, monkeypatch, tmp_path, kind  # noqa: F811
):
    per_episode = _episodes(kind, monkeypatch, tmp_path, whisper_api)
    _silent_first(whisper_api, per_episode)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    db.expire_all()
    assert db.get(Job, job_id).status == "completed"
    statuses = [d.transcript_status for d in db.query(Document).order_by(Document.source_id)]
    assert statuses == ["unavailable", "fetched"]


def test_a_silent_episode_reaches_the_limits_without_the_usage_meter(
    db, tasks, whisper_api, monkeypatch, tmp_path  # noqa: F811
):
    """D-111: with the meter silent the cap still hears, from the connector."""
    monkeypatch.setattr(youtube_service.usage_service, "record_whisper", lambda seconds: None)
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 5)
    _single_episodes(monkeypatch, whisper_api)
    whisper_api.silent = True
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == 1


def test_an_empty_split_says_how_far_whisper_heard(whisper_api, monkeypatch, tmp_path):  # noqa: F811
    _split_episodes(monkeypatch, tmp_path, whisper_api)
    whisper_api.silent = True
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"x" * 9)

    with pytest.raises(source_failure.TranscriptionEmpty) as caught:
        youtube_service._transcribe_in_chunks(whisper_api.client, str(audio), str(tmp_path), "ep", "")

    assert caught.value.seconds == 870.0
    assert isinstance(caught.value, source_failure.PaidTranscriptionLost)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.fixture
def silent_youtube(db, tasks, no_captions, whisper_api, monkeypatch, tmp_path):  # noqa: F811
    """Captions fail and Whisper answers every request with no words, 300 s
    heard each. Yields a function that splits each download in three, and the
    ``allow_whisper`` of each ``fetch_transcript``, in order."""
    whisper_api.seconds = 300.0
    whisper_api.silent = True
    real = youtube_service.fetch_transcript
    asked: list[bool] = []

    def fetch_transcript(video_id, **kwargs):
        asked.append(kwargs.get("allow_whisper", True))
        return real(video_id, **kwargs)

    monkeypatch.setattr(youtube_service, "fetch_transcript", fetch_transcript)
    return SimpleNamespace(asked=asked, split=lambda: _split_into(monkeypatch, tmp_path, 3))


@pytest.mark.parametrize("kind", ["sync", "approved"])
@pytest.mark.parametrize("split", [False, True], ids=["single", "split"])
def test_a_silent_video_counts_as_a_recording_through_the_real_connector(
    db, silent_youtube, youtube_network, whisper_api, monkeypatch, kind, split  # noqa: F811
):
    """Down YouTube's own path: the real `YouTubeConnector`, `fetch_transcript`
    and Whisper paths, with only the network fake. A try/except on the way up
    that turned the exception into None would let the second video through."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", 600)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    if split:
        silent_youtube.split()

    _run_two_videos(db, kind, youtube_network)

    assert silent_youtube.asked == [True, False]
    assert whisper_api.sent == (3 if split else 1)


@pytest.mark.parametrize("kind", ["sync", "approved"])
@pytest.mark.parametrize("cap_minutes, next_allowed", [(5, False), (6, True)])
def test_a_silent_video_charges_what_whisper_heard_through_the_real_connector(
    db, silent_youtube, youtube_network, whisper_api, monkeypatch, kind, cap_minutes, next_allowed  # noqa: F811
):
    """300 s heard of a video that declares 10 minutes: a 5-minute cap is
    spent, and a 6-minute one, which the declared length would have spent, is
    not."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)

    _run_two_videos(db, kind, youtube_network)

    assert silent_youtube.asked == [True, next_allowed]
    assert whisper_api.sent == (2 if next_allowed else 1)


# ---------------------------------------------------------------------------
# T-1.7.1.8: an episode Whisper answered with words and no segments
#
# The podcast single-file path dropped such an answer, and since #430 charged
# it as empty, so the episode was paid for and its words lost. It is now kept
# as pseudo-segments (YouTube's helper), an ordinary transcription: read,
# charged once to the count and by what Whisper heard to the minute cap, and
# never also as empty. Through the real connector, with the OpenAI client as
# the only fake (`whisper_api`), so no request leaves.
#
# Mutation check: take the pseudo-segment fallback out of
# `_whisper_transcribe_audio` and each episode reads unavailable: the run
# fails and the status assertions below fail with it.
# ---------------------------------------------------------------------------


def test_a_text_only_episode_is_read_and_counts_once(db, tasks, whisper_api, monkeypatch):  # noqa: F811
    """Two recordings allowed and three episodes: the first two are read and
    the third waits. Charged twice each (as read and as empty), the second
    would have waited too."""
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 2)
    _single_episodes(monkeypatch, whisper_api, episodes=3)
    whisper_api.text_only = True
    job_id = _approved(db, [None, None, None])

    _resume(job_id)

    assert whisper_api.sent == 2
    db.expire_all()
    assert db.get(Job, job_id).status == "completed"
    docs = db.query(Document).order_by(Document.source_id).all()
    assert [d.transcript_status for d in docs] == ["fetched", "fetched", "unavailable"]
    assert [d.transcript_source for d in docs[:2]] == ["podcast_whisper", "podcast_whisper"]
    assert docs[0].transcript_word_count == 60, "the words Whisper sent are kept: 300 s, a word every 5 s"


@pytest.mark.parametrize("cap_minutes, requests", [(5, 1), (6, 2)])
def test_a_text_only_episode_counts_what_whisper_heard_against_the_minute_cap(
    db, tasks, whisper_api, monkeypatch, cap_minutes, requests  # noqa: F811
):
    """300 s heard: its pseudo-segments end there, so a 5-minute cap is spent
    by the first episode and a 6-minute one is not."""
    monkeypatch.setattr(settings, "WHISPER_MAX_MINUTES_PER_JOB", cap_minutes)
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)
    _single_episodes(monkeypatch, whisper_api)
    whisper_api.text_only = True
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert whisper_api.sent == requests
    db.expire_all()
    statuses = [d.transcript_status for d in db.query(Document).order_by(Document.source_id)]
    assert statuses[0] == "fetched"


def test_a_text_only_episode_is_never_also_charged_as_empty(db, tasks, whisper_api, monkeypatch):  # noqa: F811
    """The one connector answer is the transcript: ``_fetch_text`` sees no
    ``PaidTranscriptionLost``, so ``charge_part`` is never called."""
    _single_episodes(monkeypatch, whisper_api)
    whisper_api.text_only = True
    parts: list[float] = []
    charged: list[float] = []
    real_charge = job_tasks.WhisperMinutes.charge
    monkeypatch.setattr(job_tasks.WhisperMinutes, "charge_part", lambda self, seconds: parts.append(seconds))

    def charge(self, document, extracted):
        charged.append(document.source_id)
        real_charge(self, document, extracted)

    monkeypatch.setattr(job_tasks.WhisperMinutes, "charge", charge)
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert charged == ["podcast:ep-0", "podcast:ep-1"]
    assert parts == []


def test_an_episode_with_no_words_at_all_is_still_charged_as_empty(db, tasks, whisper_api, monkeypatch):  # noqa: F811
    """T-1.7.1.7 unchanged beside it: no text at all stays TranscriptionEmpty."""
    _single_episodes(monkeypatch, whisper_api)
    whisper_api.silent = True
    parts: list[float] = []
    monkeypatch.setattr(job_tasks.WhisperMinutes, "charge_part", lambda self, seconds: parts.append(seconds))
    job_id = _approved(db, [None, None])

    _resume(job_id)

    assert parts == [300.0, 300.0]
    db.expire_all()
    assert [d.transcript_status for d in db.query(Document)] == ["unavailable", "unavailable"]

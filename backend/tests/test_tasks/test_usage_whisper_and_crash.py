"""Whisper seconds and a dying worker, at the Celery callers (T-5.2.12, T-5.2.13).

The task bodies run with only the network replaced: the YouTube client
(``youtube_network``), the caption fetch, the audio download and the OpenAI
client below ``_whisper_transcribe_with_retry`` (``whisper_api``). A crash is
``WorkerDied``: a ``BaseException``, so no handler in a task catches it, raised
after emptying the ledger, which is what a dead process leaves behind. Its
``finally`` still runs here, so the tests take the orphan backstop out; the
meter's close finds nothing to write, and ``db.close()`` rolls back what the
dead process had not committed.

Mutation checks, pinned below: with ``checkpoint`` a no-op a killed run leaves
nothing (``test_mutation_a_loop_without_its_checkpoint_loses_the_killed_run``),
and with no try after a model call a killed report leaves nothing
(``test_mutation_a_model_call_that_tries_no_checkpoint_loses_the_report``).
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents.report_agent import _map_in_context
from app.config import settings
from app.models.api_quota_log import ApiQuotaLog
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import usage_service, youtube_service
from app.tasks import job_tasks
from tests.test_tasks.test_usage_metering_tasks import CHANNEL, _channel_responses, _owner
from tests.usage_helpers import (  # noqa: F401
    call_llm,
    flush_always_due,
    metered_llms,
    tenants_with_usage,
    usage_rows,
    whisper_api,
    youtube_network,
)

WHISPER = ("ingest", "whisper_seconds")


class WorkerDied(BaseException):
    pass


def _kill_worker() -> None:
    usage_service.current_scope().ledger.drain()
    raise WorkerDied


def _die_at_request(n: int):
    """As Whisper request ``n`` goes out. Requests before it were answered."""

    def before_send(api) -> None:
        if api.sent == n - 1:
            _kill_worker()

    return before_send


def _fake_download(video_id, tmpdir, tag, prefer_smallest=False):
    path = os.path.join(tmpdir, f"{video_id}.m4a")
    with open(path, "wb") as f:
        f.write(b"fake audio bytes")
    return path


def _writes(data: bytes):
    """A ``fetch_audio_to_file`` that delivers ``data`` to the path it is given."""

    def fetch(url, path):
        with open(path, "wb") as f:
            f.write(data)
        return len(data)

    return fetch


def _split_into(monkeypatch, tmp_path, count: int, step: float = 285.0) -> None:
    """Every download is over the upload limit and splits into ``count`` chunks."""
    chunks = [tmp_path / f"chunk{i}.m4a" for i in range(count)]
    for c in chunks:
        c.write_bytes(b"x")
    monkeypatch.setattr(youtube_service, "WHISPER_MAX_FILE_BYTES", 4)
    monkeypatch.setattr(youtube_service, "_split_audio_for_whisper",
                        lambda path, tmpdir, tag: [(str(c), i * step) for i, c in enumerate(chunks)])


@pytest.fixture
def clock(monkeypatch):
    """Moves only when a test moves it, so a try lands where the test puts it
    and pool threads never write at once on the suite's one connection."""
    time = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(usage_service, "_clock", lambda: time.now)
    return time


@pytest.fixture
def no_captions(monkeypatch, db):
    """Every caption fetch fails, so ``fetch_transcript`` reaches Whisper."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(job_tasks, "progress_service", MagicMock())
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    monkeypatch.setattr(youtube_service, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(youtube_service, "transcript_breaker", youtube_service._TranscriptCircuitBreaker())
    monkeypatch.setattr(youtube_service, "_fetch_transcript_once", lambda *a, **k: None)
    monkeypatch.setattr(youtube_service, "_download_audio_with_ladder", _fake_download)
    monkeypatch.setattr(youtube_service, "get_default_audio_languages", lambda ids, job_id="": {})
    monkeypatch.setattr(youtube_service.time, "sleep", lambda _: None)


def _sync_job(db, owner):
    job = Job(job_type="subscription", num_videos=1, channel_list=json.dumps([CHANNEL]), tenant_id=owner.id)
    db.add(job)
    db.commit()
    return job


def _run_sync(job) -> None:
    with patch.object(job_tasks, "chroma_service") as chroma:
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.execute_subscription_job.run(job.id)


def _run_until_killed(monkeypatch, run) -> None:
    with monkeypatch.context() as m:
        m.setattr(job_tasks, "_backstop_orphan", lambda *a: None)
        with pytest.raises(WorkerDied):
            run()


def _units(rows) -> int:
    return sum(amount for (_, metric), amount in rows.items() if metric == "youtube_units")


def _logged_units(db) -> int:
    db.expire_all()
    return sum(r.units for r in db.query(ApiQuotaLog))


# ---------------------------------------------------------------- Whisper at its callers


def test_a_sync_charges_its_whisper_fallback_to_the_subscriber(no_captions, db, youtube_network, whisper_api):
    owner = _owner(db)
    job = _sync_job(db, owner)
    youtube_network.responses = _channel_responses(["vWhisper001", "vWhisper002"])
    whisper_api.seconds = 61.4

    _run_sync(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert whisper_api.sent == 2
    assert usage_rows(db, owner.id)[WHISPER] == 122
    assert tenants_with_usage(db) == {owner.id}


def test_a_split_recording_is_charged_per_chunk_overlap_included(no_captions, db, whisper_api, monkeypatch, tmp_path):
    """The overlap between chunks is sent twice, so it is billed twice."""
    owner = _owner(db)
    _split_into(monkeypatch, tmp_path, 3)
    whisper_api.seconds = 300.0

    with usage_service.metered(db, owner.id):
        out = youtube_service._transcribe_with_whisper("vLong000001", job_id="j")

    assert out is not None
    assert usage_rows(db, owner.id) == {WHISPER: 900}


def test_a_chunk_that_fails_leaves_the_chunks_already_billed_on_the_record(no_captions, db, whisper_api, monkeypatch, tmp_path):
    owner = _owner(db)
    _split_into(monkeypatch, tmp_path, 3, step=0.0)

    def fail_second(api):
        if api.sent == 1:
            raise RuntimeError("upstream broke")

    whisper_api.before_send = fail_second

    with usage_service.metered(db, owner.id):
        assert youtube_service._transcribe_with_whisper("vLong000002") is None

    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_a_retried_request_is_charged_for_the_response_only(no_captions, db, whisper_api):
    from openai import APIConnectionError

    owner = _owner(db)
    failures = [APIConnectionError(request=MagicMock())]

    def fail_once(api):
        if failures:
            raise failures.pop()

    whisper_api.before_send = fail_once

    with usage_service.metered(db, owner.id):
        assert youtube_service._transcribe_with_whisper("vRetry00001") is not None

    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_captions_and_cached_transcripts_record_no_audio(no_captions, db, whisper_api, monkeypatch):
    owner = _owner(db)
    segments = [{"text": "hello there", "start": 0.0, "duration": 1.0}]
    monkeypatch.setattr(youtube_service, "_fetch_transcript_once", lambda *a, **k: (segments, "en", None))

    with usage_service.metered(db, owner.id):
        assert youtube_service.fetch_transcript("vCaption001").source == "youtube"
        assert youtube_service.fetch_transcript("vCaption001") is not None  # the cache

    assert whisper_api.sent == 0
    assert usage_rows(db, owner.id) == {}


def test_a_run_past_its_whisper_budget_records_no_audio(no_captions, db, whisper_api):
    owner = _owner(db)
    with usage_service.metered(db, owner.id):
        assert youtube_service.fetch_transcript("vNoBudget01", allow_whisper=False) is None
    assert whisper_api.sent == 0
    assert usage_rows(db, owner.id) == {}


# ---------------------------------------------------------------- a dying worker


def test_a_killed_sync_keeps_what_it_flushed_and_its_redelivery_adds_only_its_own(
    no_captions, db, youtube_network, whisper_api, flush_always_due, monkeypatch
):
    owner = _owner(db)
    job = _sync_job(db, owner)
    youtube_network.responses = _channel_responses(["vKill000001", "vKill000002", "vKill000003"])
    whisper_api.before_send = _die_at_request(2)

    _run_until_killed(monkeypatch, lambda: _run_sync(job))

    db.expire_all()
    assert db.get(Job, job.id).status == "extracting", "a dead worker records nothing about itself"
    assert whisper_api.sent == 1
    rows = usage_rows(db, owner.id)
    assert rows[WHISPER] == 60, "the finished video's audio was flushed before the kill"
    assert _units(rows) == _logged_units(db) > 0, "so were the walk's YouTube units"

    # Tasks ack late: the broker hands the same job to the next worker.
    whisper_api.before_send = None
    _run_sync(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert whisper_api.sent == 3, "the finished video is reused, the other two transcribed"
    rows = usage_rows(db, owner.id)
    assert rows[WHISPER] == 180, "a video charged twice, or one lost"
    assert _units(rows) == _logged_units(db), "the meter and the install-wide log disagree"


def test_a_sync_killed_on_its_first_video_keeps_the_walks_youtube_units(
    no_captions, db, youtube_network, whisper_api, flush_always_due, monkeypatch
):
    owner = _owner(db)
    job = _sync_job(db, owner)
    youtube_network.responses = _channel_responses(["vWalk000001"])
    whisper_api.before_send = _die_at_request(1)

    _run_until_killed(monkeypatch, lambda: _run_sync(job))

    rows = usage_rows(db, owner.id)
    assert WHISPER not in rows
    assert _units(rows) == _logged_units(db) > 0


def test_a_split_recording_keeps_its_billed_chunks_when_the_worker_dies_inside_it(
    no_captions, db, youtube_network, whisper_api, flush_always_due, monkeypatch, tmp_path
):
    """A long upload is one iteration of the loop and has no model call in it,
    so the try after each response is all that stands between the chunks
    already billed and a dead worker."""
    owner = _owner(db)
    job = _sync_job(db, owner)
    youtube_network.responses = _channel_responses(["vSplit00001"])
    _split_into(monkeypatch, tmp_path, 4)
    whisper_api.before_send = _die_at_request(3)

    _run_until_killed(monkeypatch, lambda: _run_sync(job))

    assert whisper_api.sent == 2
    assert usage_rows(db, owner.id)[WHISPER] == 120, "the billed chunks went with the worker"

    # The transcript was never cached, so the redelivery sends all four again
    # and pays for them again.
    whisper_api.before_send = None
    _run_sync(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert whisper_api.sent == 6
    assert usage_rows(db, owner.id)[WHISPER] == 360, "either attempt's bill is missing"


def test_flushing_all_the_way_records_what_writing_at_the_end_records(
    no_captions, db, youtube_network, whisper_api, flush_always_due, monkeypatch
):
    at_the_end = _owner(db)
    job = _sync_job(db, at_the_end)
    youtube_network.responses = _channel_responses(["vEnd0000001", "vEnd0000002"])
    with monkeypatch.context() as m:
        m.setattr(settings, "USAGE_FLUSH_INTERVAL_SECONDS", 0)
        _run_sync(job)

    part_way = _owner(db)
    job = _sync_job(db, part_way)
    youtube_network.responses = _channel_responses(["vWay0000001", "vWay0000002"])
    _run_sync(job)

    rows = usage_rows(db, part_way.id)
    assert rows == usage_rows(db, at_the_end.id)
    assert rows[WHISPER] == 120


def _approved_job(db, owner, video_ids):
    job = Job(job_type="topic", topic="tariffs", num_videos=len(video_ids), status="awaiting_approval",
              tenant_id=owner.id)
    db.add(job)
    db.flush()
    for vid in video_ids:
        doc = Document(video_id=vid, source_id=vid, title=vid, url=f"https://www.youtube.com/watch?v={vid}")
        db.add(doc)
        db.flush()
        db.add(JobVideo(job_id=job.id, video_id=vid, document_id=doc.document_id, approved=True))
    db.commit()
    return job


def test_a_job_charges_podcast_audio_to_its_owner_as_reading_a_source(no_captions, db, whisper_api, monkeypatch):
    """The third Whisper path, at its caller: the task's own scope is what
    catches an episode, ``fetch_text`` opens none."""
    from app.sources.podcast import connector

    owner = _owner(db)
    feed_url = "https://example.com/feed.xml"
    entry = {"id": "ep-1", "title": "Tariffs", "enclosures": [{"href": "https://example.com/ep.mp3"}]}
    monkeypatch.setattr(connector.settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(connector.podcast_client, "get_client", lambda: SimpleNamespace(
        fetch_feed=lambda url: {"feed": {}, "entries": [entry] if url == feed_url else []},
        fetch_audio_to_file=_writes(b"mp3 bytes"),
    ))
    whisper_api.seconds = 1800.0
    doc = Document(source_type="podcast_episode", source_id="podcast:ep-1", title="Tariffs",
                   url="https://example.com/ep", channel_id=feed_url)
    job = Job(job_type="topic", topic="tariffs", num_videos=1, status="awaiting_approval", tenant_id=owner.id)
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, approved=True))
    db.commit()

    _run_resume(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert db.get(Document, doc.document_id).transcript_source == "podcast_whisper"
    assert whisper_api.sent == 1
    assert usage_rows(db, owner.id) == {WHISPER: 1800}
    assert tenants_with_usage(db) == {owner.id}


def test_a_job_reads_a_long_episode_whole_and_charges_every_chunk(no_captions, db, whisper_api, monkeypatch, tmp_path):
    """Past Whisper's upload cap an episode used to be lost after approval, and
    a run of them ended failed with "No transcripts could be fetched". At the
    extraction task: all of it is read, and each chunk is charged to the owner."""
    from app.sources.podcast import connector

    owner = _owner(db)
    feed_url = "https://example.com/feed.xml"
    entry = {"id": "ep-1", "title": "Tariffs", "enclosures": [{"href": "https://example.com/ep.mp3"}]}
    monkeypatch.setattr(connector.settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(connector.podcast_client, "get_client", lambda: SimpleNamespace(
        fetch_feed=lambda url: {"feed": {}, "entries": [entry] if url == feed_url else []},
        fetch_audio_to_file=_writes(b"far too many mp3 bytes"),
    ))
    _split_into(monkeypatch, tmp_path, 3)
    whisper_api.seconds = 300.0
    whisper_api.segment_start = 100.0
    doc = Document(source_type="podcast_episode", source_id="podcast:ep-1", title="Tariffs",
                   url="https://example.com/ep", channel_id=feed_url)
    job = Job(job_type="topic", topic="tariffs", num_videos=1, status="awaiting_approval", tenant_id=owner.id)
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, approved=True))
    db.commit()

    _run_resume(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert db.get(Document, doc.document_id).transcript_source == "podcast_whisper"
    assert whisper_api.sent == 3, "one request per chunk, never the whole file"
    assert usage_rows(db, owner.id) == {WHISPER: 900}
    stored = json.loads(db.get(TranscriptCache, doc.document_id).segments_json)
    assert [(s["text"], s["start"]) for s in stored] == [
        ("spoken words 1", 100.0),
        ("spoken words 2", 385.0),
        ("spoken words 3", 670.0),
    ]


def _run_resume(job, report=None) -> None:
    with (
        patch.object(job_tasks, "chroma_service") as chroma,
        patch("app.agents.report_agent.run_report_agent", side_effect=report or (lambda **k: ({}, "<p>report</p>"))),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.resume_job_after_approval.run(job.id)


def test_a_job_killed_during_extraction_keeps_what_it_flushed_and_its_redelivery_adds_only_its_own(
    no_captions, db, whisper_api, flush_always_due, monkeypatch
):
    owner = _owner(db)
    job = _approved_job(db, owner, ["vJobKill001", "vJobKill002", "vJobKill003"])
    whisper_api.before_send = _die_at_request(2)

    _run_until_killed(monkeypatch, lambda: _run_resume(job))

    assert usage_rows(db, owner.id) == {WHISPER: 60}

    whisper_api.before_send = None
    _run_resume(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert whisper_api.sent == 3
    assert usage_rows(db, owner.id) == {WHISPER: 180}


def _sync_of(db, owner, youtube_network, video_ids):
    youtube_network.responses = _channel_responses(video_ids)
    return _sync_job(db, owner), _run_sync


def _approved_job_of(db, owner, youtube_network, video_ids):
    return _approved_job(db, owner, video_ids), _run_resume


LOOPS = pytest.mark.parametrize("loop", [_sync_of, _approved_job_of], ids=["sync", "approved_job"])


def _killed_with_the_interval_passing_after_the_audio(loop, db, youtube_network, whisper_api, clock, monkeypatch):
    """The first video's audio comes back too soon for a write, the rest of its
    iteration takes longer than the interval, and the worker dies in the second
    video's request. Only the loop's own checkpoint can have written the first."""
    owner = _owner(db)
    job, run = loop(db, owner, youtube_network, ["vLoop000001", "vLoop000002"])
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: setattr(clock, "now", clock.now + 3600))
    whisper_api.before_send = _die_at_request(2)

    _run_until_killed(monkeypatch, lambda: run(job))

    assert whisper_api.sent == 1
    return owner


@LOOPS
def test_a_loop_writes_at_the_end_of_a_video_what_the_response_was_too_early_for(
    loop, no_captions, db, youtube_network, whisper_api, clock, monkeypatch
):
    owner = _killed_with_the_interval_passing_after_the_audio(loop, db, youtube_network, whisper_api, clock, monkeypatch)
    assert usage_rows(db, owner.id)[WHISPER] == 60


@LOOPS
def test_mutation_a_loop_without_its_checkpoint_loses_the_killed_run(
    loop, no_captions, db, youtube_network, whisper_api, clock, monkeypatch
):
    monkeypatch.setattr(usage_service, "checkpoint", lambda: False)
    owner = _killed_with_the_interval_passing_after_the_audio(loop, db, youtube_network, whisper_api, clock, monkeypatch)
    assert usage_rows(db, owner.id) == {}


def _report_job(db, owner):
    doc = Document(video_id="vRepKill001", source_id="vRepKill001", title="Tariffs",
                   url="https://www.youtube.com/watch?v=vRepKill001", transcript_status="fetched")
    job = Job(job_type="topic", topic="tariffs", num_videos=1, status="awaiting_approval", tenant_id=owner.id)
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=doc.video_id, document_id=doc.document_id, approved=True))
    db.add(TranscriptCache(video_id=doc.video_id, language="en",
                           segments_json=json.dumps([{"text": "Tariffs are taxes.", "start": 0.0, "duration": 3.0}])))
    db.commit()
    return job


def _report_that_dies(clock):
    def report_agent(**kwargs):
        with ThreadPoolExecutor(max_workers=2) as pool:
            _map_in_context(pool, lambda i: call_llm("report_map_chunks", str(i)), range(3))
        clock.now += 3600
        call_llm("report_reduce_summaries")
        _kill_worker()

    return report_agent


def test_a_worker_killed_during_a_report_keeps_the_model_calls_it_had_made(
    no_captions, db, metered_llms, clock, monkeypatch
):
    """The report has no loop of the task's: the meter's own try after each
    model call is what saves the map phase, the most expensive part of a job."""
    owner = _owner(db)
    job = _report_job(db, owner)

    _run_until_killed(monkeypatch, lambda: _run_resume(job, _report_that_dies(clock)))

    assert usage_rows(db, owner.id) == {
        ("report", "llm_calls"): 4, ("report", "llm_tokens_in"): 400, ("report", "llm_tokens_out"): 80,
    }


def test_mutation_a_model_call_that_tries_no_checkpoint_loses_the_report(
    no_captions, db, metered_llms, clock, monkeypatch
):
    monkeypatch.setattr(usage_service, "_checkpoint", lambda scope: False)
    owner = _owner(db)
    job = _report_job(db, owner)

    _run_until_killed(monkeypatch, lambda: _run_resume(job, _report_that_dies(clock)))

    assert usage_rows(db, owner.id) == {}

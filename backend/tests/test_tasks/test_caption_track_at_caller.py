"""S-1.11.11 at the production caller: a job ingests a dubbed Hindi video.

`execute_subscription_job` runs for real through the YouTube connector and
`youtube_service.fetch_transcript`; only the network is replaced (the
player response and timedtext served by `FakeTranscriptApi`, the Data API
lookups). The Hindi lecture `1v3_AQ26jZ0` was ingested as its Bengali dub
before this story; here the document, the transcript cache and the chunks
handed to Chroma must all hold the speaker's Hindi.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.transcript_cache import TranscriptCache
from app.services import youtube_service
from app.tasks import job_tasks
from tests.caption_track_fixtures import SHAPES, TRACK_TEXT, FakeTranscriptApi

CHANNEL = "UCcaptionTrack01"
SHAPE = SHAPES["hindi_audio_bengali_and_english_dubs"]


class _NoWait:
    def wait(self) -> None:
        return None


@pytest.fixture
def caller(monkeypatch, db):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    # The transcript cache is written through youtube_service's own session.
    monkeypatch.setattr(youtube_service, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(youtube_service, "transcript_limiter", _NoWait())
    monkeypatch.setattr(youtube_service, "transcript_breaker", youtube_service._TranscriptCircuitBreaker())
    monkeypatch.setattr(youtube_service, "_transcribe_with_whisper", lambda vid, job_id="": None)
    # Era extraction is an LLM call; not this test's subject.
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)

    api = FakeTranscriptApi(SHAPE.captions())
    monkeypatch.setattr(youtube_service, "_build_transcript_api", lambda: api)
    monkeypatch.setattr(
        youtube_service, "get_default_audio_languages",
        lambda ids, job_id="": {vid: SHAPE.declared for vid in ids},
    )

    details = {
        SHAPE.video_id: {
            "video_id": SHAPE.video_id,
            "title": "AI Vs ML Vs DL for Beginners in Hindi",
            "channel_name": "Lecture Channel",
            "channel_id": CHANNEL,
            "url": f"https://www.youtube.com/watch?v={SHAPE.video_id}",
            "duration_seconds": 600,
            "thumbnail_url": None,
            "published_at": None,
        }
    }
    monkeypatch.setattr(youtube_service, "resolve_channel_id", lambda c, **kw: CHANNEL)
    monkeypatch.setattr(
        youtube_service, "get_channel_metadata",
        lambda c, **kw: {
            "channel_id": CHANNEL, "name": "Lecture Channel",
            "uploads_playlist_id": "UUcaptionTrack01", "subscriber_count": 10,
        },
    )
    monkeypatch.setattr(youtube_service, "get_channel_videos_all", lambda c, **kw: [SHAPE.video_id])
    monkeypatch.setattr(youtube_service, "get_video_details", lambda ids, **kw: details)

    job = Job(job_type="subscription", topic=None, num_videos=1,
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-caption")
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job": job, "api": api}


def _run(job_id: str) -> MagicMock:
    with patch.object(job_tasks, "chroma_service") as chroma, patch.object(job_tasks, "progress_service"):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.execute_subscription_job.run(job_id)
    return chroma


def test_job_ingests_the_spoken_hindi_track_not_the_bengali_dub(caller, db):
    chroma = _run(caller["job"].id)

    doc = db.query(Document).filter(Document.video_id == SHAPE.video_id).one()
    assert doc.transcript_status == "fetched"
    assert doc.transcript_language == "hi"
    assert doc.transcript_source == "youtube"

    track = json.loads(doc.source_metadata_json)["caption_track"]
    assert track["language"] == "hi"
    assert track["kind"] == "asr"
    assert track["match"] == "spoken"
    assert track["spoken_language"] == "hi"
    assert track["skipped_dubbed"] == ["bn", "en-US"]

    cached = db.query(TranscriptCache).filter(TranscriptCache.video_id == SHAPE.video_id).one()
    assert cached.language == "hi"
    assert json.loads(cached.segments_json)[0]["text"] == TRACK_TEXT["hi"]

    chunks = chroma.insert_chunks.call_args[0][0]
    text = " ".join(c["text"] for c in chunks)
    assert TRACK_TEXT["hi"] in text
    assert TRACK_TEXT["bn"] not in text
    # Only the chosen track was downloaded.
    assert caller["api"].fetched == ["hi"]


def test_mutation_the_old_rule_would_have_ingested_the_dub(caller, db, monkeypatch):
    """Mutation check: put the pre-S-1.11.11 rule back at the same seam and
    the caller ends up with the Bengali dub — so the test above fails on it."""

    def old_rule(tracks, *, spoken_language, dubbed=frozenset(), preferred_language="en"):
        for code in (preferred_language, "en"):
            for t in [t for t in tracks if not t.is_generated] + [t for t in tracks if t.is_generated]:
                if t.language_code == code:
                    return t, "old", ()
        ordered = [t for t in tracks if not t.is_generated] + [t for t in tracks if t.is_generated]
        return ordered[0], "old", ()

    monkeypatch.setattr(youtube_service, "choose_caption_track", old_rule)
    _run(caller["job"].id)

    doc = db.query(Document).filter(Document.video_id == SHAPE.video_id).one()
    assert doc.transcript_language == "bn"

"""T-1.16.1.7 at the production caller: a job that chunks a document stores
its language profile on ``documents.language_mix``.

The jobs run for real through the YouTube connector, as in
``test_caption_track_at_caller``; only the network is replaced. The profile
on the document must be the one the chunks were built from: the chunks
handed to Chroma carry the same ``code_mix_*`` fields the stored profile
yields.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import code_mixing_service, language_mix_service, youtube_service
from app.tasks import job_tasks
from tests.caption_track_fixtures import SHAPES, TRACK_TEXT, FakeTranscriptApi

CHANNEL = "UClanguageMix001"
SHAPE = SHAPES["hindi_audio_bengali_and_english_dubs"]


class _NoWait:
    def wait(self) -> None:
        return None


@pytest.fixture
def caller(monkeypatch, db):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
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
            "uploads_playlist_id": "UUlanguageMix001", "subscriber_count": 10,
        },
    )
    monkeypatch.setattr(youtube_service, "get_channel_videos_all", lambda c, **kw: [SHAPE.video_id])
    monkeypatch.setattr(youtube_service, "get_video_details", lambda ids, **kw: details)

    job = Job(job_type="subscription", topic=None, num_videos=1,
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-language-mix")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _run_subscription(job_id: str) -> MagicMock:
    with patch.object(job_tasks, "chroma_service") as chroma, patch.object(job_tasks, "progress_service"):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.execute_subscription_job.run(job_id)
    return chroma


def _resume(job_id: str) -> MagicMock:
    with (
        patch.object(job_tasks, "chroma_service") as chroma,
        patch.object(job_tasks, "progress_service"),
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.resume_job_after_approval.run(job_id)
    return chroma


def _doc(db) -> Document:
    db.expire_all()
    return db.query(Document).filter(Document.video_id == SHAPE.video_id).one()


def _chunk_code_mix(chunks: list[dict]) -> dict:
    """The document-level code_mix_* fields every chunk carries."""
    keys = ("code_mix_primary", "code_mix_script", "code_mix_share",
            "code_mix_matrix_share", "code_mix_quote")
    fields = {tuple(sorted((k, c["metadata"].get(k)) for k in keys)) for c in chunks}
    assert len(fields) == 1, "chunks of one document disagree on its profile"
    return dict(fields.pop())


def test_a_subscription_ingest_stores_the_profile_its_chunks_carry(caller, db):
    chroma = _run_subscription(caller.id)

    doc = _doc(db)
    stored = json.loads(doc.language_mix)
    assert stored["primary_language"] == "hi"
    assert stored["native_script"] == "Devanagari"
    assert stored["quote_mode"] == "native_script"
    assert stored["hi_share"] == 1.0
    # The full profile_transcript result, from the text that was chunked.
    cached = db.query(TranscriptCache).filter(TranscriptCache.video_id == SHAPE.video_id).one()
    assert stored == code_mixing_service.profile_transcript(json.loads(cached.segments_json))

    chunks = chroma.insert_chunks.call_args[0][0]
    assert TRACK_TEXT["hi"] in " ".join(c["text"] for c in chunks)
    assert _chunk_code_mix(chunks) == code_mixing_service.chunk_metadata_from_profile(stored)


def test_mutation_without_the_wiring_the_document_stays_unprofiled(caller, db, monkeypatch):
    """Mutation check: put the pre-T-1.16.1.7 behaviour back at the seam (no
    profile stored; the chunker profiles the transcript itself). The chunks
    still carry the profile, but the document has none, so the test above
    fails on it."""
    monkeypatch.setattr(job_tasks.language_mix_service, "ensure", lambda doc, segments: None)
    chroma = _run_subscription(caller.id)

    assert _doc(db).language_mix is None
    chunks = chroma.insert_chunks.call_args[0][0]
    assert _chunk_code_mix(chunks)["code_mix_primary"] == "hi"


@pytest.fixture
def approved_job(caller, db):
    """A channel job whose user approved the lecture (the topic and channel
    job path, `resume_job_after_approval`)."""
    doc = Document(
        video_id=SHAPE.video_id, source_id=SHAPE.video_id,
        title="AI Vs ML Vs DL for Beginners in Hindi",
        url=f"https://www.youtube.com/watch?v={SHAPE.video_id}",
    )
    job = Job(job_type="channel", topic=None, num_videos=1, status="awaiting_approval",
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-language-mix")
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=SHAPE.video_id, document_id=doc.document_id, approved=True))
    db.commit()
    return job


def test_an_approved_job_stores_the_profile(approved_job, caller, db):
    chroma = _resume(approved_job.id)

    stored = language_mix_service.load(_doc(db))
    assert stored is not None and stored["primary_language"] == "hi"
    chunks = chroma.insert_chunks.call_args[0][0]
    assert _chunk_code_mix(chunks) == code_mixing_service.chunk_metadata_from_profile(stored)


def test_a_reused_library_document_gains_its_profile(approved_job, caller, db):
    """A document chunked before T-1.16.1.7 (fetched, embedded, no profile)
    is profiled the next time a job reuses it, from the cached transcript,
    without being re-embedded."""
    doc = _doc(db)
    segments = [{"text": TRACK_TEXT["hi"], "start": 0.0, "duration": 2.5}]
    db.add(TranscriptCache(document_id=doc.document_id, video_id=SHAPE.video_id,
                           segments_json=json.dumps(segments), language="hi", source="youtube"))
    doc.transcript_status = "fetched"
    doc.embedded_in_chroma = True
    db.commit()

    chroma = _resume(approved_job.id)

    stored = language_mix_service.load(_doc(db))
    assert stored == code_mixing_service.profile_transcript(segments)
    chroma.insert_chunks.assert_not_called()  # reused: nothing re-embedded


def test_every_chunking_site_in_the_job_loops_stores_the_profile_first():
    """Source-level guard, like the era one: each `chunk_transcript(...)` in
    the ingest loops is preceded by `language_mix_service.ensure(video, X)`
    for the segments it chunks and is handed that profile. A new ingest path
    that forgets it fails here."""
    src = Path(job_tasks.__file__).read_text(encoding="utf-8")
    sites = list(re.finditer(
        r"language_profile = language_mix_service\.ensure\(video, (\w+)\)\n"
        r"\s+_ensure_era\(db, video, (\w+), job_id\)\n"
        r"\s+chunks = chunk_transcript\(\n"
        r"\s+_with_visuals\(db, job, video, (\w+),[^\n]*\n"
        r"(?:\s+[^\n]*\n){0,4}?"
        r"\s+language_profile=language_profile,\n",
        src,
    ))
    total = len(re.findall(r"chunks = chunk_transcript\(", src))
    assert total >= 6
    assert len(sites) == total, "a chunk_transcript site does not store the language profile"
    assert all(m.group(1) == m.group(2) == m.group(3) for m in sites), (
        "profile computed from different segments than chunked"
    )

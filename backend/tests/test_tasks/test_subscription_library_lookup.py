"""T-1.11.11.6 at ``execute_subscription_job``: a video the library already holds
costs no details read, and is still linked and granted.

``db.get(Document, vid)`` compared a YouTube id with the UUID primary key, so
every unlinked video counted as missing and every sync re-read its whole
channel. Once the check works, a video another tenant ingested is no longer in
the details, so the code below it has to link it and grant it (D-063) from what
the library holds, and must not build a row from details that are absent: the
default title "Unknown" would replace the real one for every tenant.

Mutation check: put ``db.get(Document, vid) is None`` back in the task and
``test_a_sync_reads_details_only_for_what_the_library_lacks`` fails on
``fetch_metadata``, which then gets all the unlinked ids. Put the
``info.get("title", "Unknown")`` row back and
``test_a_library_document_keeps_what_it_knows`` fails on the title.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import visibility_service, youtube_service
from app.sources.types import DEFAULT_AUDIO_LANGUAGE
from app.sources.video.connector import YouTubeConnector
from app.tasks import job_tasks

CHANNEL = "UClookup000001"
NEW = "vNew0000001"
FOREIGN = "vForeign001"
LINKED = "vLinked0001"
OTHER_TENANT = "tenant-who-got-there-first"
SEGMENTS = [{"text": "spoken words about the topic", "start": 0.0, "duration": 5.0}]


def _details(video_id: str, **over) -> dict:
    return {
        "video_id": video_id,
        "title": f"Details of {video_id}",
        "channel_id": CHANNEL,
        "channel_name": "Lookup Channel",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "duration_seconds": 300,
        "thumbnail_url": f"https://i.ytimg.com/{video_id}.jpg",
        "published_at": "2026-01-01T00:00:00Z",
        **over,
    }


@pytest.fixture
def channel(db, monkeypatch):
    """The task and the real connector; only YouTube's own calls are fakes.
    ``uploads`` is the playlist, ``metadata`` the spy on ``fetch_metadata``."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(job_tasks, "progress_service", MagicMock())
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    monkeypatch.setattr(youtube_service, "resolve_channel_id", lambda c, **kw: CHANNEL)
    monkeypatch.setattr(youtube_service, "get_channel_metadata", lambda c, **kw: {
        "channel_id": CHANNEL, "name": "Lookup Channel",
        "uploads_playlist_id": "UUlookup000001", "subscriber_count": 10,
    })
    monkeypatch.setattr(youtube_service, "fetch_transcript", lambda vid, **kw: (SEGMENTS, "en", "youtube"))

    state = MagicMock()
    state.uploads = [NEW, FOREIGN, LINKED]
    state.details = {NEW: _details(NEW)}
    monkeypatch.setattr(youtube_service, "get_channel_videos_all", lambda c, **kw: state.uploads)
    monkeypatch.setattr(
        youtube_service, "get_video_details",
        lambda ids, job_id="": {vid: state.details[vid] for vid in ids if vid in state.details},
    )
    real = YouTubeConnector.fetch_metadata
    state.metadata = MagicMock(side_effect=lambda ids, job_id="": real(YouTubeConnector(), ids, job_id=job_id))
    monkeypatch.setattr(YouTubeConnector, "fetch_metadata", lambda self, ids, job_id="": state.metadata(ids, job_id=job_id))
    return state


def _library_document(db, video_id: str, tenant_id: str, **over) -> Document:
    """A document another run finished: text cached, chunks embedded."""
    doc = Document(
        video_id=video_id,
        source_id=video_id,
        title=f"The real title of {video_id}",
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel_id="UCitsRealChannel",
        duration_seconds=1234,
        thumbnail_url="https://i.ytimg.com/kept.jpg",
        transcript_status="fetched",
        embedded_in_chroma=True,
        **over,
    )
    db.add(doc)
    db.flush()
    db.add(TranscriptCache(document_id=doc.document_id, video_id=video_id, language="en",
                           segments_json=json.dumps(SEGMENTS), source="youtube"))
    visibility_service.grant(db, [doc.document_id], tenant_id, visibility_service.SOURCE_JOB)
    db.commit()
    return doc


def _sync_job(db, tenant_id: str) -> Job:
    job = Job(job_type="subscription", num_videos=0, channel_list=json.dumps([CHANNEL]), tenant_id=tenant_id)
    db.add(job)
    db.commit()
    return job


def _link(db, job: Job, doc: Document) -> None:
    """What a run of this job that died after the walk left behind."""
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
    db.commit()


def _run(job: Job) -> None:
    with patch.object(job_tasks, "chroma_service") as chroma:
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.execute_subscription_job.run(job.id)


def _visible_videos(db, tenant_id: str) -> set[str]:
    return {
        row[0]
        for row in db.query(Document.video_id)
        .join(DocumentVisibility, DocumentVisibility.document_id == Document.document_id)
        .filter(DocumentVisibility.tenant_id == tenant_id)
    }


def _linked_videos(db, job: Job) -> set[str]:
    return {row[0] for row in db.query(JobVideo.video_id).filter(JobVideo.job_id == job.id)}


def test_a_sync_reads_details_only_for_what_the_library_lacks(db, test_user, channel):
    """One new video, one from another tenant, one this job already linked."""
    _library_document(db, FOREIGN, OTHER_TENANT)
    job = _sync_job(db, test_user.id)
    _link(db, job, _library_document(db, LINKED, OTHER_TENANT))

    _run(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    channel.metadata.assert_called_once_with([NEW], job_id=job.id)
    assert _linked_videos(db, job) == {NEW, FOREIGN, LINKED}
    # The dedup hit is the point of D-063: the bytes existed, this tenant had
    # never seen them, and a sync that skipped the details must still grant it.
    assert _visible_videos(db, test_user.id) == {NEW, FOREIGN, LINKED}
    assert _visible_videos(db, OTHER_TENANT) == {FOREIGN, LINKED}, "the other tenant's grants stand, and gain nothing"


def test_a_library_document_keeps_what_it_knows(db, test_user, channel):
    """No details were read for it, so nothing here may look like they were."""
    doc = _library_document(db, FOREIGN, OTHER_TENANT, source_metadata_json=json.dumps({DEFAULT_AUDIO_LANGUAGE: "hi"}))
    channel.uploads = [FOREIGN]
    job = _sync_job(db, test_user.id)

    _run(job)

    db.expire_all()
    kept = db.get(Document, doc.document_id)
    assert kept.title == f"The real title of {FOREIGN}"
    assert kept.url == f"https://www.youtube.com/watch?v={FOREIGN}"
    assert kept.thumbnail_url == "https://i.ytimg.com/kept.jpg"
    assert kept.duration_seconds == 1234
    assert kept.channel_id == "UCitsRealChannel"
    assert json.loads(kept.source_metadata_json) == {DEFAULT_AUDIO_LANGUAGE: "hi"}
    assert kept.transcript_status == "fetched"


def test_a_channel_the_library_already_holds_costs_no_details_at_all(db, test_user, channel):
    for vid in (NEW, FOREIGN, LINKED):
        _library_document(db, vid, OTHER_TENANT)

    _run(_sync_job(db, test_user.id))

    channel.metadata.assert_not_called()
    assert _visible_videos(db, test_user.id) == {NEW, FOREIGN, LINKED}


def test_a_second_tenants_sync_of_the_same_channel_reads_nothing_again(db, test_user, channel):
    """The saving, end to end: the first sync pays, the second links."""
    channel.uploads = [NEW]
    _run(_sync_job(db, OTHER_TENANT))
    assert channel.metadata.call_count == 1

    _run(_sync_job(db, test_user.id))

    assert channel.metadata.call_count == 1
    assert _visible_videos(db, test_user.id) == {NEW}


def test_a_new_video_the_details_left_out_still_gets_a_row(db, test_user, channel):
    """A private video on the playlist: the defaults are for this case alone."""
    channel.uploads = [NEW]
    channel.details = {}

    _run(_sync_job(db, test_user.id))

    db.expire_all()
    doc = db.query(Document).filter(Document.video_id == NEW).one()
    assert doc.title == "Unknown"
    assert doc.url == f"https://www.youtube.com/watch?v={NEW}"
    assert doc.channel_id == CHANNEL
    assert _visible_videos(db, test_user.id) == {NEW}


def test_a_new_video_keeps_everything_its_details_said(db, test_user, channel):
    channel.uploads = [NEW]
    channel.details = {NEW: _details(NEW, default_audio_language="hi")}

    _run(_sync_job(db, test_user.id))

    db.expire_all()
    doc = db.query(Document).filter(Document.video_id == NEW).one()
    assert doc.title == f"Details of {NEW}"
    assert doc.duration_seconds == 300
    assert doc.thumbnail_url == f"https://i.ytimg.com/{NEW}.jpg"
    assert doc.published_at is not None
    assert json.loads(doc.source_metadata_json)[DEFAULT_AUDIO_LANGUAGE] == "hi"


def test_a_long_uploads_list_is_looked_up_in_batches(db, monkeypatch):
    """SQLite caps the parameters in one statement, and a channel can pass it."""
    monkeypatch.setattr(job_tasks, "_IN_LIST_SIZE", 2)
    _library_document(db, "vA", OTHER_TENANT)
    _library_document(db, "vC", OTHER_TENANT)
    _library_document(db, "vE", OTHER_TENANT)

    assert job_tasks._videos_in_library(db, ["vA", "vB", "vC", "vD", "vE"]) == {"vA", "vC", "vE"}


def test_a_document_of_another_source_type_is_not_a_match(db):
    """``video_id`` is NULL for every non-video source, so nothing can hit one."""
    db.add(Document(source_type="pdf", source_id="pdf:1", title="A PDF", url="https://example.com/1"))
    db.commit()

    assert job_tasks._videos_in_library(db, ["vNotThere"]) == set()

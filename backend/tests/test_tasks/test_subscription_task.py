"""Tests for the channel-subscription Celery task (Unit 5).

`execute_subscription_job` is the auto-run background task that ingests new
videos from a subscribed channel. Unlike topic/channel jobs, subscription
jobs:
  - skip the `awaiting_approval` phase entirely (all videos auto-approved),
  - never generate a report (`report_path` stays None),
  - tag every JobVideo with `selection_reason='subscription'`.
"""
from unittest.mock import MagicMock, patch

import pytest

# Unit 5 dep: the task itself.
job_tasks = pytest.importorskip("app.tasks.job_tasks")
if not hasattr(job_tasks, "execute_subscription_job"):
    pytest.skip(
        "execute_subscription_job not yet merged (pending Unit 5)",
        allow_module_level=True,
    )

# Unit 1/2 deps for data model.
pytest.importorskip("app.models.job_video", reason="pending Unit 1 — JobVideo")
pytest.importorskip("app.models.channel", reason="pending Unit 2 — Channel")

from app.models.channel import Channel  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.job_video import JobVideo  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.sources.video import connector as yt_connector  # noqa: E402


@pytest.fixture
def patch_session_local(monkeypatch, db):
    """Route the task's SessionLocal to the test in-memory session.

    The Celery task calls `SessionLocal()` internally; we monkey-patch the
    symbol in `app.tasks.job_tasks` so it yields the shared StaticPool engine
    test session instead.
    """
    from tests import conftest as _conftest
    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    yield


def _make_subscription_job(db, channel_id: str = "UCsub001") -> Job:
    """Create a Job row representing a subscription ingest. The exact schema
    for 'subscription' job_type is defined in Unit 5; we use the string
    'subscription' consistently."""
    job = Job(
        job_type="subscription",
        topic=None,
        num_videos=3,
        channel_list=f'["{channel_id}"]',
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_execute_subscription_job_auto_completes_without_approval(patch_session_local, db):
    """Verifies the full happy-path: 3 videos ingested, auto-approved,
    chunks inserted, channel marked subscribed, job status=completed,
    no report generated, no awaiting_approval state."""
    channel_id = "UCsubHappyPath"
    job = _make_subscription_job(db, channel_id=channel_id)

    video_ids = ["vSub1", "vSub2", "vSub3"]
    details = {
        vid: {
            "video_id": vid,
            "title": f"Sub Video {vid}",
            "channel_name": "SubChannel",
            "channel_id": channel_id,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "duration_seconds": 300,
            "thumbnail_url": None,
            "published_at": None,
        }
        for vid in video_ids
    }
    fake_segments = [{"text": "hello world from the sub channel", "start": 0.0, "duration": 5.0}]

    channel_metadata = {
        "channel_id": channel_id,
        "name": "SubChannel",
        "uploads_playlist_id": f"UU{channel_id[2:]}",
        "subscriber_count": 1000,
    }

    with patch.object(job_tasks, "youtube_service") as mock_yt, \
         patch.object(yt_connector, "youtube_service", mock_yt), \
         patch.object(job_tasks, "chroma_service") as mock_chroma, \
         patch.object(job_tasks, "progress_service"):
        mock_yt.resolve_channel_id = MagicMock(return_value=channel_id)
        mock_yt.get_channel_metadata = MagicMock(return_value=channel_metadata)
        mock_yt.get_channel_videos_all = MagicMock(return_value=video_ids)
        mock_yt.get_video_details = MagicMock(return_value=details)
        mock_yt.fetch_transcript = MagicMock(return_value=(fake_segments, "en", "youtube"))
        mock_chroma.insert_chunks = MagicMock(return_value=3)
        mock_chroma.delete_video_chunks = MagicMock(return_value=None)

        job_tasks.execute_subscription_job.run(job.id)

    # Global videos table now has 3 rows.
    videos = db.query(Document).filter(Document.video_id.in_(video_ids)).all()
    assert len(videos) == 3

    # job_videos links: all 3, all approved, selection_reason='subscription'.
    links = db.query(JobVideo).filter(JobVideo.job_id == job.id).all()
    assert len(links) == 3
    assert all(jv.approved is True for jv in links)
    assert all(jv.selection_reason == "subscription" for jv in links)

    # Job completed directly — no awaiting_approval pause, no report.
    db.refresh(job)
    assert job.status == "completed"
    assert job.report_path is None

    # Channel row created and marked subscribed.
    ch = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    assert ch is not None
    assert ch.subscribed is True


def test_execute_subscription_job_skips_duplicate_videos(patch_session_local, db):
    """If a video already exists in the global `videos` table, the task reuses
    it (no duplicate row) and only creates the JobVideo link."""
    channel_id = "UCsubDedupe"
    job = _make_subscription_job(db, channel_id=channel_id)

    # Pre-seed one video in the global table.
    existing = Document(
        video_id="vSub1",
        title="Already Seen",
        channel_id=channel_id,
        url="https://www.youtube.com/watch?v=vSub1",
        duration_seconds=100,
        transcript_status="pending",
    )
    db.add(existing)
    db.commit()

    video_ids = ["vSub1", "vSub2"]
    details = {
        vid: {
            "video_id": vid,
            "title": f"Sub Video {vid}",
            "channel_name": "SubChannel",
            "channel_id": channel_id,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "duration_seconds": 300,
            "thumbnail_url": None,
            "published_at": None,
        }
        for vid in video_ids
    }
    fake_segments = [{"text": "hi", "start": 0.0, "duration": 1.0}]

    channel_metadata = {
        "channel_id": channel_id,
        "name": "SubChannel",
        "uploads_playlist_id": f"UU{channel_id[2:]}",
        "subscriber_count": 500,
    }

    with patch.object(job_tasks, "youtube_service") as mock_yt, \
         patch.object(yt_connector, "youtube_service", mock_yt), \
         patch.object(job_tasks, "chroma_service") as mock_chroma, \
         patch.object(job_tasks, "progress_service"):
        mock_yt.resolve_channel_id = MagicMock(return_value=channel_id)
        mock_yt.get_channel_metadata = MagicMock(return_value=channel_metadata)
        mock_yt.get_channel_videos_all = MagicMock(return_value=video_ids)
        mock_yt.get_video_details = MagicMock(return_value=details)
        mock_yt.fetch_transcript = MagicMock(return_value=(fake_segments, "en", "youtube"))
        mock_chroma.insert_chunks = MagicMock(return_value=2)
        mock_chroma.delete_video_chunks = MagicMock(return_value=None)

        job_tasks.execute_subscription_job.run(job.id)

    # Still only one row per video_id globally.
    assert db.query(Document).filter(Document.video_id == "vSub1").count() == 1
    assert db.query(Document).filter(Document.video_id == "vSub2").count() == 1
    # Both linked to the subscription job.
    assert db.query(JobVideo).filter(JobVideo.job_id == job.id).count() == 2

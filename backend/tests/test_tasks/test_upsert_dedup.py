"""Regression tests for `_upsert_video_and_link`'s pending-insert dedup.

A single search batch often returns multiple videos from the same channel
(e.g. 5 Firstpost videos). `db.get(Channel, ...)` only consults the session's
identity map of flushed rows — it cannot see rows still sitting in `db.new`.
Without an explicit `db.new` check, the second call in a batch adds the same
Channel again; the commit then trips the UNIQUE constraint and leaves the
whole session in a PendingRollbackError state, which wedges the orchestrator
task before it can mark the job failed.

These tests pin down both:
  1. repeated same-batch adds of the same channel_id / video_id do not crash,
  2. only one row per natural key lands in the database,
  3. the JobVideo link rows are still created correctly.
"""
from app.models.channel import Channel
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.video import Video
from app.tasks.job_tasks import (
    _channel_pending,
    _upsert_video_and_link,
    _video_pending,
)


def _make_job(db, job_type: str = "topic") -> Job:
    job = Job(job_type=job_type, topic="dedup-test", num_videos=5)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_pending_helpers_see_unflushed_additions(db):
    """Without a flush, db.get() returns None but the pending helpers catch it."""
    db.add(Channel(channel_id="UCpending", name="Pending"))
    db.add(Video(video_id="vPending", channel_id="UCpending", title="t", url="u"))

    # db.get() does not see unflushed adds — that's the bug we're working around.
    assert db.get(Channel, "UCpending") is None
    assert db.get(Video, "vPending") is None

    # The helpers must see them.
    assert _channel_pending(db, "UCpending") is True
    assert _video_pending(db, "vPending") is True
    assert _channel_pending(db, "UCmissing") is False
    assert _video_pending(db, "vMissing") is False


def test_upsert_dedups_same_channel_across_videos(db):
    """Five videos sharing one channel must produce one Channel row, five Videos,
    five JobVideo links — all in a single commit."""
    job = _make_job(db)
    shared_channel_id = "UCsharedDedup"
    shared_channel_name = "SharedChannel"

    for i in range(5):
        _upsert_video_and_link(db, job.id, {
            "video_id": f"vDedup{i}",
            "title": f"Video {i}",
            "channel_id": shared_channel_id,
            "channel_name": shared_channel_name,
            "url": f"https://www.youtube.com/watch?v=vDedup{i}",
            "duration_seconds": 300,
        })

    # This is what breaks before the fix: UNIQUE violation on Channel.channel_id.
    db.commit()

    channels = db.query(Channel).filter(Channel.channel_id == shared_channel_id).all()
    assert len(channels) == 1
    assert channels[0].name == shared_channel_name

    videos = db.query(Video).filter(Video.channel_id == shared_channel_id).all()
    assert len(videos) == 5

    links = db.query(JobVideo).filter(JobVideo.job_id == job.id).all()
    assert len(links) == 5
    assert all(jv.approved is True for jv in links)


def test_upsert_dedups_same_video_added_twice(db):
    """Same video_id appearing twice in one batch must produce one Video row
    and one JobVideo link."""
    job = _make_job(db)

    payload = {
        "video_id": "vTwice",
        "title": "Only Once",
        "channel_id": "UCtwice",
        "channel_name": "TwiceChannel",
        "url": "https://www.youtube.com/watch?v=vTwice",
        "duration_seconds": 120,
    }

    _upsert_video_and_link(db, job.id, payload)
    # Second call in the same batch (unflushed): must NOT stage a duplicate Video.
    _upsert_video_and_link(db, job.id, payload)

    db.commit()

    videos = db.query(Video).filter(Video.video_id == "vTwice").all()
    assert len(videos) == 1

    links = db.query(JobVideo).filter(
        JobVideo.job_id == job.id, JobVideo.video_id == "vTwice"
    ).all()
    assert len(links) == 1


def test_upsert_handles_mixed_batch_new_and_existing(db):
    """A batch that includes both a pre-existing video and a fresh one must
    commit cleanly — preserving the existing row's state and inserting the new."""
    # Pre-seed an existing Channel + Video (flushed and committed).
    db.add(Channel(channel_id="UCmixed", name="Mixed"))
    db.add(Video(
        video_id="vExisting",
        channel_id="UCmixed",
        title="Original Title",
        url="https://www.youtube.com/watch?v=vExisting",
        duration_seconds=600,
    ))
    db.commit()

    job = _make_job(db)

    # Refresh metadata on the existing video and add a new one in the same batch.
    _upsert_video_and_link(db, job.id, {
        "video_id": "vExisting",
        "title": "Refreshed Title",
        "channel_id": "UCmixed",
        "channel_name": "Mixed",
        "url": "https://www.youtube.com/watch?v=vExisting",
        "duration_seconds": 600,
    })
    _upsert_video_and_link(db, job.id, {
        "video_id": "vFresh",
        "title": "Brand New",
        "channel_id": "UCmixed",
        "channel_name": "Mixed",
        "url": "https://www.youtube.com/watch?v=vFresh",
        "duration_seconds": 240,
    })

    db.commit()

    # Channel unchanged.
    assert db.query(Channel).filter(Channel.channel_id == "UCmixed").count() == 1

    # Existing video: title got refreshed, still one row.
    existing = db.query(Video).filter(Video.video_id == "vExisting").one()
    assert existing.title == "Refreshed Title"

    # New video landed.
    fresh = db.query(Video).filter(Video.video_id == "vFresh").one()
    assert fresh.title == "Brand New"

    # Both JobVideo links created.
    link_video_ids = {
        jv.video_id for jv in db.query(JobVideo).filter(JobVideo.job_id == job.id).all()
    }
    assert link_video_ids == {"vExisting", "vFresh"}

"""Tests for the globally-deduplicated `videos` table and `job_videos` link table.

These tests verify the Unit 1 data model refactor:
- `videos` is a global table (one row per YouTube `video_id`).
- `job_videos` is the association between jobs and the global video rows,
  carrying per-job attributes like `approved` and `selection_reason`.
- `Job.videos` still exposes the associated Video objects via secondary.
"""
import pytest

from app.models.job import Job

# Unit 1 deps: global Video + JobVideo link. Skip the whole module with a
# clear reason when those haven't landed yet.
pytest.importorskip("app.models.job_video", reason="pending Unit 1 merge — JobVideo link table")

from app.models.job_video import JobVideo  # noqa: E402
from app.models.video import Video  # noqa: E402

# Extra guard: the refactored Video model no longer has a per-row job_id FK
# (moved to the JobVideo link table). If we still see that column, the
# rename hasn't fully happened yet.
if "job_id" in {c.name for c in Video.__table__.columns}:
    pytest.skip(
        "pending Unit 1 merge — Video.job_id still present; awaiting global-video refactor",
        allow_module_level=True,
    )


def _make_job(db, topic: str = "unit-test") -> Job:
    job = Job(job_type="topic", topic=topic, num_videos=5)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_video(db, video_id: str, title: str = "Title") -> Video:
    video = Video(
        video_id=video_id,
        title=title,
        channel_id="UC123",
        url=f"https://www.youtube.com/watch?v={video_id}",
        duration_seconds=300,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def test_video_global_uniqueness_across_jobs(db):
    """Creating two jobs that both reference the same `video_id` stores ONE row
    in `videos` and TWO rows in `job_videos`."""
    job_a = _make_job(db, "topic A")
    job_b = _make_job(db, "topic B")
    video = _make_video(db, "shared-vid")

    db.add(JobVideo(job_id=job_a.id, video_id=video.video_id, approved=True,
                    selection_reason="search"))
    db.add(JobVideo(job_id=job_b.id, video_id=video.video_id, approved=True,
                    selection_reason="search"))
    db.commit()

    assert db.query(Video).filter(Video.video_id == "shared-vid").count() == 1
    assert db.query(JobVideo).filter(JobVideo.video_id == "shared-vid").count() == 2


def test_job_videos_secondary_relationship_returns_video(db):
    """`job.videos` (via secondary) must return the Video rows for each job."""
    job_a = _make_job(db, "topic A")
    job_b = _make_job(db, "topic B")
    video = _make_video(db, "vid-shared", title="Shared Video")

    db.add(JobVideo(job_id=job_a.id, video_id=video.video_id, approved=True))
    db.add(JobVideo(job_id=job_b.id, video_id=video.video_id, approved=True))
    db.commit()
    db.refresh(job_a)
    db.refresh(job_b)

    a_videos = list(job_a.videos)
    b_videos = list(job_b.videos)

    assert len(a_videos) == 1
    assert len(b_videos) == 1
    assert a_videos[0].video_id == "vid-shared"
    assert a_videos[0].title == "Shared Video"
    assert b_videos[0].video_id == "vid-shared"


def test_insert_duplicate_video_raises(db):
    """Second insert of the same video_id must violate the global uniqueness
    constraint — enforcement may be PRIMARY KEY or UNIQUE depending on schema."""
    _make_video(db, "dup-vid")

    dup = Video(
        video_id="dup-vid",
        title="Dup",
        channel_id="UC123",
        url="https://www.youtube.com/watch?v=dup-vid",
        duration_seconds=100,
    )
    db.add(dup)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_delete_job_removes_link_but_keeps_global_video(db):
    """Deleting a Job must cascade to its JobVideo links but leave the global
    Video row intact (other jobs may reference it)."""
    job_a = _make_job(db, "topic A")
    job_b = _make_job(db, "topic B")
    video = _make_video(db, "vid-shared2")

    db.add(JobVideo(job_id=job_a.id, video_id=video.video_id, approved=True))
    db.add(JobVideo(job_id=job_b.id, video_id=video.video_id, approved=True))
    db.commit()

    db.delete(job_a)
    db.commit()

    # Video row survives, job_b's link survives, only job_a's link is gone.
    assert db.query(Video).filter(Video.video_id == "vid-shared2").count() == 1
    assert db.query(JobVideo).filter(JobVideo.video_id == "vid-shared2").count() == 1
    remaining = db.query(JobVideo).filter(JobVideo.video_id == "vid-shared2").first()
    assert remaining.job_id == job_b.id

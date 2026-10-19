"""replay_visual_ab.py — the two arms must differ only by the visual spans.

The report agent is not run here. What is checked is the part that makes the
A/B valid: the OFF arm carries no `[VISUAL @` marker, the ON arm does, both
arms come from the same videos, and the manifest counts are honest.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import replay_visual_ab as replay  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.job_video import JobVideo  # noqa: E402

SEGMENTS = [
    {"text": f"Sentence number {i} about plotting a bar chart with matplotlib.", "start": float(i * 5), "duration": 5.0}
    for i in range(40)
]


def _frame(ts: float, desc: str, informative: bool = True, status: str = "described"):
    return SimpleNamespace(timestamp_seconds=ts, description=desc, informative=informative, status=status)


def _seed(db, test_user, video_id: str = "abcdefghijk") -> Job:
    now = datetime.now(timezone.utc)
    doc = Document(
        video_id=video_id,
        title="Bar charts in matplotlib",
        channel_id="UC" + "A" * 22,
        url=f"https://www.youtube.com/watch?v={video_id}",
        duration_seconds=200,
        published_at=now,
        transcript_status="fetched",
        created_at=now,
    )
    job = Job(id="r1-ab-job", tenant_id=test_user.id, job_type="topic", topic="matplotlib tutorials",
              status="completed", created_at=now)
    db.add_all([doc, job])
    db.commit()
    db.add(JobVideo(job_id=job.id, video_id=video_id, approved=True))
    db.commit()
    return job


def test_arms_differ_only_by_visual_spans(db, test_user, monkeypatch):
    job = _seed(db, test_user)
    monkeypatch.setattr(replay, "_load_cached_segments", lambda vid: (SEGMENTS, "en"))
    monkeypatch.setattr(
        replay, "_existing_frames",
        lambda _db, vid: [_frame(12.0, "A bar chart with three blue bars labelled Q1-Q3"), _frame(90.0, "Code: plt.bar(x, y)")],
    )

    manifest, on, off, blocks = replay.build_arms(db, job.id)

    assert manifest["video_count"] == 1
    assert manifest["frames_total"] == 2 and manifest["frames_informative"] == 2
    assert not any(replay.MARKER in c["text"] for c in off), "OFF arm must carry no visual span"
    assert any(replay.MARKER in c["text"] for c in on), "ON arm must carry the spans"
    assert manifest["chunks_with_visual"] >= 1
    # Same spoken words in both arms once the spans are stripped.
    from app.services.visual_service import strip_annotations
    spoken_on = " ".join(strip_annotations(c["text"]) for c in on).split()
    spoken_off = " ".join(c["text"] for c in off).split()
    assert set(spoken_on) == set(spoken_off)
    assert blocks and "Bar charts in matplotlib" in blocks[0] and replay.MARKER in blocks[0]


def test_uninformative_frames_do_not_annotate(db, test_user, monkeypatch):
    job = _seed(db, test_user, video_id="zyxwvutsrqp")
    monkeypatch.setattr(replay, "_load_cached_segments", lambda vid: (SEGMENTS, "en"))
    monkeypatch.setattr(
        replay, "_existing_frames",
        lambda _db, vid: [_frame(12.0, "A blank slide", informative=False), _frame(50.0, None, status="failed")],
    )
    manifest, on, off, _ = replay.build_arms(db, job.id)
    assert manifest["frames_total"] == 2 and manifest["frames_informative"] == 0
    assert manifest["chunks_with_visual"] == 0
    assert [c["text"] for c in on] == [c["text"] for c in off]


def test_missing_transcript_is_skipped_not_fatal(db, test_user, monkeypatch):
    job = _seed(db, test_user, video_id="nocachevid1")
    monkeypatch.setattr(replay, "_load_cached_segments", lambda vid: None)
    monkeypatch.setattr(replay, "_existing_frames", lambda _db, vid: [])
    manifest, on, off, blocks = replay.build_arms(db, job.id)
    assert manifest["video_count"] == 0 and on == [] and off == [] and blocks == []

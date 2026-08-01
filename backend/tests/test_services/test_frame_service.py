"""Frame extraction against a real video file.

The ffmpeg invocation is the kind of code that looks obviously correct and
is silently wrong — a misplaced `-ss`, a scale filter producing an odd
height that the encoder rejects, a seek past the end producing no file and
no error. So these tests run ffmpeg for real against a synthetic clip
generated on the fly. No network, no YouTube, no bot-wall exposure.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from app.services import frame_service
from app.services.frame_service import FrameCaptureError, frames_dir_for

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> str:
    """A 10-second 640x360 test-pattern clip with a visible timer."""
    path = str(tmp_path_factory.mktemp("clip") / "test.mp4")
    subprocess.run(
        [
            shutil.which("ffmpeg"), "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=10",
            "-pix_fmt", "yuv420p", path,
        ],
        check=True, capture_output=True, timeout=120,
    )
    return path


def test_extracts_a_frame_at_the_requested_timestamp(clip, tmp_path):
    out = str(tmp_path / "f.jpg")
    dims = frame_service._extract_one(clip, 5.0, out, "[t]")
    assert dims is not None
    assert os.path.getsize(out) > 0
    assert dims == (640, 360)


def test_frames_are_downscaled_to_the_configured_width(clip, tmp_path, monkeypatch):
    """Vision cost scales with pixel count, so the cap has to actually bite."""
    monkeypatch.setattr("app.config.settings.VISUAL_FRAME_MAX_WIDTH", 320)
    dims = frame_service._extract_one(clip, 1.0, str(tmp_path / "f.jpg"), "[t]")
    assert dims == (320, 180)


def test_frames_smaller_than_the_cap_are_not_upscaled(clip, tmp_path, monkeypatch):
    """`min(cap, iw)` — upscaling would spend vision tokens on invented
    pixels."""
    monkeypatch.setattr("app.config.settings.VISUAL_FRAME_MAX_WIDTH", 4096)
    dims = frame_service._extract_one(clip, 1.0, str(tmp_path / "f.jpg"), "[t]")
    assert dims == (640, 360)


def test_scaling_never_produces_an_odd_height(clip, tmp_path, monkeypatch):
    """`-2` in the scale filter keeps height even. An odd height is rejected
    by yuv420p encoders, which would fail every frame at that width."""
    monkeypatch.setattr("app.config.settings.VISUAL_FRAME_MAX_WIDTH", 331)
    dims = frame_service._extract_one(clip, 1.0, str(tmp_path / "f.jpg"), "[t]")
    assert dims is not None
    assert dims[1] % 2 == 0


def test_seeking_past_the_end_returns_none_rather_than_a_broken_file(clip, tmp_path):
    """ffmpeg exits 0 and writes nothing. Without the explicit size check
    this would register as a captured frame and be sent to a vision model."""
    out = str(tmp_path / "f.jpg")
    assert frame_service._extract_one(clip, 9999.0, out, "[t]") is None


def test_distinct_timestamps_produce_distinct_images(clip, tmp_path):
    """Guards the `-ss` placement: with `-ss` after `-i` on some builds you
    can get frame 0 back every time — twelve identical stills, each billed."""
    a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    frame_service._extract_one(clip, 1.0, a, "[t]")
    frame_service._extract_one(clip, 8.0, b, "[t]")
    assert open(a, "rb").read() != open(b, "rb").read()


def test_capture_frames_with_no_timestamps_does_no_work(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not download")

    monkeypatch.setattr(frame_service, "_download_video", boom)
    assert frame_service.capture_frames("v1", []) == []
    assert called["n"] == 0


def test_capture_frames_extracts_every_timestamp_from_one_download(clip, monkeypatch, tmp_path):
    """One download, many seeks. The naive shape is one yt-dlp call per
    timestamp, which is 12x the requests for the same bytes — and is how you
    get bot-walled (D-051)."""
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(tmp_path / "frames"))
    downloads = {"n": 0}

    def fake_download(video_id, tmpdir, tag):
        downloads["n"] += 1
        return clip

    monkeypatch.setattr(frame_service, "_download_video", fake_download)
    frames = frame_service.capture_frames("vid123", [1.0, 4.0, 8.0])

    assert downloads["n"] == 1
    assert len(frames) == 3
    assert [f.timestamp_seconds for f in frames] == [1.0, 4.0, 8.0]
    assert all(os.path.exists(f.image_path) for f in frames)


def test_one_bad_timestamp_does_not_lose_the_others(clip, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(tmp_path / "frames"))
    monkeypatch.setattr(frame_service, "_download_video", lambda *a, **k: clip)
    frames = frame_service.capture_frames("vid123", [1.0, 9999.0, 8.0])
    assert [f.timestamp_seconds for f in frames] == [1.0, 8.0]


def test_frames_dir_is_per_document(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(tmp_path / "frames"))
    a, b = frames_dir_for("abc123"), frames_dir_for("xyz789")
    assert a != b
    assert os.path.isdir(a) and os.path.isdir(b)


def test_document_id_cannot_escape_the_frames_directory(tmp_path, monkeypatch):
    """The id reaches this function from ingested source data."""
    base = tmp_path / "frames"
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(base))
    path = frames_dir_for("../../etc/evil")
    assert os.path.abspath(path).startswith(os.path.abspath(str(base)))


def test_an_id_with_no_usable_characters_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(tmp_path / "frames"))
    with pytest.raises(FrameCaptureError):
        frames_dir_for("../..")


def test_colon_ids_are_flattened_not_split(tmp_path, monkeypatch):
    """Non-YouTube source ids look like `reddit:abc123`; a raw colon is an
    illegal path character on Windows."""
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(tmp_path / "frames"))
    path = frames_dir_for("reddit:abc123")
    assert os.path.isdir(path)
    assert ":" not in os.path.basename(path)


# ---------------------------------------------------------------------------
# Stored paths
# ---------------------------------------------------------------------------
def test_stored_paths_are_relative_to_the_frames_root_not_the_cwd(tmp_path, monkeypatch):
    """The Celery worker, the API process and a CLI script do not share a cwd,
    so a cwd-relative path written by one may not resolve in another."""
    base = tmp_path / "frames"
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(base))
    stored = frame_service.relative_image_path(str(base / "vid123" / "45.jpg"))
    assert stored == "vid123/45.jpg"
    assert not os.path.isabs(stored)


def test_stored_paths_round_trip(tmp_path, monkeypatch):
    base = tmp_path / "frames"
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(base))
    original = str(base / "vid123" / "45.jpg")
    resolved = frame_service.resolve_image_path(
        frame_service.relative_image_path(original)
    )
    assert os.path.normpath(resolved) == os.path.normpath(original)


def test_a_path_outside_the_frames_root_stays_absolute(tmp_path, monkeypatch):
    """Better an absolute path than a `../../..` chain that silently resolves
    somewhere else after the install moves."""
    monkeypatch.setattr("app.config.settings.VISUAL_FRAMES_DIR", str(tmp_path / "frames"))
    outside = str(tmp_path / "elsewhere" / "x.jpg")
    assert os.path.isabs(frame_service.relative_image_path(outside))

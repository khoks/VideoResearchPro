"""Frame capture from source video — R1 / S-1.18.1.

Pulls still images out of a video at requested timestamps. This is the only
part of the visual pipeline that talks to YouTube, and it is the part with
teeth: D-051 records an IP block that cost 63 videos mid-job, caused by
audio-only downloads at a gentler rate than this.

**One download, many seeks.** The naive shape is one yt-dlp invocation per
timestamp, which is 12x the requests for the same bytes and is exactly how
you get bot-walled. Instead we download the video once into a temp dir and
run ``ffmpeg -ss T -frames:v 1`` against the local file per timestamp. That
turns N network round-trips into 1.

**Worst stream that still clears 360p.** Frames only have to be legible to
a vision model reading a slide or a chart axis. `worstvideo[height>=360]`
typically lands 360-480p, which is a fraction of the bytes of the default
`best` and still passes ``VISUAL_MAX_VIDEO_DOWNLOAD_MB``.

The temp video is deleted as soon as extraction finishes. Only the JPEGs
persist, under ``VISUAL_FRAMES_DIR/<video_id>/``.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapturedFrame:
    """One successfully extracted still."""

    timestamp_seconds: float
    image_path: str
    width: int
    height: int


class FrameCaptureError(RuntimeError):
    """Capture failed for a whole document — no frames are available.

    Raised for the document-level failures (download blocked, ffmpeg
    missing, stream too large). A single timestamp failing to extract is
    NOT an error: it is logged and skipped, because losing one moment out
    of twelve should not cost the other eleven.
    """


def _ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def frames_dir_for(video_id: str) -> str:
    """Absolute directory holding one document's frames. Created on demand."""
    base = os.path.abspath(settings.VISUAL_FRAMES_DIR)
    # Path component from a caller-supplied id — keep it to the characters
    # YouTube/Reddit/HN ids actually use so a crafted id cannot escape the
    # frames directory.
    safe = "".join(c for c in video_id if c.isalnum() or c in "-_:")[:80]
    if not safe:
        raise FrameCaptureError(f"unusable document id for a path: {video_id!r}")
    path = os.path.join(base, safe.replace(":", "_"))
    os.makedirs(path, exist_ok=True)
    return path


def relative_image_path(absolute_path: str) -> str:
    """Store frame paths relative to ``VISUAL_FRAMES_DIR``.

    Not relative to the process's cwd: the Celery worker, the API process and
    a CLI script do not share one, so a cwd-relative path written by the
    worker may not resolve anywhere else. Relative to the configured root, a
    stored path stays valid when the install moves.
    """
    base = os.path.abspath(settings.VISUAL_FRAMES_DIR)
    absolute = os.path.abspath(absolute_path)
    try:
        rel = os.path.relpath(absolute, base)
    except ValueError:
        # Different drive on Windows — no relative path exists.
        return absolute
    return absolute if rel.startswith("..") else rel.replace(os.sep, "/")


def resolve_image_path(stored_path: str) -> str:
    """Inverse of `relative_image_path`. Absolute paths pass through."""
    if os.path.isabs(stored_path):
        return stored_path
    return os.path.join(os.path.abspath(settings.VISUAL_FRAMES_DIR), stored_path)


def _download_video(video_id: str, tmpdir: str, tag: str) -> str:
    """Download one video stream via yt-dlp, escalating player clients.

    Reuses `youtube_service`'s rate limiter and client ladder rather than
    keeping a second, differently-tuned copy — the bot-wall does not care
    which of our code paths made the request.
    """
    import yt_dlp

    from app.services.youtube_service import (
        _YTDLP_CLIENT_LADDER,
        _build_ydl_opts,
        download_limiter,
    )

    url = f"https://www.youtube.com/watch?v={video_id}"
    max_bytes = settings.VISUAL_MAX_VIDEO_DOWNLOAD_MB * 1024 * 1024

    for client, delay in _YTDLP_CLIENT_LADDER:
        if delay:
            time.sleep(delay)
        download_limiter.wait()
        attempt_dir = tempfile.mkdtemp(dir=tmpdir)
        # Start from the audio-path options so every unblock knob
        # (proxy, cookies-from-browser, cookies-file) applies identically,
        # then swap the format selector for a video one.
        opts = _build_ydl_opts(attempt_dir, client, prefer_smallest=False)
        opts["format"] = (
            "worstvideo[height>=360][ext=mp4]"
            "/worstvideo[height>=360]"
            "/worst[height>=360][ext=mp4]"
            "/worst[ext=mp4]"
            "/worst"
        )
        opts["outtmpl"] = os.path.join(attempt_dir, "video.%(ext)s")
        # yt-dlp aborts the download itself once the declared size exceeds
        # the cap, so we never spend the bytes we are trying to avoid.
        opts["max_filesize"] = max_bytes
        client_label = client or "default"
        try:
            logger.info(
                "%s Downloading video for %s via yt-dlp (client=%s)",
                tag, video_id, client_label,
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            logger.warning(
                "%s yt-dlp video download failed for %s (client=%s): %s",
                tag, video_id, client_label, e,
            )
            continue
        files = [
            os.path.join(attempt_dir, f)
            for f in os.listdir(attempt_dir)
            if not f.endswith(".part")
        ]
        if files:
            path = files[0]
            size_mb = os.path.getsize(path) / (1024 * 1024)
            logger.info(
                "%s Downloaded %.1f MB of video for %s", tag, size_mb, video_id
            )
            return path
        logger.warning(
            "%s yt-dlp produced no video file for %s (client=%s) — "
            "likely over the %d MB cap",
            tag, video_id, client_label, settings.VISUAL_MAX_VIDEO_DOWNLOAD_MB,
        )
    raise FrameCaptureError(
        f"yt-dlp could not fetch a usable video stream for {video_id} on any "
        f"of {len(_YTDLP_CLIENT_LADDER)} player clients"
    )


def _extract_one(
    video_path: str, timestamp: float, out_path: str, tag: str
) -> tuple[int, int] | None:
    """Extract a single frame. Returns (width, height), or None on failure.

    ``-ss`` before ``-i`` is the fast path: ffmpeg seeks by keyframe rather
    than decoding from the start of the file. For a 12-frame grab out of an
    hour-long video the difference is minutes.
    """
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        raise FrameCaptureError("ffmpeg not found on PATH")

    cmd = [
        ffmpeg, "-v", "error", "-y",
        "-ss", f"{max(timestamp, 0.0):.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale='min({settings.VISUAL_FRAME_MAX_WIDTH},iw)':-2",
        "-q:v", str(settings.VISUAL_FRAME_JPEG_QUALITY),
        out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    except subprocess.CalledProcessError as e:
        logger.warning(
            "%s ffmpeg failed at t=%.1fs: %s", tag, timestamp, (e.stderr or "")[:200]
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning("%s ffmpeg timed out at t=%.1fs", tag, timestamp)
        return None

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        # Seeking past the end of the stream produces no output and no error.
        logger.warning(
            "%s ffmpeg produced no frame at t=%.1fs (past end of stream?)",
            tag, timestamp,
        )
        return None
    return _probe_dimensions(out_path)


def _probe_dimensions(image_path: str) -> tuple[int, int] | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                image_path,
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
        w, _, h = out.stdout.strip().partition("x")
        return int(w), int(h)
    except Exception:
        return None


def capture_frames(
    video_id: str,
    timestamps: list[float],
    *,
    tag: str = "[visual]",
) -> list[CapturedFrame]:
    """Capture stills at ``timestamps`` (seconds) from one video.

    Raises `FrameCaptureError` when the document as a whole cannot be
    processed (no ffmpeg, download blocked, stream over the size cap).
    Individual timestamps that fail to extract are skipped with a warning —
    a partial set of frames is worth more than none.
    """
    if not timestamps:
        return []
    if not _ffmpeg_bin():
        raise FrameCaptureError("ffmpeg not found on PATH")

    out_dir = frames_dir_for(video_id)
    deadline = time.monotonic() + settings.VISUAL_CAPTURE_TIMEOUT_SEC
    captured: list[CapturedFrame] = []

    with tempfile.TemporaryDirectory(prefix="frames_") as tmpdir:
        video_path = _download_video(video_id, tmpdir, tag)

        for ts in sorted(timestamps):
            if time.monotonic() > deadline:
                logger.warning(
                    "%s Capture budget (%ds) exhausted for %s after %d/%d "
                    "frames — remaining timestamps skipped",
                    tag, settings.VISUAL_CAPTURE_TIMEOUT_SEC, video_id,
                    len(captured), len(timestamps),
                )
                break
            out_path = os.path.join(out_dir, f"{int(round(ts))}.jpg")
            dims = _extract_one(video_path, ts, out_path, tag)
            if dims is None:
                continue
            captured.append(
                CapturedFrame(
                    timestamp_seconds=float(ts),
                    image_path=out_path,
                    width=dims[0],
                    height=dims[1],
                )
            )

    logger.info(
        "%s Captured %d/%d frames for %s", tag, len(captured), len(timestamps), video_id
    )
    return captured

"""Flatten a podcast episode into chunkable text segments.

Two paths:

1. **In-feed transcript** — the Podcast Index 2.0 spec defines a
   ``<podcast:transcript>`` tag with ``url`` + ``type`` (typically
   ``application/srt`` or ``text/vtt``). When present, we fetch and
   parse it directly, skipping the Whisper round-trip.
2. **Whisper transcribe** — download audio enclosure to temp file,
   send to OpenAI Whisper API (reusing the existing helper from
   ``app.services.youtube_service``), use its returned ``segments``
   list directly.

Either way the output shape mirrors the YouTube transcript shape so
the chunker (which already handles `(text, start, duration, extra)`
segments per [S-1.5.12](../../../docs/initiatives.md#s-1512--backend-reference-enrichment))
stays uniform across source types.

Each segment carries an `extra` block with ``kind="audio_segment"``
plus the parent episode's ``author`` (show host) and a ``timestamp_url``
that podcast players can deep-link into when the listener clicks the
citation. Per-segment provenance is uniform within an episode (no
multi-author straddling like Reddit/HN/Mastodon), so the dominant-
segment heuristic in chunk_transcript is a no-op for podcasts —
the whole chunk's ``comment_id`` always reflects the episode.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Cheap SRT-block regex. SRT format:
#   1
#   00:00:01,000 --> 00:00:05,500
#   Hello world.
#
#   2
#   00:00:05,500 --> 00:00:10,000
#   Second segment.
_SRT_BLOCK_RE = re.compile(
    r"(?P<idx>\d+)\s*\n"
    r"(?P<start_h>\d+):(?P<start_m>\d+):(?P<start_s>\d+)[,.](?P<start_ms>\d+)\s*-->\s*"
    r"(?P<end_h>\d+):(?P<end_m>\d+):(?P<end_s>\d+)[,.](?P<end_ms>\d+)\s*\n"
    r"(?P<text>(?:.+\n?)+?)(?:\n\n|\Z)",
    re.MULTILINE,
)


def _srt_timestamp_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(srt_text: str) -> list[dict[str, Any]]:
    """Parse an SRT-formatted transcript into segments.

    Returns a list of ``{text, start, duration}`` dicts matching the
    YouTube transcript-segment shape so the chunker can consume them
    without special-casing.
    """
    if not srt_text:
        return []
    segments: list[dict[str, Any]] = []
    for m in _SRT_BLOCK_RE.finditer(srt_text):
        text = " ".join(m.group("text").strip().split())
        if not text:
            continue
        start = _srt_timestamp_to_seconds(
            m.group("start_h"),
            m.group("start_m"),
            m.group("start_s"),
            m.group("start_ms"),
        )
        end = _srt_timestamp_to_seconds(
            m.group("end_h"),
            m.group("end_m"),
            m.group("end_s"),
            m.group("end_ms"),
        )
        duration = max(0.0, end - start)
        segments.append({"text": text, "start": start, "duration": duration})
    return segments


# VTT format: same as SRT but with `WEBVTT` header and `.` decimal
# separator instead of `,`. Our SRT parser already accepts both `.`
# and `,` (regex `[,.]`), so we just strip the header.
def parse_vtt(vtt_text: str) -> list[dict[str, Any]]:
    """Parse a WebVTT-formatted transcript into segments."""
    if not vtt_text:
        return []
    body = vtt_text
    if body.lstrip().startswith("WEBVTT"):
        idx = body.find("\n")
        if idx >= 0:
            body = body[idx + 1 :]
    return parse_srt(body)


def whisper_segments_to_canonical(whisper_segments: list[dict]) -> list[dict[str, Any]]:
    """Convert OpenAI Whisper's ``segments`` array to our canonical shape.

    Whisper returns ``[{id, start, end, text, ...}]`` (with ``end`` not
    ``duration``). We coerce to ``{text, start, duration}`` so the
    chunker — which standardises on ``duration`` — doesn't need a
    podcast-specific branch.
    """
    out: list[dict[str, Any]] = []
    for seg in whisper_segments or []:
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        out.append(
            {
                "text": text,
                "start": start,
                "duration": max(0.0, end - start),
            }
        )
    return out


def attach_episode_extra(
    segments: list[dict[str, Any]],
    episode_url: str,
    author: str,
) -> list[dict[str, Any]]:
    """Add the per-episode ``extra`` block to every segment.

    Per S-1.5.12, the chunker's dominant-segment heuristic promotes
    `extra.comment_id` / `comment_url` / `author` to chunk metadata.
    For podcasts, every segment within one episode shares the same
    provenance (the episode itself), so we attach it uniformly here
    rather than per-segment in the caller.

    The synthetic ``comment_id`` is the episode URL — that's the
    "specific reply" analogue for a podcast. The ``comment_url`` is
    the same URL plus a ``#t=<seconds>`` time fragment so player apps
    that honour it (Overcast, Pocket Casts, Apple Podcasts on iOS 17+)
    deep-link to the cited timestamp on click.
    """
    out: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = seg.get("start") or 0
        out.append(
            {
                "text": seg.get("text", ""),
                "start": seg.get("start", 0),
                "duration": seg.get("duration", 0),
                "extra": {
                    "kind": "audio_segment",
                    "author": author or "",
                    "comment_id": episode_url,
                    "comment_url": (
                        f"{episode_url}#t={int(float(start))}" if episode_url else ""
                    ),
                    "depth": 0,
                },
            }
        )
    return out

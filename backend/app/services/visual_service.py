"""Merge captured visual annotations into a transcript — R1 / S-1.18.1.

This module is deliberately small and pure. `annotate_segments` takes
transcript segments and frame descriptions and returns a NEW segment list;
it mutates neither input. That matters because the transcript it is handed
comes from `transcript_cache`, which is part of the globally-shared
compute-once layer — one row per video, reused by every job and every
tenant. Annotating by rewriting that row would make one job's opt-in
feature silently rewrite everyone else's source text.

**The annotation format is the contract.** Every annotation is wrapped in
`[VISUAL @ mm:ss — ...]`. The marker travels inside the chunk TEXT, not
only in metadata, and that is on purpose: chunking can split, merge,
overlap and re-pack segments, and metadata promoted by a dominant-segment
heuristic can be dropped — but text that is physically inside the chunk
reaches the model no matter which chunk it lands in. The matching reader
instruction lives in `prompts/shared.py::VISUAL_ANNOTATION_CONTRACT`.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from app.agents.prompts.shared import VISUAL_MARKER_OPEN

logger = logging.getLogger(__name__)

# Nominal duration given to an inserted annotation segment. Non-zero so
# ordering against a same-second speech segment is stable; small enough
# that it cannot meaningfully shift a chunk's timestamp span.
_ANNOTATION_DURATION = 0.01


def format_timestamp(seconds: float) -> str:
    """mm:ss, or h:mm:ss past the hour."""
    total = int(round(max(seconds, 0.0)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_annotation(timestamp_seconds: float, description: str) -> str:
    """Render one annotation in the canonical `[VISUAL @ mm:ss — ...]` form.

    Any `]` inside the description would let a downstream reader think the
    annotation ended early and the rest was speech — exactly the confusion
    this feature must never create. Replaced rather than escaped, because
    the annotation is prose for a model to read, not a parseable payload.
    """
    body = " ".join((description or "").split()).replace("]", ")")
    return f"{VISUAL_MARKER_OPEN} @ {format_timestamp(timestamp_seconds)} — {body}]"


def annotate_segments(
    segments: list[dict],
    frames: Iterable[Any],
) -> list[dict]:
    """Return a new segment list with visual annotations interleaved.

    ``segments`` are transcript segments (`{text, start, duration, ...}`).
    ``frames`` are objects with ``timestamp_seconds``, ``description``,
    ``informative`` and ``status`` — normally `VisualFrame` rows, but any
    object with those attributes works so tests need no database.

    Only frames that are `described` AND `informative` are merged. A frame
    the describer judged uninformative is still stored (so we do not spend
    the capture again) but adding "a man is speaking to a camera" to a
    transcript is pure noise for every downstream stage.

    Annotations are inserted in timestamp order and carry
    ``extra = {"kind": "visual", "atomic": True}``. ``atomic`` is honoured by
    `utils.chunking`, which otherwise splits multi-sentence text into
    sentences and interpolates fake per-sentence timestamps — that would
    shred an annotation into fragments, each carrying half a marker.
    """
    usable = []
    for f in frames or []:
        if getattr(f, "status", None) != "described":
            continue
        if not getattr(f, "informative", False):
            continue
        desc = (getattr(f, "description", "") or "").strip()
        if not desc:
            continue
        usable.append((float(getattr(f, "timestamp_seconds", 0.0) or 0.0), desc))

    if not usable:
        return list(segments)

    usable.sort(key=lambda t: t[0])

    annotation_segments = [
        {
            "text": format_annotation(ts, desc),
            "start": ts,
            "duration": _ANNOTATION_DURATION,
            "extra": {"kind": "visual", "atomic": True, "frame_timestamp": ts},
        }
        for ts, desc in usable
    ]

    merged = list(segments) + annotation_segments
    # Stable sort on start time. Ties put the annotation AFTER the speech
    # at the same second: the speaker says "as you can see here" and then
    # the description explains what "here" was, which is the order a reader
    # needs. `_is_annotation` as the secondary key gives that ordering
    # without disturbing the relative order of the speech segments.
    merged.sort(key=lambda s: (float(s.get("start", 0) or 0), _is_annotation(s)))

    logger.info(
        "Merged %d visual annotations into %d transcript segments",
        len(annotation_segments), len(segments),
    )
    return merged


def _is_annotation(segment: dict) -> int:
    extra = segment.get("extra") or {}
    return 1 if isinstance(extra, dict) and extra.get("kind") == "visual" else 0


def strip_annotations(text: str) -> str:
    """Remove `[VISUAL @ ... ]` spans from a string.

    For the surfaces that must show what was actually SAID — dataset
    exports of speech, transcript downloads, word counts, and the
    language-detection profiler, which would otherwise measure our own
    English annotations instead of the speaker's language.
    """
    if VISUAL_MARKER_OPEN not in text:
        return text
    out: list[str] = []
    i = 0
    while i < len(text):
        start = text.find(VISUAL_MARKER_OPEN, i)
        if start == -1:
            out.append(text[i:])
            break
        end = text.find("]", start)
        if end == -1:
            # Unterminated marker — keep the remainder rather than
            # swallowing real transcript text.
            out.append(text[i:])
            break
        out.append(text[i:start])
        i = end + 1
    return " ".join("".join(out).split())

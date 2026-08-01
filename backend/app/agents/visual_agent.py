"""Visual-understanding agent — R1 / S-1.18.1.

Four stages: select moments from the transcript, capture stills at those
moments, describe each still in transcript context, persist.

The pipeline is deliberately fail-soft at every level, because it is an
opt-in enrichment layered on top of a working product. A video whose frames
cannot be captured must still produce a normal report; a frame that cannot
be described must not cost the other eleven. The only thing that must never
happen is a *silent* failure — every drop is logged with its reason, and the
`visual_frames` row records it too, so "we tried and it did not work" is
always distinguishable from "we never tried".

Frames are keyed on the document, so a second job over the same video finds
the work already done. This mirrors transcripts, embeddings and knowledge
artifacts (D-063: shared cache, private catalogue).
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.prompts.visual_prompts import (
    SELECT_MOMENTS_PROMPT,
    describe_frame_prompt,
)
from app.config import settings
from app.models.visual_frame import VisualFrame
from app.services import frame_service
from app.services.llm_routing import resolve_config, warn_if_not_vision_capable
from app.services.llm_service import get_llm_for, response_text
from app.services.visual_service import format_timestamp

logger = logging.getLogger(__name__)

# How much speech to show the describer either side of the frame. Wide
# enough that "as you can see here" and the explanation that follows are
# both present; narrow enough that the describer cannot reconstruct the
# whole segment from words and skip looking at the picture.
_WINDOW_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Stage 1 — select moments
# ---------------------------------------------------------------------------
def _transcript_with_timestamps(segments: list[dict], max_chars: int = 120_000) -> str:
    lines: list[str] = []
    used = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        line = f"[{format_timestamp(float(seg.get('start', 0) or 0))}] {text}"
        if used + len(line) > max_chars:
            lines.append("... (transcript truncated)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _parse_moments(raw: str) -> list[dict]:
    """Parse the selector's JSON array; tolerate code fences and prose."""
    content = (raw or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        end = -1 if lines and lines[-1].startswith("```") else len(lines)
        content = "\n".join(lines[1:end]).strip()
    # Models occasionally wrap the array in a sentence. Recover the array
    # rather than discarding a whole video's selection over punctuation.
    if not content.startswith("["):
        start = content.find("[")
        stop = content.rfind("]")
        if start == -1 or stop <= start:
            logger.warning("Visual selector returned no JSON array: %r", content[:200])
            return []
        content = content[start : stop + 1]

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Visual selector returned non-JSON: %r", content[:200])
        return []
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp_seconds")
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            continue
        if ts < 0:
            continue
        out.append({
            "timestamp_seconds": ts,
            "reason": str(item.get("reason") or "").strip(),
            "expected_content": str(item.get("expected_content") or "").strip(),
        })
    return out


def _enforce_spacing_and_cap(
    moments: list[dict], *, max_frames: int, min_gap: float, duration: float | None
) -> list[dict]:
    """Drop moments that violate the spacing rule or exceed the cap.

    The prompt asks for both, but a prompt is a request and this is the
    guarantee — the budget these constraints protect is real money and real
    bot-wall exposure, so it is enforced in code rather than trusted.
    """
    ordered = sorted(moments, key=lambda m: m["timestamp_seconds"])
    kept: list[dict] = []
    dropped_gap = 0
    dropped_range = 0
    for m in ordered:
        ts = m["timestamp_seconds"]
        if duration and ts > duration:
            dropped_range += 1
            continue
        if kept and ts - kept[-1]["timestamp_seconds"] < min_gap:
            dropped_gap += 1
            continue
        kept.append(m)

    dropped_cap = max(0, len(kept) - max_frames)
    kept = kept[:max_frames]

    if dropped_gap or dropped_cap or dropped_range:
        logger.info(
            "Visual selection filtered: %d too close (<%.0fs), %d past end of "
            "video, %d over the per-video cap of %d; %d kept",
            dropped_gap, min_gap, dropped_range, dropped_cap, max_frames, len(kept),
        )
    return kept


def select_moments(
    *,
    video_title: str,
    channel_name: str,
    segments: list[dict],
    duration_seconds: float | None,
    max_frames: int,
) -> list[dict]:
    """Ask the selector where the picture matters. Returns [] on any failure."""
    transcript = _transcript_with_timestamps(segments)
    if not transcript.strip():
        logger.info("Visual selection skipped: empty transcript")
        return []

    prompt = SELECT_MOMENTS_PROMPT.format(
        video_title=video_title or "Unknown",
        channel_name=channel_name or "Unknown",
        duration_label=(
            format_timestamp(duration_seconds) if duration_seconds else "unknown"
        ),
        transcript=transcript,
        max_frames=max_frames,
        min_gap=int(settings.VISUAL_MIN_GAP_SECONDS),
    )
    try:
        llm = get_llm_for("visual_select_moments", temperature=0.0, max_tokens=4_000)
        moments = _parse_moments(response_text(llm.invoke([HumanMessage(content=prompt)])))
    except Exception:
        logger.exception("Visual moment selection failed; no frames will be captured")
        return []

    return _enforce_spacing_and_cap(
        moments,
        max_frames=max_frames,
        min_gap=settings.VISUAL_MIN_GAP_SECONDS,
        duration=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Stage 3 — describe
# ---------------------------------------------------------------------------
def transcript_window(segments: list[dict], timestamp: float) -> str:
    """Speech within ±_WINDOW_SECONDS of ``timestamp``, timestamped."""
    lo, hi = timestamp - _WINDOW_SECONDS, timestamp + _WINDOW_SECONDS
    lines: list[str] = []
    for seg in segments:
        start = float(seg.get("start", 0) or 0)
        if start < lo or start > hi:
            continue
        text = (seg.get("text") or "").strip()
        if text:
            marker = " <-- FRAME" if abs(start - timestamp) <= 3 else ""
            lines.append(f"[{format_timestamp(start)}] {text}{marker}")
    return "\n".join(lines)


def _encode_image(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        logger.exception("Could not read captured frame at %s", path)
        return None


def _parse_description(raw: str) -> dict | None:
    content = (raw or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        end = -1 if lines and lines[-1].startswith("```") else len(lines)
        content = "\n".join(lines[1:end]).strip()
    if not content.startswith("{"):
        start, stop = content.find("{"), content.rfind("}")
        if start == -1 or stop <= start:
            return None
        content = content[start : stop + 1]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    description = str(data.get("description") or "").strip()
    informative = bool(data.get("informative")) and bool(description)
    # A description the model itself flagged unreadable is not evidence —
    # promoting it would let "the chart appears to show roughly 40%" become
    # a cited figure downstream.
    if str(data.get("legibility") or "").lower() == "unreadable":
        informative = False
    return {
        "informative": informative,
        "description": description,
        "reads_as": str(data.get("reads_as") or "").strip(),
        "legibility": str(data.get("legibility") or "").strip(),
    }


def describe_frame(
    *,
    video_title: str,
    frame: frame_service.CapturedFrame,
    moment: dict,
    segments: list[dict],
) -> dict | None:
    """Describe one captured still. Returns None when the call fails."""
    b64 = _encode_image(frame.image_path)
    if b64 is None:
        return None

    prompt = describe_frame_prompt(
        video_title=video_title or "Unknown",
        timestamp_label=format_timestamp(frame.timestamp_seconds),
        selection_reason=moment.get("reason", ""),
        expected_content=moment.get("expected_content", ""),
        transcript_window=transcript_window(segments, frame.timestamp_seconds),
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            },
        ]
    )
    try:
        llm = get_llm_for("visual_describe_frame", temperature=0.0, max_tokens=1_500)
        return _parse_description(response_text(llm.invoke([message])))
    except Exception:
        logger.exception(
            "Frame description failed at t=%.1fs", frame.timestamp_seconds
        )
        return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _existing_frames(db: Any, video_id: str) -> list[VisualFrame]:
    return (
        db.query(VisualFrame)
        .filter(VisualFrame.video_id == video_id)
        .order_by(VisualFrame.timestamp_seconds)
        .all()
    )


def run_visual_agent(
    db: Any,
    *,
    video_id: str,
    video_title: str,
    channel_name: str,
    segments: list[dict],
    duration_seconds: float | None = None,
    max_frames: int | None = None,
    force: bool = False,
) -> tuple[list[VisualFrame], int]:
    """Select → capture → describe → persist for one document.

    Returns ``(rows, newly_captured)``. ``newly_captured`` is what this call
    actually spent — zero when the document's frames already existed. The
    caller's budget must charge on that number, not on ``len(rows)``:
    re-running a job over an already-processed corpus costs nothing, and
    charging for it would exhaust the job budget after the first handful of
    documents and silently drop annotations from the rest.

    Idempotent: an already-processed document returns its existing rows
    untouched unless ``force``. Never raises — a failure returns whatever
    rows exist, which for a first attempt is an empty list.
    """
    tag = f"[visual {video_id}]"

    existing = _existing_frames(db, video_id)
    if existing and not force:
        logger.info("%s Already has %d frames; reusing", tag, len(existing))
        return existing, 0

    cap = max_frames if max_frames is not None else settings.VISUAL_MAX_FRAMES_PER_VIDEO
    if cap <= 0:
        logger.info("%s Frame budget is 0; skipping", tag)
        return existing, 0

    # Surface a text-only model behind a vision use case at the point it can
    # still be acted on, rather than after the download has been paid for.
    warn_if_not_vision_capable("visual_describe_frame", resolve_config("visual_describe_frame"))

    moments = select_moments(
        video_title=video_title,
        channel_name=channel_name,
        segments=segments,
        duration_seconds=duration_seconds,
        max_frames=cap,
    )
    if not moments:
        logger.info("%s Selector found no visually informative moments", tag)
        return existing, 0

    logger.info("%s Selector picked %d moments", tag, len(moments))

    try:
        captured = frame_service.capture_frames(
            video_id, [m["timestamp_seconds"] for m in moments], tag=tag
        )
    except frame_service.FrameCaptureError as e:
        logger.warning("%s Frame capture unavailable: %s", tag, e)
        return existing, 0

    by_ts = {round(m["timestamp_seconds"]): m for m in moments}
    described_model = resolve_config("visual_describe_frame").as_label()
    rows: list[VisualFrame] = []

    for frame in captured:
        moment = by_ts.get(round(frame.timestamp_seconds), {})
        result = describe_frame(
            video_title=video_title,
            frame=frame,
            moment=moment,
            segments=segments,
        )
        row = VisualFrame(
            video_id=video_id,
            # Rounded on write so the uniqueness constraint is meaningful —
            # 132.0 and 132.4 are the same frame.
            timestamp_seconds=float(round(frame.timestamp_seconds)),
            image_path=frame_service.relative_image_path(frame.image_path),
            selection_reason=moment.get("reason") or None,
            width=frame.width,
            height=frame.height,
            description_model=described_model,
        )
        if result is None:
            row.status = "failed"
            row.error_message = "description call failed or returned unparseable output"
        else:
            row.status = "described"
            row.description = result["description"] or None
            row.informative = result["informative"]
            row.described_at = datetime.utcnow()
        rows.append(row)

    try:
        if force and existing:
            for old in existing:
                db.delete(old)
            db.flush()

        for row in rows:
            db.add(row)
        db.commit()
    except Exception:
        # Roll back explicitly. The caller shares this session with the
        # extraction loop, and a failed commit leaves it unusable — every
        # subsequent video in the job would then fail on an unrelated write,
        # turning one bad visual persist into a dead job.
        db.rollback()
        logger.exception("%s Could not persist %d frames", tag, len(rows))
        return existing, 0

    informative = sum(1 for r in rows if r.informative)
    logger.info(
        "%s Persisted %d frames (%d informative, %d failed)",
        tag, len(rows), informative,
        sum(1 for r in rows if r.status == "failed"),
    )
    return rows, len(rows)

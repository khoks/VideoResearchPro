"""Per-video knowledge extraction endpoints (Unit 4).

Runs the knowledge agent synchronously for the first pass (Celery migration can
come later if the wall-clock becomes an issue). Persists the structured
extraction + Markdown report on the `Video` row.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.transcript_cache import TranscriptCache
from app.models.video import Video
from app.schemas.knowledge import KnowledgeExtractResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/videos",
    tags=["knowledge"],
    dependencies=[Depends(get_current_user)],
)


_KNOWLEDGE_KEYS = ("topics", "concepts", "events", "facts")


def _reconstruct_transcript_text(db: Session, video_id: str) -> str:
    """Build a single transcript string from `transcript_cache.segments_json`.

    Each segment is expected to have a `text` field (as returned by
    youtube-transcript-api). Segments are joined with spaces and paragraph
    breaks introduced every few segments so the splitter has natural
    boundaries to work with.
    """
    row = db.query(TranscriptCache).filter(TranscriptCache.video_id == video_id).first()
    if row is None:
        return ""
    try:
        segments = json.loads(row.segments_json)
    except (ValueError, TypeError):
        logger.exception("Corrupt transcript cache for %s", video_id)
        return ""

    if not isinstance(segments, list):
        return ""

    parts: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "") or "").strip()
        if text:
            parts.append(text)

    # Group into rough paragraphs so the splitter has semantic boundaries.
    group_size = 20
    paragraphs = [
        " ".join(parts[i:i + group_size])
        for i in range(0, len(parts), group_size)
    ]
    return "\n\n".join(paragraphs)


def _load_merged_from_video(video: Video) -> dict[str, list[str]]:
    """Parse `video.extracted_knowledge_json` into a dict of four lists."""
    empty = {k: [] for k in _KNOWLEDGE_KEYS}
    if not video.extracted_knowledge_json:
        return empty
    try:
        data = json.loads(video.extracted_knowledge_json)
    except (ValueError, TypeError):
        logger.warning("Corrupt extracted_knowledge_json for video %s", video.video_id)
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        key: [str(v) for v in data.get(key, []) if isinstance(v, (str, int, float))]
        for key in _KNOWLEDGE_KEYS
    }


def _build_response(video: Video) -> KnowledgeExtractResponse:
    merged = _load_merged_from_video(video)
    return KnowledgeExtractResponse(
        video_id=video.video_id,
        topics=merged["topics"],
        concepts=merged["concepts"],
        events=merged["events"],
        facts=merged["facts"],
        knowledge_report_md=video.knowledge_report_md or "",
        knowledge_extracted_at=video.knowledge_extracted_at,
    )


@router.post(
    "/{video_id}/extract-knowledge",
    response_model=KnowledgeExtractResponse,
)
def extract_knowledge(
    video_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
) -> KnowledgeExtractResponse:
    """Run the knowledge agent on this video and persist the artifact.

    Returns 409 if the video already has an extraction unless `?force=true`.
    Returns 404 if the video doesn't exist. Returns 422 if no transcript is
    cached for the video (nothing to extract from).
    """
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    if video.knowledge_extracted_at is not None and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge already extracted. Pass ?force=true to re-run.",
        )

    transcript_text = _reconstruct_transcript_text(db, video_id)
    if not transcript_text.strip():
        # 422 = unprocessable content: the video exists but has no transcript
        # to extract from yet (user must wait for transcript fetch to complete).
        raise HTTPException(
            status_code=422,
            detail="No transcript available for this video",
        )

    # Import inside the handler so tests that patch
    # `app.routers.knowledge.run_knowledge_extract_agent` work without the
    # real LLM being loaded at import time.
    from app.agents.knowledge_agent import run_knowledge_extract_agent

    result = run_knowledge_extract_agent(video, transcript_text)

    merged = {key: list(result.get(key, [])) for key in _KNOWLEDGE_KEYS}
    video.extracted_knowledge_json = json.dumps(merged, ensure_ascii=False)
    video.knowledge_report_md = result.get("knowledge_report_md", "") or ""
    video.knowledge_extracted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(video)

    logger.info(
        "Knowledge extracted for video %s: %d topics, %d concepts, %d events, %d facts",
        video_id,
        len(merged["topics"]),
        len(merged["concepts"]),
        len(merged["events"]),
        len(merged["facts"]),
    )

    return _build_response(video)


@router.get(
    "/{video_id}/knowledge",
    response_model=KnowledgeExtractResponse,
)
def get_knowledge(
    video_id: str,
    db: Session = Depends(get_db),
) -> KnowledgeExtractResponse:
    """Return the persisted knowledge artifact for this video (404 if unset)."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )
    if video.knowledge_extracted_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No knowledge extracted for this video",
        )
    return _build_response(video)

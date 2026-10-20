"""S-1.18.2: frames surfaced to the user (R1, D-067).

Endpoints, all under the tenant's own library (D-063):
  GET  /api/v1/videos/{video_id}/frames                    — the document's frames
  GET  /api/v1/videos/{video_id}/frames/{frame_id}/image   — one still (JPEG)
  POST /api/v1/videos/{video_id}/extract-frames            — capture on demand (202)

A frame is as private as its document: every route resolves the document
through `visibility_service.visible_document`, and a document the caller
cannot see 404s exactly like a missing one. The path parameter may be the
`document_id` or the legacy YouTube id, as on the knowledge routes.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.visual_frame import VisualFrame
from app.schemas.frames import FrameOut, FramesExtractResponse, FramesResponse
from app.services import quota_metering_service, task_routing_service, visibility_service, visual_extraction_service
from app.tasks.visual_tasks import extract_frames

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/videos",
    tags=["frames"],
    dependencies=[Depends(get_current_user)],
)

_NOT_FOUND = "Video not found"


def _visible_video(db: Session, user_id: str, video_id: str):
    doc = visibility_service.visible_document(db, user_id, video_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return doc


def _frames_for(db: Session, doc) -> list[VisualFrame]:
    if not doc.video_id:
        return []
    return (
        db.query(VisualFrame)
        .filter(VisualFrame.video_id == doc.video_id)
        .order_by(VisualFrame.timestamp_seconds)
        .all()
    )


def _safe_image_path(stored: str | None) -> str | None:
    """Absolute path of a stored frame, only if it stays under the frames root.

    `frame_service.resolve_image_path` passes absolute paths straight through,
    so the containment check lives here, where the path meets HTTP.
    """
    if not stored:
        return None
    from app.services.frame_service import resolve_image_path

    root = os.path.realpath(os.path.abspath(settings.VISUAL_FRAMES_DIR))
    path = os.path.realpath(resolve_image_path(stored))
    try:
        inside = os.path.commonpath([root, path]) == root
    except ValueError:  # different drives on Windows
        inside = False
    return path if inside else None


def _frame_out(f: VisualFrame) -> FrameOut:
    from app.services.visual_service import format_timestamp

    path = _safe_image_path(f.image_path)
    return FrameOut(
        frame_id=f.frame_id,
        timestamp_seconds=float(f.timestamp_seconds),
        timestamp_display=format_timestamp(float(f.timestamp_seconds)),
        description=f.description,
        informative=f.informative,
        status=f.status,
        width=f.width,
        height=f.height,
        has_image=bool(path and os.path.exists(path)),
    )


@router.get("/{video_id}/frames", response_model=FramesResponse)
def list_frames(
    video_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> FramesResponse:
    doc = _visible_video(db, current_user.id, video_id)
    return FramesResponse(
        document_id=doc.document_id,
        video_id=doc.video_id,
        visual_enabled=bool(settings.VISUAL_ENABLED),
        in_progress=visual_extraction_service.is_in_progress(doc.document_id),
        frames=[_frame_out(f) for f in _frames_for(db, doc)],
    )


@router.get("/{video_id}/frames/{frame_id}/image")
def frame_image(
    video_id: str,
    frame_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from fastapi.responses import FileResponse

    doc = _visible_video(db, current_user.id, video_id)
    frame = db.query(VisualFrame).filter(VisualFrame.frame_id == frame_id).first()
    # A frame of ANOTHER document 404s like a missing one, so a visible
    # document id cannot be used to read a foreign document's stills.
    if frame is None or not doc.video_id or frame.video_id != doc.video_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame not found")
    path = _safe_image_path(frame.image_path)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frame image missing")
    return FileResponse(
        path,
        media_type="image/jpeg",
        # The bytes never change for a frame id; the cache stays per user.
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post(
    "/{video_id}/extract-frames",
    response_model=FramesExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def extract_frames_for_video(
    video_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> FramesExtractResponse:
    """Queue frame capture for one document (T-1.18.2.4).

    404: missing or not visible. 503: visual analysis is off on this install
    (VISUAL_ENABLED) or its models failed the startup probe. 422: not a
    YouTube video, or no transcript to choose moments from. 409: frames exist
    (pass ``force=true`` to recapture) or a capture is already running. 429:
    monthly `visual_extractions` quota spent.
    """
    doc = _visible_video(db, current_user.id, video_id)

    if not settings.VISUAL_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Visual analysis is turned off on this install (VISUAL_ENABLED).",
        )
    from app.services.llm_smoke import _STATUS

    if "visual_analysis" in _STATUS.unavailable_features():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The vision models failed their startup check; see /health/llm.",
        )
    if doc.source_type != "video" or not doc.video_id:
        raise HTTPException(status_code=422, detail="Frames can only be captured from YouTube videos.")

    from app.models.transcript_cache import TranscriptCache

    if db.query(TranscriptCache.video_id).filter(TranscriptCache.video_id == doc.video_id).first() is None:
        raise HTTPException(status_code=422, detail="No transcript available for this video.")

    if not force and any(f.status == "described" for f in _frames_for(db, doc)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Frames already captured. Pass ?force=true to recapture.",
        )

    quota_metering_service.enforce_quota_or_raise(db, current_user, "visual_extractions")

    if not visual_extraction_service.mark_started(doc.document_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A capture is already running.")
    try:
        task_routing_service.dispatch_for_user(extract_frames, current_user, doc.document_id, current_user.id, force)
    except Exception:
        visual_extraction_service.mark_finished(doc.document_id)
        logger.exception("extract-frames: dispatch failed for %s", doc.document_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue the capture; the task queue is unavailable.",
        )
    return FramesExtractResponse(status="queued", document_id=doc.document_id)

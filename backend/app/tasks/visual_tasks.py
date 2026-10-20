"""S-1.18.2 (T-1.18.2.4): capture and describe frames for ONE document on demand.

The per-job path (``job_tasks._with_visuals``) only runs when a job opts in
before ingest. This task lets a user add frames to a document already in
their library, the way ``/videos/{id}/extract-knowledge`` adds a knowledge
report. Frames are computed once per document and reused by every job and
tenant that can see it (D-067).
"""
from __future__ import annotations

import json
import logging

from app.database import SessionLocal
from app.models.document import Document
from app.services import quota_metering_service, visual_extraction_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="visual.extract_frames", ignore_result=True)
def extract_frames(self, document_id: str, user_id: str, force: bool = False) -> int:
    """Run select -> capture -> describe -> persist; return frames newly captured.

    Quota is charged only when frames were actually captured: a document
    whose frames already existed costs the user nothing, the same rule the
    job budget follows (``run_visual_agent`` returns what it spent).
    """
    from app.agents.visual_agent import run_visual_agent
    from app.config import settings
    from app.models.transcript_cache import TranscriptCache
    from app.services import llm_service

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.document_id == document_id).first()
        if doc is None or not doc.video_id:
            logger.warning("extract_frames: document %s missing or not a video", document_id)
            return 0
        # Read through this task's own session (job_tasks' loader opens a
        # second one), so the whole capture sees one consistent database.
        row = db.query(TranscriptCache).filter(TranscriptCache.video_id == doc.video_id).first()
        try:
            segments = json.loads(row.segments_json) if row else []
        except (TypeError, ValueError):
            segments = []
        if not segments:
            logger.warning("extract_frames: no usable cached transcript for %s", doc.video_id)
            return 0
        with llm_service.byok_context(user_id, db):
            _rows, newly = run_visual_agent(
                db,
                video_id=doc.video_id,
                video_title=doc.title or "",
                channel_name=doc.channel_name or "",
                segments=segments,
                duration_seconds=doc.duration_seconds,
                max_frames=settings.VISUAL_MAX_FRAMES_PER_VIDEO,
                force=force,
            )
        if newly:
            quota_metering_service.record_usage(db, user_id, "visual_extractions")
        logger.info("extract_frames: %s -> %d new frame(s)", document_id, newly)
        return newly
    except Exception:  # noqa: BLE001 - a worker task must not crash the worker
        logger.exception("extract_frames failed for %s", document_id)
        return 0
    finally:
        visual_extraction_service.mark_finished(document_id)
        db.close()

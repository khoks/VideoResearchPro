"""Per-document knowledge extraction endpoints (Unit 4).

Runs the knowledge agent synchronously for the first pass (Celery migration can
come later if the wall-clock becomes an issue). Persists the structured
extraction + Markdown report on the `Document` row.

Every source type can be extracted: the text comes from
`document_text_service.full_text` — the transcript cache for a YouTube video,
the document's reassembled Chroma chunks for a PDF, a pasted page, a thread or
a podcast episode. The path keeps its `/videos/` prefix (and accepts the
legacy YouTube id) for back-compat; any `document_id` works.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.document import Document
from app.schemas.knowledge import KnowledgeExtractResponse
from app.services import document_text_service, visibility_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/videos",
    tags=["knowledge"],
    dependencies=[Depends(get_current_user)],
)


_KNOWLEDGE_KEYS = ("topics", "concepts", "events", "facts")


def _load_merged_from_video(video: Document) -> dict[str, list[str]]:
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


def _build_response(video: Document) -> KnowledgeExtractResponse:
    merged = _load_merged_from_video(video)
    return KnowledgeExtractResponse(
        video_id=video.video_id,
        topics=merged["topics"],
        concepts=merged["concepts"],
        events=merged["events"],
        facts=merged["facts"],
        knowledge_report_md=video.knowledge_report_md or "",
        knowledge_extracted_at=video.knowledge_extracted_at,
        document_id=video.document_id,
        source_type=video.source_type or "video",
        title=video.title,
        channel_name=video.channel_name or None,
        url=video.source_url or video.url or None,
        published_at=video.published_at,
    )


@router.post(
    "/{video_id}/extract-knowledge",
    response_model=KnowledgeExtractResponse,
)
def extract_knowledge(
    video_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> KnowledgeExtractResponse:
    """Run the knowledge agent on this document and persist the artifact.

    Returns 409 if the document already has an extraction unless `?force=true`.
    Returns 404 if the document doesn't exist OR this tenant cannot see it
    (D-063 — indistinguishable on purpose). Returns 422 if neither the
    transcript cache nor the document's chunks hold any text (nothing to
    extract from).
    """
    # The path parameter may be the YouTube `video_id` (back-compat) or the
    # `document_id`. Before 2026-10-19 this looked the row up with no tenant
    # check, so any signed-in user could spend an extraction on — and then
    # read — a document only another tenant had ingested.
    video = visibility_service.visible_document(db, current_user.id, video_id)
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

    # Keyed on the row's document_id (D-070), never on the path parameter:
    # before 2026-10-25 this read `transcript_cache` by `video_id`, which is
    # NULL for every non-video source, so a PDF, a pasted page or a thread
    # always 422'd here.
    source_text = document_text_service.full_text(db, video)
    transcript_text = source_text.text
    if not transcript_text.strip():
        # 422 = unprocessable content: the document exists but has no text to
        # extract from yet (its transcript fetch or ingest has not finished).
        raise HTTPException(
            status_code=422,
            detail="No transcript or text available for this document yet",
        )

    # T-5.5.5: per-user quota check BEFORE the (expensive) agent runs.
    from app.services import quota_metering_service
    quota_metering_service.enforce_quota_or_raise(
        db, current_user, "knowledge_extractions"
    )

    # Import inside the handler so tests that patch
    # `app.routers.knowledge.run_knowledge_extract_agent` work without the
    # real LLM being loaded at import time.
    from app.agents.knowledge_agent import run_knowledge_extract_agent
    from app.services import llm_service

    # T-5.6.4: BYOK context covers both knowledge_extract_batch (map) and
    # knowledge_synthesize_report (reduce) call sites in the agent.
    with llm_service.byok_context(current_user.id, db):
        result = run_knowledge_extract_agent(video, transcript_text)

    # T-5.5.5: track consumption AFTER successful extraction.
    quota_metering_service.record_usage(
        db, current_user.id, "knowledge_extractions"
    )

    merged = {key: list(result.get(key, [])) for key in _KNOWLEDGE_KEYS}
    # S-1.12.8: persist sanity-ceiling metadata (>500K-token transcripts are
    # truncated by the agent) so the artifact records its partial coverage.
    # `_load_merged_from_video` filters to _KNOWLEDGE_KEYS, so readers that
    # only want the four lists are unaffected.
    if result.get("_processing"):
        merged["_processing"] = result["_processing"]
    video.extracted_knowledge_json = json.dumps(merged, ensure_ascii=False)
    video.knowledge_report_md = result.get("knowledge_report_md", "") or ""
    video.knowledge_extracted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(video)

    logger.info(
        "Knowledge extracted for document %s (%s, text from %s): "
        "%d topics, %d concepts, %d events, %d facts",
        video.document_id,
        video.source_type or "video",
        source_text.origin,
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
    current_user=Depends(get_current_user),
) -> KnowledgeExtractResponse:
    """Return the persisted knowledge artifact for this video (404 if unset).

    The artifact lives on the shared `documents` row and is computed once for
    everyone (D-063), but only a tenant who ingested the document may read
    it. Before 2026-10-19 there was no tenant check here at all.
    """
    video = visibility_service.visible_document(db, current_user.id, video_id)
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

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.channel import Channel
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.document import Document
from app.schemas.library_qa import (
    LibraryClarifyRequest,
    LibraryClarifyResponse,
    LibraryQARequest,
    LibraryQAResponse,
    LibraryReference,
)
from app.schemas.library_video import LibrarySort, LibraryVideoResponse
from app.services import chroma_service
from app.services.llm_service import get_llm_for

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/library",
    tags=["library"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/qa/clarify",
    response_model=LibraryClarifyResponse,
)
def clarify_library_question(request: LibraryClarifyRequest) -> LibraryClarifyResponse:
    """Two-step clarify flow: ask the LLM to interpret + suggest clarifications.

    The clarify step doesn't depend on any job context, so we reuse the same
    prompt structure as the job Q&A clarify endpoint.
    """
    llm = get_llm_for("library_qa_clarification", temperature=0.3)

    prompt = (
        f'The user asked: "{request.question}"\n\n'
        "Please: 1) Write a 1-2 sentence interpretation of what they most likely want to know, "
        "2) Generate 3 specific clarifying questions that would help refine the search.\n\n"
        "Return JSON only (no markdown, no code fences) with keys "
        "'interpretation' (string) and 'clarifications' (array of 3 strings):\n"
        '{"interpretation": "...", "clarifications": ["q1", "q2", "q3"]}'
    )

    response = llm.invoke(prompt)
    content = (response.content or "").strip()

    # Strip markdown code fences if the model returns them anyway
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM returned invalid JSON for clarification",
        )

    return LibraryClarifyResponse(
        interpretation=data.get("interpretation", ""),
        clarifications=data.get("clarifications", [])[:3],
    )


@router.post(
    "/qa",
    response_model=LibraryQAResponse,
)
def ask_library_question(
    request: LibraryQARequest,
    db: Session = Depends(get_db),
) -> LibraryQAResponse:
    """Run library-wide Q&A across the global video library and persist the exchange."""
    # Import inside the handler so the agent is only loaded when needed
    # (and so tests that patch ``app.routers.library.run_library_qa_agent``
    # work as expected).
    from app.agents.qa_agent import run_library_qa_agent

    result = run_library_qa_agent(
        question=request.question,
        answer_language=request.answer_language,
    )
    answer = result.get("answer", "")
    references = result.get("references", [])

    exchange = LibraryQAExchange(
        question=request.question,
        answer=answer,
        references_json=json.dumps(references),
        answer_language=request.answer_language,
    )
    db.add(exchange)
    db.commit()
    db.refresh(exchange)

    # Index into the Q&A library collection so it powers the history-chat
    # meta-RAG. Chroma failures must never break the Q&A response.
    try:
        chroma_service.upsert_qa_exchange(exchange, source="library")
    except Exception:
        logger.exception(
            "Failed to upsert library Q&A exchange id=%s into Q&A library",
            exchange.id,
        )

    return LibraryQAResponse(
        id=exchange.id,
        question=exchange.question,
        answer=exchange.answer,
        references=[LibraryReference(**r) for r in references],
        answer_language=exchange.answer_language,
        created_at=exchange.created_at,
    )


@router.get(
    "/qa",
    response_model=list[LibraryQAResponse],
)
def get_library_qa_history(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[LibraryQAResponse]:
    """Return library Q&A history ordered by created_at ASC (job convention)."""
    exchanges = (
        db.query(LibraryQAExchange)
        .order_by(LibraryQAExchange.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: list[LibraryQAResponse] = []
    for qa in exchanges:
        try:
            raw_refs = json.loads(qa.references_json)
            refs = [LibraryReference(**r) for r in raw_refs]
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "Failed to parse references_json for library_qa_exchange id=%s",
                qa.id,
            )
            refs = []
        results.append(LibraryQAResponse(
            id=qa.id,
            question=qa.question,
            answer=qa.answer,
            references=refs,
            answer_language=qa.answer_language,
            created_at=qa.created_at,
        ))
    return results


@router.delete(
    "/qa/{exchange_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_library_qa_exchange(
    exchange_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Delete a single library Q&A exchange."""
    exchange = db.get(LibraryQAExchange, exchange_id)
    if not exchange:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library Q&A exchange not found",
        )
    db.delete(exchange)
    db.commit()


@router.get(
    "/videos",
    response_model=list[LibraryVideoResponse],
)
def list_library_videos(
    search: str | None = None,
    language: str | None = None,
    channel_id: str | None = None,
    transcript_status: str | None = None,
    sort: LibrarySort = "newest",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[LibraryVideoResponse]:
    """Browse the global, deduplicated video library.

    Filters: free-text search across title and channel name, transcript
    language, channel_id, and transcript_status. Sort by recency or duration.
    Each row carries an aggregated `job_count` and `job_titles[]` so the UI
    can show "appears in N research runs" without follow-up requests.
    """
    q = db.query(Document).outerjoin(Channel, Document.channel_id == Channel.channel_id)

    if search:
        like = f"%{search}%"
        q = q.filter(or_(Document.title.ilike(like), Channel.name.ilike(like)))
    if language:
        q = q.filter(Document.transcript_language == language)
    if channel_id:
        q = q.filter(Document.channel_id == channel_id)
    if transcript_status:
        q = q.filter(Document.transcript_status == transcript_status)

    if sort == "newest":
        q = q.order_by(Document.created_at.desc())
    elif sort == "oldest":
        q = q.order_by(Document.created_at.asc())
    elif sort == "longest":
        q = q.order_by(Document.duration_seconds.desc())
    elif sort == "shortest":
        q = q.order_by(Document.duration_seconds.asc())

    videos = q.offset(offset).limit(limit).all()

    if not videos:
        return []

    video_ids = [v.video_id for v in videos]

    # One round-trip to fetch (video_id -> distinct job topics) for the page.
    rows = (
        db.query(JobVideo.video_id, Job.topic)
        .join(Job, Job.id == JobVideo.job_id)
        .filter(JobVideo.video_id.in_(video_ids))
        .all()
    )
    titles_by_video: dict[str, list[str]] = {}
    for vid, topic in rows:
        if not topic:
            continue
        bucket = titles_by_video.setdefault(vid, [])
        if topic not in bucket:
            bucket.append(topic)

    counts_by_video: dict[str, int] = dict(
        db.query(JobVideo.video_id, func.count(func.distinct(JobVideo.job_id)))
        .filter(JobVideo.video_id.in_(video_ids))
        .group_by(JobVideo.video_id)
        .all()
    )

    return [
        LibraryVideoResponse(
            id=v.video_id,
            video_id=v.video_id,
            title=v.title,
            channel_id=v.channel_id,
            channel_name=v.channel_name,
            url=v.url,
            thumbnail_url=v.thumbnail_url,
            duration_seconds=v.duration_seconds,
            published_at=v.published_at,
            transcript_status=v.transcript_status,
            transcript_language=v.transcript_language,
            transcript_word_count=v.transcript_word_count,
            job_count=counts_by_video.get(v.video_id, 0),
            job_titles=titles_by_video.get(v.video_id, []),
        )
        for v in videos
    ]

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
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
from app.sources.pdf.connector import (
    SOURCE_ID_PREFIX as PDF_SOURCE_ID_PREFIX,
    hash_pdf_bytes,
    upload_path_for_source_id,
)
from app.sources import connector_for as _connector_for
from app.utils.chunking import chunk_transcript
from app.tasks.job_tasks import _build_video_metadata

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


# ---------------------------------------------------------------------------
# PDF upload (M-1.8)
# ---------------------------------------------------------------------------
# PDFs are the first source type with no discovery surface — they
# come from upload directly. This endpoint:
#   1. Accepts a multipart PDF file.
#   2. Hashes the first 64KB to derive a stable Document.source_id.
#   3. Persists raw bytes to PDF_UPLOAD_DIR/<source_id>.pdf.
#   4. Inserts a Document row with source_type='pdf', triggering the
#      same per-document polymorphic Chroma metadata flow as every
#      other source type.
#   5. Calls the connector's `fetch_text` to extract per-page
#      segments + chunk + embed into the global Chroma collection.
#   6. Returns the document_id so the frontend can navigate to its
#      library detail view.
#
# The endpoint is library-scoped (not job-scoped) because PDFs sit
# in the global library and participate in library-wide Q&A
# regardless of any specific research job.


@router.post("/upload-pdf", status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a PDF and ingest it into the global library.

    Returns ``{document_id, source_id, page_count, word_count, deduped}``.
    `deduped=True` indicates the same file (by first-64KB hash) was
    already in the library — the existing Document row is returned
    rather than a duplicate created.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload must be a .pdf file",
        )
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(pdf_bytes) > settings.PDF_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"PDF exceeds {settings.PDF_MAX_BYTES // (1024 * 1024)}MB limit; "
                "split the document or raise PDF_MAX_BYTES"
            ),
        )

    # Derive stable source_id and persist raw bytes (idempotent —
    # re-uploads of the same file dedup at the (source_type,
    # source_id) unique index).
    digest = hash_pdf_bytes(pdf_bytes)
    source_id = f"{PDF_SOURCE_ID_PREFIX}{digest}"

    existing = (
        db.query(Document)
        .filter(Document.source_type == "pdf", Document.source_id == source_id)
        .one_or_none()
    )
    if existing is not None:
        return {
            "document_id": existing.document_id,
            "source_id": existing.source_id,
            "page_count": (
                json.loads(existing.source_metadata_json or "{}").get("page_count")
                if existing.source_metadata_json
                else None
            ),
            "word_count": existing.word_count,
            "deduped": True,
        }

    # Persist raw bytes.
    os.makedirs(settings.PDF_UPLOAD_DIR, exist_ok=True)
    path = upload_path_for_source_id(source_id)
    try:
        with open(path, "wb") as out:
            out.write(pdf_bytes)
    except OSError as e:
        logger.exception("PDF upload: write failed for %s", path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not persist PDF: {e}",
        )

    # Build the source_url that fetch_text will use to synthesise
    # per-page #page=<N> deep-links. Served path mirrors the upload
    # directory layout; a future PR can add a static-file route or
    # signed-URL handler if needed.
    source_url = f"/api/v1/library/pdf/{digest}.pdf"

    # Create the Document row first so the chunking pipeline has
    # something to attach metadata to. fetch_text below populates
    # transcript_word_count + extracted page_count.
    title = file.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if title.lower().endswith(".pdf"):
        title = title[:-4]
    doc = Document(
        source_type="pdf",
        source_id=source_id,
        source_url=source_url,
        title=title or "Untitled PDF",
        url=source_url,
        transcript_status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Run extraction immediately (PDFs don't have an async fetch
    # phase like videos / podcasts — extraction is pure-CPU and
    # bounded). Plug into the same Chroma write path as every
    # other source type.
    connector = _connector_for("pdf")
    from app.sources.types import Candidate

    cand = Candidate(
        source_type="pdf",
        source_id=source_id,
        title=doc.title,
        source_url=source_url,
    )
    extracted = connector.fetch_text(cand)
    if extracted is None:
        # Extraction failed — keep the Document + raw bytes (operator
        # can re-extract later) but report the failure to the user.
        doc.transcript_status = "unavailable"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "PDF was uploaded but text extraction yielded no segments — "
                "the file may be image-only (OCR not yet supported) or corrupt"
            ),
        )

    # Persist extraction summary on the Document row.
    page_count = extracted.extra.get("page_count") if extracted.extra else None
    doc.word_count = extracted.word_count
    doc.transcript_word_count = extracted.word_count
    doc.transcript_language = extracted.language
    doc.transcript_source = "pdf"
    doc.language = extracted.language
    doc.source_metadata_json = json.dumps({"page_count": page_count})
    doc.transcript_status = "fetched"
    db.commit()

    # Chunk + embed via the polymorphic chunker. Build the metadata
    # dict the same way `_build_video_metadata` does so the per-document
    # polymorphic fields (`source_type`, `source_id`, `permalink`,
    # `author`, `subreddit`, `instance`) flow into Chroma — and so
    # the per-segment `comment_id` / `comment_url` / `kind` / `depth`
    # the PDF flatten module emits land on chunk metadata via the
    # dominant-segment heuristic.
    video_metadata = _build_video_metadata(doc, language=extracted.language)
    chunks = chunk_transcript(
        extracted.segments,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        video_metadata=video_metadata,
        transcription_source="pdf",
    )
    chroma_service.insert_chunks(chunks)
    doc.embedded_in_chroma = True
    db.commit()

    return {
        "document_id": doc.document_id,
        "source_id": source_id,
        "page_count": page_count,
        "word_count": extracted.word_count,
        "deduped": False,
    }


@router.get("/pdf/{digest}.pdf")
def serve_pdf(digest: str, db: Session = Depends(get_db)):
    """Serve an uploaded PDF by digest.

    Used by the per-page deep-link citation rendering — clicking a
    PDF citation in the Q&A response opens this URL with the
    `#page=<N>` fragment so the user's PDF viewer jumps to the page.
    """
    from fastapi.responses import FileResponse

    source_id = f"{PDF_SOURCE_ID_PREFIX}{digest}"
    # Sanity check that the document exists in our library before
    # serving the file (prevents serving arbitrary uploads via path
    # manipulation).
    existing = (
        db.query(Document)
        .filter(Document.source_type == "pdf", Document.source_id == source_id)
        .one_or_none()
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF not in library",
        )
    path = upload_path_for_source_id(source_id)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF file missing from upload directory",
        )
    return FileResponse(path, media_type="application/pdf", filename=f"{existing.title}.pdf")

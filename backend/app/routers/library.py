import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.prompts.qa_prompts import with_clarification
from app.config import settings
from app.dependencies import get_current_user, get_db
from pydantic import BaseModel

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
from app.schemas.qa_scope import QAScope
from app.schemas.graph import GraphResponse
from app.schemas.tag import TagSummary
from app.services import library_qa_service
from app.services import chroma_service
from app.services import document_cap_service
from app.services import graph_service, library_query_service, qa_scope_service, tag_service, visibility_service
from app.services.llm_service import get_llm_for
from app.sources.pdf.connector import (
    SOURCE_ID_PREFIX as PDF_SOURCE_ID_PREFIX,
    hash_pdf_bytes,
    upload_path_for_source_id,
)
from app.sources.paste_url.connector import hash_url
from app.sources import connector_for as _connector_for
from app.services.paste_url_resolver import resolve_source_type
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
    # S-1.12.7: clarify returns a tiny JSON blob — cap runaway completions.
    llm = get_llm_for("library_qa_clarification", temperature=0.3, max_tokens=400)

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
    current_user=Depends(get_current_user),
) -> LibraryQAResponse:
    """Run library-wide Q&A across the global video library and persist the exchange."""
    return answer_library_question(db, current_user, request, scope=None)


# Moved to the shared core (T-8.3.3.6); kept for callers that import it here.
_within_scope = library_qa_service.within_scope


def answer_library_question(
    db: Session,
    current_user,
    request: LibraryQARequest,
    scope: QAScope | None,
) -> LibraryQAResponse:
    """Ask the library agent over ``scope`` and persist the exchange.

    One path for the whole library (``scope=None``, ``POST /library/qa``) and
    for narrowed scopes such as a shelf (``POST /shelves/{id}/qa``, S-8.1.4),
    so quota, corpus statistics, trust weights and the Q&A library index work
    the same everywhere. Raises ``qa_scope_service.ScopeNotFound`` for a scope
    that is not the caller's; the route turns it into a 404.
    """
    # S-5.7.1 / S-8.1.4: the scope's documents (inside the visible set; an
    # empty list retrieves nothing) and the notes it may draw on, through the
    # core a saved search's run shares (T-8.3.3.6). Resolved first, so a
    # foreign shelf is a 404 before any quota is checked.
    prepared = library_qa_service.prepare(db, current_user.id, scope)

    # T-5.5.5: per-user quota check BEFORE the (expensive) agent runs.
    from app.services import quota_metering_service
    quota_metering_service.enforce_quota_or_raise(
        db, current_user, "library_qa_exchanges"
    )

    result = library_qa_service.ask(
        db,
        current_user.id,
        prepared,
        # S-8.13.1: the reader's clarify answers reach the agent inside the
        # question, as in job Q&A; the exchange below stores what they typed.
        question=with_clarification(request.question, request.context),
        answer_language=request.answer_language,
        output_length=request.output_length,
    )

    # T-5.5.5: track consumption.
    quota_metering_service.record_usage(
        db, current_user.id, "library_qa_exchanges"
    )
    answer = result.answer
    references = result.references

    # Per E-5.1 phase 2a, stamp tenant_id from the authenticated user.
    exchange = LibraryQAExchange(
        question=request.question,
        answer=answer,
        references_json=json.dumps(references),
        answer_language=request.answer_language,
        tenant_id=current_user.id,
        scope_json=qa_scope_service.dump(scope),
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

    # S-3.3.2: the question is the user's own words, so Echo may learn
    # from it. Fail-soft and cheap until enough new text is waiting.
    from app.services import echo_signal_extraction

    echo_signal_extraction.maybe_queue(db, current_user.id)

    return library_exchange_response(exchange)


@router.get(
    "/qa",
    response_model=list[LibraryQAResponse],
)
def get_library_qa_history(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[LibraryQAResponse]:
    """Return library Q&A history ordered by created_at ASC (job convention).

    Per E-5.1 phase 2b, filtered to the authenticated user's tenant.
    """
    exchanges = (
        db.query(LibraryQAExchange)
        .filter(LibraryQAExchange.tenant_id == current_user.id)
        .order_by(LibraryQAExchange.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [library_exchange_response(qa) for qa in exchanges]


def library_exchange_response(qa: LibraryQAExchange) -> LibraryQAResponse:
    """One stored exchange as the API returns it (library and shelf history).

    Citations are parsed one by one: a malformed entry is skipped (and
    logged) instead of emptying the exchange's whole list.
    """
    try:
        raw_refs = json.loads(qa.references_json or "[]")
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse references_json for library_qa_exchange id=%s", qa.id)
        raw_refs = []
    refs: list[LibraryReference] = []
    for r in raw_refs if isinstance(raw_refs, list) else []:
        try:
            refs.append(LibraryReference(**r))
        except (TypeError, ValueError):
            logger.warning("Skipped a malformed citation on library_qa_exchange id=%s", qa.id)
    return LibraryQAResponse(
        id=qa.id,
        question=qa.question,
        answer=qa.answer,
        references=refs,
        answer_language=qa.answer_language,
        created_at=qa.created_at,
        scope=qa_scope_service.load(qa.scope_json),
    )


@router.delete(
    "/qa/{exchange_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_library_qa_exchange(
    exchange_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    """Delete a single library Q&A exchange.

    S-5.7.1: this previously fetched by primary key alone and deleted, so any
    authenticated user could destroy any other user's exchange by guessing or
    observing an id. The tenant filter is part of the lookup — not a check
    after the fact — so a foreign id is indistinguishable from a missing one
    and the 404 leaks nothing about what exists.
    """
    exchange = (
        db.query(LibraryQAExchange)
        .filter(
            LibraryQAExchange.id == exchange_id,
            LibraryQAExchange.tenant_id == current_user.id,
        )
        .first()
    )
    if not exchange:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library Q&A exchange not found",
        )
    db.delete(exchange)
    db.commit()


@router.get("/graph", response_model=GraphResponse)
def library_graph(
    focus: str | None = None,
    depth: int = Query(default=1, ge=1, le=graph_service.MAX_DEPTH),
    shelf_id: str | None = None,
    channel_id: str | None = None,
    job_id: str | None = None,
    types: str | None = None,
    limit: int = Query(default=graph_service.DEFAULT_LIMIT, ge=1, le=graph_service.MAX_LIMIT),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> GraphResponse:
    """The reader's library as a graph (S-8.9.1): visible documents, their
    channels and knowledge topics, and the reader's own answers that cite
    them. ``focus`` (a node id) returns its neighbourhood to ``depth`` hops;
    ``shelf_id`` / ``job_id`` / ``channel_id`` narrow the documents (a
    foreign shelf or job is a 404); ``types`` picks node types besides
    documents. An empty visible set is an empty graph (D-063)."""
    try:
        return graph_service.build_graph(
            db,
            current_user.id,
            focus=focus,
            depth=depth,
            shelf_id=shelf_id,
            channel_id=channel_id,
            job_id=job_id,
            types=[t.strip() for t in types.split(",")] if types else None,
            limit=limit,
        )
    except graph_service.GraphScopeNotFound as exc:
        raise HTTPException(status_code=404, detail=f"{str(exc).capitalize()} not found")


MAX_VIDEO_CHANNEL_LOOKUP = 200


class VideoChannel(BaseModel):
    channel_id: str
    channel_name: str


@router.get("/video-channels", response_model=dict[str, VideoChannel])
def resolve_video_channels(
    video_ids: str = Query(..., description="Comma-separated YouTube video ids"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, VideoChannel]:
    """Map cited YouTube video ids to their channel (S-8.7.4), so a citation
    chip can link to the channel page. Only documents the caller can see
    answer (D-063 / D-070); unknown or invisible ids are simply absent, so the
    response never confirms that another reader holds a document. At most
    ``MAX_VIDEO_CHANNEL_LOOKUP`` distinct ids per call.

    Resolved at read time rather than stored on Q&A references, so every
    existing answer gains the link without touching the Q&A agent."""
    ids = [v.strip() for v in dict.fromkeys(video_ids.split(",")) if v.strip()]
    ids = ids[:MAX_VIDEO_CHANNEL_LOOKUP]
    if not ids:
        return {}
    rows = (
        db.query(Document.video_id, Document.channel_id, Channel.name)
        .join(Channel, Channel.channel_id == Document.channel_id)
        .filter(
            Document.video_id.in_(ids),
            Document.document_id.in_(visibility_service.visible_document_ids(db, current_user.id)),
        )
        .all()
    )
    return {
        vid: VideoChannel(channel_id=channel_id, channel_name=name or "")
        for vid, channel_id, name in rows
    }


@router.get(
    "/videos",
    response_model=list[LibraryVideoResponse],
)
def list_library_videos(
    search: str | None = None,
    language: str | None = None,
    channel_id: str | None = None,
    transcript_status: str | None = None,
    tag: str | None = None,
    document_id: str | None = None,
    sort: LibrarySort = "newest",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[LibraryVideoResponse]:
    """Browse the caller's view of the deduplicated video library.

    Filters: free-text search across title and channel name, transcript
    language, channel_id, and transcript_status. Sort by recency or duration.
    Each row carries an aggregated `job_count` and `job_titles[]` so the UI
    can show "appears in N research runs" without follow-up requests.

    S-5.7.1 — shared cache, private catalogue: `documents` remains the global
    deduplicated store (that is what makes transcripts and embeddings
    compute-once), but this listing is restricted to documents THIS tenant
    ingested. Previously it returned every document plus the *job topics* of
    every other user — leaking not just what others had ingested but what they
    were researching.
    """
    return query_library_documents(
        db,
        current_user.id,
        search=search,
        language=language,
        channel_id=channel_id,
        transcript_status=transcript_status,
        tag_id=tag,
        document_id=document_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )


def query_library_documents(
    db: Session,
    tenant_id: str,
    *,
    search: str | None = None,
    language: str | None = None,
    channel_id: str | None = None,
    transcript_status: str | None = None,
    tag_id: str | None = None,
    sort: LibrarySort = "newest",
    limit: int = 50,
    offset: int = 0,
    job_ids: list[str] | None = None,
    document_id: str | None = None,
) -> list[LibraryVideoResponse]:
    """The library listing as a plain function, so other surfaces (the shelf
    page, S-8.1.2) can reuse the filters, the visibility scope and the
    per-row job aggregation without a second copy of the query.

    ``job_ids`` restricts the result to documents selected by those jobs
    (joined on ``job_documents.document_id``). An EMPTY list returns nothing
    rather than everything — the D-063 posture: a narrower scope never
    widens to the whole library by accident.
    """
    # One builder for the listing and for scoped Q&A (S-8.1.4), so a shelf
    # means the same documents in its list and in its answers.
    q = library_query_service.documents_query(
        db,
        tenant_id,
        job_ids=job_ids,
        search=search,
        language=language,
        channel_id=channel_id,
        transcript_status=transcript_status,
        tag_id=tag_id,
        document_id=document_id,
    )
    if q is None:
        return []

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

    document_ids = [v.document_id for v in videos]

    # One round-trip to fetch (document_id -> distinct job topics) for the page.
    rows = (
        db.query(JobVideo.document_id, Job.topic)
        .join(Job, Job.id == JobVideo.job_id)
        .filter(
            JobVideo.document_id.in_(document_ids),
            # Never surface another tenant's research topic against a shared
            # document — the topic string is the more sensitive half of this.
            Job.tenant_id == tenant_id,
        )
        .all()
    )
    titles_by_document: dict[str, list[str]] = {}
    for did, topic in rows:
        if not topic:
            continue
        bucket = titles_by_document.setdefault(did, [])
        if topic not in bucket:
            bucket.append(topic)

    counts_by_document: dict[str, int] = dict(
        db.query(JobVideo.document_id, func.count(func.distinct(JobVideo.job_id)))
        .join(Job, Job.id == JobVideo.job_id)
        .filter(JobVideo.document_id.in_(document_ids), Job.tenant_id == tenant_id)
        .group_by(JobVideo.document_id)
        .all()
    )

    tags_by_document = tag_service.tags_for_documents(db, tenant_id, document_ids)

    # D-070: `id` is the primary key; `video_id` is the legacy YouTube id and
    # is None for every non-video source, as is `duration_seconds`.
    return [
        LibraryVideoResponse(
            id=v.document_id,
            video_id=v.video_id,
            source_type=v.source_type or "video",
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
            job_count=counts_by_document.get(v.document_id, 0),
            job_titles=titles_by_document.get(v.document_id, []),
            tags=tags_by_document.get(v.document_id, []),
        )
        for v in videos
    ]


# ---------------------------------------------------------------------------
# Tags on documents (S-8.1.3)
# ---------------------------------------------------------------------------


def _tag_and_document_or_404(db: Session, tenant_id: str, document_id: str, tag_id: str):
    tag = tag_service.get_tag(db, tag_id, tenant_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag_service.visible_document(db, tenant_id, document_id) is None:
        # Invisible and nonexistent read the same (D-063 existence-leak posture).
        raise HTTPException(status_code=404, detail="Document not found")
    return tag


@router.put("/videos/{document_id}/tags/{tag_id}", response_model=list[TagSummary])
def apply_document_tag(
    document_id: str,
    tag_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[TagSummary]:
    """Tag a document the caller can see. Idempotent. Returns the caller's
    tags now on the document, A→Z."""
    tag = _tag_and_document_or_404(db, current_user.id, document_id, tag_id)
    tag_service.apply_tag(db, tag, document_id)
    return tag_service.tags_for_documents(db, current_user.id, [document_id]).get(document_id, [])


@router.delete("/videos/{document_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document_tag(
    document_id: str,
    tag_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    tag = _tag_and_document_or_404(db, current_user.id, document_id, tag_id)
    if not tag_service.remove_tag(db, tag, document_id):
        raise HTTPException(status_code=404, detail="Document does not carry this tag")


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
    current_user=Depends(get_current_user),
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
    # T-5.2.10: the document cap, before the bytes are written. Re-uploading
    # a PDF this tenant already sees adds nothing and is never refused.
    document_cap_service.enforce(
        db,
        current_user,
        action=document_cap_service.ACTION_UPLOAD,
        document_ids=[existing.document_id] if existing is not None else (),
        unseen=0 if existing is not None else 1,
    )
    if existing is not None:
        # Dedup hit: the bytes are already cached, but this tenant may never
        # have seen them. Grant, then return (S-5.7.1).
        visibility_service.grant(
            db, [existing.document_id], current_user.id, visibility_service.SOURCE_PDF
        )
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
    visibility_service.grant(
        db, [doc.document_id], current_user.id, visibility_service.SOURCE_PDF
    )

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


# ---------------------------------------------------------------------------
# URL paste-mode (S-1.5.8)
# ---------------------------------------------------------------------------
# Closes Mode B paste support per [D-005](docs/decisions.md) (social-
# media before article-ingest) + [D-008](docs/decisions.md) (no
# search-page scraping on FB/IG/LI). User pastes 1-N URLs from any
# supported platform; the endpoint resolves each URL to a source_type
# (article / fb_post / ig_post / li_post / tweet) via host-based
# routing, runs the article-extraction primitives (trafilatura
# primary, Playwright fallback when ARTICLE_PLAYWRIGHT_ENABLED), and
# creates Documents with the right per-platform discriminator.


@router.post("/paste-urls", status_code=status.HTTP_201_CREATED)
def paste_urls(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Ingest 1-N pasted URLs into the global library.

    Body shape: ``{"urls": ["https://...", "https://...", ...]}``.

    Returns ``{"results": [{url, document_id, source_id, source_type,
    word_count, status, deduped}, ...]}`` with one entry per URL.
    Per-URL `status` is ``"created"`` / ``"deduped"`` / ``"extraction_failed"`` /
    ``"invalid_url"`` so the caller (frontend) can show per-URL state
    rather than failing the whole batch on one bad URL.
    """
    urls = payload.get("urls")
    if not isinstance(urls, list) or not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must contain a non-empty 'urls' list",
        )
    if len(urls) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 URLs per paste batch",
        )

    _enforce_paste_cap(urls, db, current_user)

    results: list[dict] = []
    for raw in urls:
        result = _ingest_single_paste_url(raw, db, current_user)
        results.append(result)
    return {"results": results}


def _enforce_paste_cap(urls: list, db: Session, current_user) -> None:
    """T-5.2.10: refuse the whole batch (429) when the documents it would add
    do not fit under the caller's cap, before any page is fetched.

    Counted the way ``_ingest_single_paste_url`` resolves each entry: the
    same source id twice is one document, an existing document the caller
    already sees is a dedup hit and does not count, and an entry with no
    document yet counts even though its extraction may still fail (the
    estimate errs towards refusing, never past the cap).
    """
    if document_cap_service.cap_for(current_user) < 0:
        return
    source_ids: dict[tuple[str, str], None] = {}
    for raw in urls:
        if not isinstance(raw, str) or not raw.strip():
            continue
        url = raw.strip()
        source_type = resolve_source_type(url)
        source_ids[(source_type, f"{source_type}:{hash_url(url)}")] = None
    if not source_ids:
        return
    existing = {
        (row.source_type, row.source_id): row.document_id
        for row in db.query(Document.source_type, Document.source_id, Document.document_id).filter(
            Document.source_id.in_([sid for _, sid in source_ids])
        )
    }
    known = [existing[k] for k in source_ids if k in existing]
    document_cap_service.enforce(
        db,
        current_user,
        action=document_cap_service.ACTION_PASTE,
        document_ids=known,
        unseen=len(source_ids) - len(known),
    )


def _ingest_single_paste_url(url: str, db: Session, current_user) -> dict:
    """Ingest a single URL — typed result dict for the batch response.

    ``current_user`` is threaded through because the visibility grant
    (D-063) is per tenant — before 2026-10-19 this helper referenced
    ``current_user`` from the caller's scope, which does not exist at
    module level, so every non-invalid URL raised ``NameError``.
    """
    if not isinstance(url, str) or not url.strip():
        return {"url": str(url), "status": "invalid_url"}
    url = url.strip()

    source_type = resolve_source_type(url)
    digest = hash_url(url)
    source_id = f"{source_type}:{digest}"

    existing = (
        db.query(Document)
        .filter(Document.source_type == source_type, Document.source_id == source_id)
        .one_or_none()
    )
    if existing is not None:
        visibility_service.grant(
            db, [existing.document_id], current_user.id, visibility_service.SOURCE_PASTE
        )
        return {
            "url": url,
            "document_id": existing.document_id,
            "source_id": source_id,
            "source_type": source_type,
            "word_count": existing.word_count,
            "status": "deduped",
            "deduped": True,
        }

    # Build the candidate so the connector can do its thing.
    from app.sources.types import Candidate

    cand = Candidate(
        source_type=source_type,
        source_id=source_id,
        title=url,  # placeholder — overwritten when extract_text returns a title
        source_url=url,
    )
    connector = _connector_for(source_type)
    extracted = connector.fetch_text(cand)
    if extracted is None:
        return {
            "url": url,
            "source_type": source_type,
            "status": "extraction_failed",
        }

    # Pull title / author from the extractor's metadata for the
    # Document row. trafilatura emits these into `extracted.extra`
    # via the paste connector's `_PasteURLBaseConnector.fetch_text`.
    extracted_extra = extracted.extra or {}
    title = (extracted_extra.get("extracted_title") or url)[:500]
    author = (extracted_extra.get("extracted_author") or "")[:200]

    doc = Document(
        source_type=source_type,
        source_id=source_id,
        source_url=url,
        title=title,
        url=url,
        transcript_status="fetched",
        transcript_language=extracted.language,
        transcript_word_count=extracted.word_count,
        transcript_source=extracted.text_source,
        language=extracted.language,
        word_count=extracted.word_count,
        source_metadata_json=json.dumps(
            {
                "author": author,
                "extractor": extracted_extra.get("extractor_source", ""),
            }
        ),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    visibility_service.grant(
        db, [doc.document_id], current_user.id, visibility_service.SOURCE_PASTE
    )

    # Chunk + embed via the polymorphic chunker. _build_video_metadata
    # carries the per-document polymorphic fields (source_type,
    # permalink, author) into Chroma per S-1.5.12.
    video_metadata = _build_video_metadata(doc, language=extracted.language)
    chunks = chunk_transcript(
        extracted.segments,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        video_metadata=video_metadata,
        transcription_source=extracted.text_source,
    )
    chroma_service.insert_chunks(chunks)
    doc.embedded_in_chroma = True
    db.commit()

    return {
        "url": url,
        "document_id": doc.document_id,
        "source_id": source_id,
        "source_type": source_type,
        "word_count": extracted.word_count,
        "status": "created",
        "deduped": False,
    }


@router.get("/pdf/{digest}.pdf")
def serve_pdf(
    digest: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
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
    # D-063: the bytes are only served to a tenant who ingested this PDF.
    # Before 2026-10-19 any signed-in user holding the digest could fetch
    # another tenant's upload; a foreign PDF now 404s like a missing one.
    existing = (
        db.query(Document)
        .filter(
            Document.source_type == "pdf",
            Document.source_id == source_id,
            Document.document_id.in_(
                visibility_service.visible_document_ids(db, current_user.id)
            ),
        )
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

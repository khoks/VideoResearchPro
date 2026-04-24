import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.library_qa_exchange import LibraryQAExchange
from app.schemas.library_qa import (
    LibraryClarifyRequest,
    LibraryClarifyResponse,
    LibraryQARequest,
    LibraryQAResponse,
    LibraryReference,
)
from app.services import chroma_service
from app.services.llm_routing import resolve_route
from app.services.llm_service import get_llm

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
    llm = get_llm(temperature=0.3, purpose=resolve_route("library_qa_clarification"))

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

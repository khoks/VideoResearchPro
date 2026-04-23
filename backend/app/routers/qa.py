import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_user_from_query_or_header
from app.models.qa_exchange import QAExchange
from app.schemas.qa import ClarifyRequest, ClarifyResponse, QARequest, QAResponse, Reference
from app.services import chroma_service, job_service, report_service
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)

# Per-route auth because /report accepts a query-string token fallback
# (iframes can't set Authorization headers) while the rest of this router
# requires a header-bearer JWT.
router = APIRouter(
    prefix="/jobs/{job_id}",
    tags=["qa"],
)


@router.get(
    "/report",
    response_class=HTMLResponse,
    dependencies=[Depends(get_user_from_query_or_header)],
)
def get_report(job_id: str, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.report_path:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    html = report_service.get_report_html(job.report_path)
    if not html:
        raise HTTPException(status_code=404, detail="Report file not found")
    return HTMLResponse(content=html)


@router.post(
    "/qa/clarify",
    response_model=ClarifyResponse,
    dependencies=[Depends(get_current_user)],
)
def clarify_question(job_id: str, request: ClarifyRequest, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    llm = get_llm(temperature=0.3, purpose="fast")

    prompt = (
        f'The user asked: "{request.question}"\n\n'
        "Please: 1) Write a 1-2 sentence interpretation of what they most likely want to know, "
        "2) Generate 3 specific clarifying questions that would help refine the search.\n\n"
        "Return JSON only (no markdown, no code fences) with keys "
        "'interpretation' (string) and 'clarifications' (array of 3 strings):\n"
        '{"interpretation": "...", "clarifications": ["q1", "q2", "q3"]}'
    )

    response = llm.invoke(prompt)
    content = response.content.strip()

    # Strip markdown code fences if the model returns them anyway
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON for clarification")

    return ClarifyResponse(
        interpretation=data.get("interpretation", ""),
        clarifications=data.get("clarifications", [])[:3],
    )


@router.post(
    "/qa",
    response_model=QAResponse,
    dependencies=[Depends(get_current_user)],
)
def ask_question(job_id: str, request: QARequest, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    # Get report HTML for topic jobs
    report_html = None
    if job.job_type == "topic" and job.report_path:
        report_html = report_service.get_report_html(job.report_path)

    # Build enriched question when the user provided clarification context
    enriched_question = request.question
    if request.context:
        enriched_question = f"{request.question}\n\nAdditional context from user:\n{request.context}"

    # Run Q&A agent
    from app.agents.qa_agent import run_qa_agent
    answer, references = run_qa_agent(
        job_id=job_id,
        job_type=job.job_type,
        question=enriched_question,
        report_html=report_html,
    )

    # Save original question to DB (not the enriched version)
    qa = QAExchange(
        job_id=job_id,
        question=request.question,
        answer=answer,
        references=json.dumps([r for r in references]),
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)

    # Index into the Q&A library collection so it powers the history-chat
    # meta-RAG. Chroma failures must never break the Q&A response.
    try:
        chroma_service.upsert_qa_exchange(qa, source="job")
    except Exception:
        logger.exception(
            f"Failed to upsert job Q&A exchange id={qa.id} into Q&A library"
        )

    return QAResponse(
        id=qa.id,
        question=qa.question,
        answer=qa.answer,
        references=[Reference(**r) for r in references],
        created_at=qa.created_at,
    )


@router.get(
    "/qa",
    response_model=list[QAResponse],
    dependencies=[Depends(get_current_user)],
)
def get_qa_history(job_id: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    exchanges = (
        db.query(QAExchange)
        .filter(QAExchange.job_id == job_id)
        .order_by(QAExchange.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = []
    for qa in exchanges:
        try:
            refs = [Reference(**r) for r in json.loads(qa.references)]
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse references JSON for qa_exchange id={qa.id}")
            refs = []
        results.append(QAResponse(
            id=qa.id,
            question=qa.question,
            answer=qa.answer,
            references=refs,
            created_at=qa.created_at,
        ))
    return results

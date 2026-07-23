import asyncio
import json
import logging
import queue

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_user_from_query_or_header
from app.models.qa_exchange import QAExchange
from app.schemas.qa import ClarifyRequest, ClarifyResponse, QARequest, QAResponse, Reference
from app.services import chroma_service, job_service, quota_metering_service, report_service
from app.services.llm_service import get_llm_for

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
)
def get_report(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_user_from_query_or_header),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
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
)
def clarify_question(
    job_id: str,
    request: ClarifyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    llm = get_llm_for("qa_clarification", temperature=0.3)

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


def _load_completed_job(db: Session, job_id: str, current_user):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")
    return job


def _run_qa_and_persist(
    db: Session,
    job,
    request: QARequest,
    current_user,
    progress_callback=None,
) -> tuple[QAExchange, list[dict]]:
    """Run the Q&A agent and persist the exchange + token accounting.

    Shared by the sync /qa endpoint and the SSE /qa/stream endpoint.
    Quota must be enforced by the caller BEFORE invoking this.
    """
    # Get report HTML for topic jobs
    report_html = None
    if job.job_type == "topic" and job.report_path:
        report_html = report_service.get_report_html(job.report_path)

    # Build enriched question when the user provided clarification context
    enriched_question = request.question
    if request.context:
        enriched_question = f"{request.question}\n\nAdditional context from user:\n{request.context}"

    # Run Q&A agent. T-5.6.4: enter BYOK context so any get_llm_for call
    # inside the agent uses the user's BYOK credential when available.
    from app.agents.qa_agent import run_qa_agent
    from app.services import llm_service

    usage: dict = {}
    with llm_service.byok_context(current_user.id, db):
        answer, references = run_qa_agent(
            job_id=job.id,
            job_type=job.job_type,
            question=enriched_question,
            report_html=report_html,
            progress_callback=progress_callback,
            usage_out=usage,
        )

    # T-5.5.5: record the consumed resource AFTER the agent succeeds.
    quota_metering_service.record_usage(db, current_user.id, "qa_exchanges")

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")

    # Save original question to DB (not the enriched version).
    # Per E-5.1 phase 2a, stamp tenant_id from the authenticated user.
    qa = QAExchange(
        job_id=job.id,
        question=request.question,
        answer=answer,
        references=json.dumps([r for r in references]),
        tenant_id=current_user.id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)

    # Per-user LLM token metering. Metering failures must never break
    # the Q&A response.
    try:
        if prompt_tokens is not None:
            quota_metering_service.record_usage(
                db, current_user.id, "llm_tokens_in", prompt_tokens
            )
        if completion_tokens is not None:
            quota_metering_service.record_usage(
                db, current_user.id, "llm_tokens_out", completion_tokens
            )
    except Exception:
        logger.exception(
            f"Failed to record LLM token metering for qa_exchange id={qa.id}"
        )

    # Index into the Q&A library collection so it powers the history-chat
    # meta-RAG. Chroma failures must never break the Q&A response.
    try:
        chroma_service.upsert_qa_exchange(qa, source="job")
    except Exception:
        logger.exception(
            f"Failed to upsert job Q&A exchange id={qa.id} into Q&A library"
        )

    return qa, references


@router.post(
    "/qa",
    response_model=QAResponse,
)
def ask_question(
    job_id: str,
    request: QARequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = _load_completed_job(db, job_id, current_user)

    # T-5.5.5: enforce per-user quota BEFORE running the (expensive)
    # agent. Free / Pro tiers cap monthly Q&A counts; Studio is
    # unlimited (limit=-1 → check_quota always allows).
    quota_metering_service.enforce_quota_or_raise(
        db, current_user, "qa_exchanges"
    )

    qa, references = _run_qa_and_persist(db, job, request, current_user)

    return QAResponse(
        id=qa.id,
        question=qa.question,
        answer=qa.answer,
        references=[Reference(**r) for r in references],
        created_at=qa.created_at,
    )


@router.post("/qa/stream")
def ask_question_stream(
    job_id: str,
    request: QARequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """SSE variant of /qa: emits stage progress events while the agent runs,
    then a "complete" event carrying the exact same exchange JSON shape the
    sync endpoint returns, then a [DONE] sentinel."""
    job = _load_completed_job(db, job_id, current_user)

    # Same enforcement point as /qa: quota errors surface as a plain 429
    # before any streaming starts.
    quota_metering_service.enforce_quota_or_raise(
        db, current_user, "qa_exchanges"
    )

    async def event_stream():
        events: queue.Queue = queue.Queue()

        def progress_callback(stage: str) -> None:
            events.put({"type": "stage", "stage": stage})

        task = asyncio.create_task(
            asyncio.to_thread(
                _run_qa_and_persist, db, job, request, current_user, progress_callback
            )
        )

        while not (task.done() and events.empty()):
            try:
                event = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            yield f"data: {json.dumps(event)}\n\n"

        try:
            qa, references = task.result()
        except HTTPException as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc.detail)})}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception:
            logger.exception(f"Streaming Q&A failed for job {job.id}")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Q&A failed. Check server logs.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        payload = QAResponse(
            id=qa.id,
            question=qa.question,
            answer=qa.answer,
            references=[Reference(**r) for r in references],
            created_at=qa.created_at,
        )
        complete = {"type": "complete", "exchange": json.loads(payload.model_dump_json())}
        yield f"data: {json.dumps(complete)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/qa",
    response_model=list[QAResponse],
)
def get_qa_history(
    job_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
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

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.job import JobCreate, JobResponse, VideoApproval
from app.schemas.job_template import JobTemplateResponse, SaveAsTemplate
from app.schemas.video import VideoResponse
from app.services import (
    chroma_service,
    document_cap_service,
    job_service,
    progress_service,
    report_service,
    visibility_service,
)
from app.services import job_template_service
from app.services.tier_service import get_user_tier, quota_limit
from app.tasks.job_tasks import (
    execute_channel_job,
    execute_subscription_job,
    execute_topic_job,
    resume_job_after_approval,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(get_current_user)],
)

# What a run whose task the broker refused says on its row (T-5.2.17).
_NOT_QUEUED = "The run could not be queued, so it never started. Submit it again in a few minutes."


@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    job_data: JobCreate,
    template_id: str | None = None,
    template_version: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # E-8.6 provenance: a run started from a template records which version.
    # The body is still the full JobCreate (validated as any submission is),
    # so a stale template cannot create an invalid run.
    resolved_version: int | None = None
    if template_id is not None:
        template = job_template_service.get_template(db, template_id, current_user.id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        resolved_version = template_version or template.latest_version
        if job_template_service.get_version(db, template, resolved_version) is None:
            raise HTTPException(status_code=404, detail="Template version not found")
        if template.job_type != job_data.job_type:
            raise HTTPException(
                status_code=422,
                detail=f"This template is for {template.job_type} runs, not {job_data.job_type} runs.",
            )
    # Per-tier num_videos ceiling for topic jobs (T-5.2 tier gating).
    # The schema-level le=500 bound still applies; this narrows it to
    # the user's tier cap (free=100 / pro=250 / studio=500).
    if job_data.job_type == "topic":
        cap = quota_limit(current_user, "num_videos_cap")
        if cap != -1 and job_data.num_videos > cap:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"num_videos {job_data.num_videos} exceeds the "
                    f"{get_user_tier(current_user).value} tier cap of {cap}. "
                    f"Upgrade to raise the limit."
                ),
            )
    # T-5.2.10: a subscription job ingests without an approval step, so a
    # full library is refused here; one with room stops at the cap in the task.
    if job_data.job_type == "subscription":
        document_cap_service.refuse_if_full(db, current_user)

    try:
        # Per E-5.1 phase 2a, stamp the new row with the creating
        # user's id. Phase 2b adds query-time filtering by tenant_id.
        job = job_service.create_job(
            db,
            job_data,
            tenant_id=current_user.id,
            template_id=template_id,
            template_version=resolved_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    # T-5.6.5: route to a per-tier queue so SaaS deployment can run
    # dedicated worker pools per tier. On self-host with one worker
    # picking up all queues, this is cosmetic; on SaaS it isolates
    # heavy Free-tier workloads from Studio-tier latency budgets.
    from app.services.task_routing_service import dispatch_for_user

    task = {
        "topic": execute_topic_job,
        "subscription": execute_subscription_job,
    }.get(job_data.job_type, execute_channel_job)
    try:
        async_result = dispatch_for_user(task, current_user, job.id)
    except Exception:  # noqa: BLE001 - the broker is down: fail the row, say so
        # T-5.2.17: a row nothing will run must not stay pending, which the
        # job limit reads as active: enough of them and the user could never
        # start another job. As `_dispatch_subscription_sync` does (T-5.2.15).
        logger.exception("Failed to dispatch the %s job %s", job_data.job_type, job.id)
        job.status = "failed"
        job.error_message = _NOT_QUEUED
        job.progress_message = "Failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue the run; the task queue is unavailable. Try again in a few minutes.",
        )

    # Store task id synchronously so cancel can revoke the live task even
    # if the worker hasn't picked it up yet.
    job.celery_task_id = async_result.id
    db.commit()
    db.refresh(job)

    # S-8.10.1: `first_job_created` activation event, once per account.
    from app.services import onboarding_service

    onboarding_service.note_job_created(db, current_user, job)

    return job_service.job_to_response_dict(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # E-5.1 phase 2b: tenant-scoped read.
    jobs = job_service.get_jobs(
        db,
        status=status,
        limit=limit,
        offset=offset,
        tenant_id=current_user.id,
    )
    return [job_service.job_to_response_dict(j) for j in jobs]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.job_to_response_dict(job)


@router.put("/{job_id}/approve", response_model=JobResponse)
def approve_job(
    job_id: str,
    approval: VideoApproval,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "awaiting_approval":
        raise HTTPException(status_code=400, detail=f"Job is not awaiting approval (status: {job.status})")

    # `approved_video_ids` historically carried YouTube video IDs (e.g.
    # "U-G-mSd4KAE"). Post-S-1.5.4 page integration, the frontend sends
    # whatever string identifies the row as displayed — for video that's
    # still the YouTube video_id, for Reddit/HN it's the document_id
    # (UUID) since those rows have video_id=NULL. We accept either here
    # and match against both columns on each JobVideo row. Approval
    # state lives on the JobVideo join row, not the shared Document.
    approved_set = set(approval.approved_video_ids)

    def _is_approved(jv) -> bool:
        return (jv.video_id is not None and jv.video_id in approved_set) or (
            jv.document_id in approved_set
        )

    # T-5.2.10: the document cap, checked before anything changes. Only the
    # approved documents this tenant cannot already see count; an approval
    # that does not fit is refused whole (429) so the user picks what to drop.
    approved_document_ids = [jv.document_id for jv in job.job_videos if _is_approved(jv)]
    document_cap_service.enforce(
        db,
        current_user,
        action=document_cap_service.ACTION_APPROVE,
        document_ids=approved_document_ids,
    )

    for jv in job.job_videos:
        jv.approved = _is_approved(jv)

    # Clear the phase-1 task id so a racing cancel cannot revoke a task that
    # has already completed. The new task id is stored below after .delay().
    job.celery_task_id = None
    db.commit()

    # T-5.6.5: route resume on the same queue as the original job dispatch
    # by looking up the user via job.tenant_id. Falls back to default queue
    # for legacy NULL-tenant jobs.
    from app.services.task_routing_service import dispatch_for_tenant_id
    try:
        async_result = dispatch_for_tenant_id(
            resume_job_after_approval, db, job.tenant_id, job_id
        )
    except Exception:  # noqa: BLE001 - the broker is down: say so, in words
        # T-5.2.17: the run stays awaiting approval, with the picks kept, so
        # Approve works again once the queue is back, and Cancel frees its
        # place. Failing it would throw the candidates away. Nothing was
        # granted yet (below), so the documents hold no place under the
        # document cap either.
        logger.exception("Failed to dispatch the resume of job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue the run; the task queue is unavailable. Approve it again in a few minutes.",
        )

    # T-5.2.10: the approved documents join the library now, not when the
    # resume task starts. The cap counts visibility grants, and the resume can
    # wait behind other work on the (solo) worker for hours; until it ran, a
    # second approval, a paste or an upload was measured against a count that
    # left this approval out. The resume task re-grants the same set
    # (idempotent). After the commit, because a failed grant rolls back.
    # T-5.2.17: after the dispatch too, so a run the queue refused grants
    # nothing: its documents were never read and must not count toward the
    # cap. ``grant`` never raises (best-effort), and a grant lost here is
    # written by the resume task.
    visibility_service.grant(
        db, approved_document_ids, current_user.id, visibility_service.SOURCE_JOB
    )

    # T-5.2.20: only from awaiting_approval. The resume task is already
    # queued and may have started, or ended (a run with nothing to read fails
    # at once), and a cancel may have landed: this write never covers theirs.
    job = job_service.update_job_status(db, job_id, "extracting", progress_pct=30,
                                        progress_message="Starting transcript extraction...",
                                        only_from="awaiting_approval")
    if job is not None:
        job.celery_task_id = async_result.id
        db.commit()
        db.refresh(job)
    return job_service.job_to_response_dict(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in job_service.ENDED_STATUSES:
        raise _cannot_cancel(job.status)
    status_before = job.status

    # T-5.2.22: only while the row is still active, in one conditional UPDATE.
    # The run can complete or fail between the read above and this write; it
    # then keeps its end, and the cancel answers what it would have answered
    # a moment later.
    job, written = job_service.write_job_status(
        db, job_id, "cancelled", progress_message=_CANCELLED_WORDS, unless_ended=True
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "cancelled":
        # Lost the race: the row keeps the run's end, which is not this
        # cancel's to announce, so nothing is published (T-5.2.30).
        raise _cannot_cancel(job.status)

    # T-5.2.30: every open page of this run hears of the cancel now, not at
    # its next refetch. The write above has committed, so no page reads
    # `cancelled` before the row says it. Before the revoke, which can wait
    # on a broker that is down. T-5.2.32: only the cancel whose own write
    # made the row cancelled announces it. A second cancel that read the run
    # active and found it cancelled by the first answers 200 as before, the
    # row being cancelled, and publishes nothing.
    if written:
        _announce_cancelled(job_id, status_before)

    # Revoked only once the row says cancelled, and with the task id the row
    # holds now (an approval may have stored the resume's meanwhile). A run
    # that ended first needs no revoke: a completed or failed run's task is
    # done or closing, and terminating it there would lose the usage its scope
    # writes as it closes. The row is what stops a run (T-5.2.20): a delivered
    # task returns at once on a cancelled row, a running one stops at its next
    # check, so a revoke the broker refuses is logged, not answered as a 500
    # for a cancel that took.
    if job.celery_task_id:
        from app.tasks.celery_app import celery_app
        try:
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception as e:  # noqa: BLE001 - the broker is down; the row already stops the run
            # The type alone: a broker error can quote its URL and password.
            logger.warning("[job:%s] cancelled, but its task could not be revoked: %s", job_id, type(e).__name__)
    return job_service.job_to_response_dict(job)


_ENDED_WORDS = {"completed": "completed", "failed": "failed", "cancelled": "been cancelled"}

# What a cancelled run's row says, and what its open pages are told.
_CANCELLED_WORDS = "Job cancelled by user"


def _announce_cancelled(job_id: str, status_before: str) -> None:
    """Publish the cancel on ``job_progress:{job_id}`` as a status change, the
    event a run's own transitions send and ``useJobProgress`` applies, so every
    tab open on the run shows it cancelled at once (T-5.2.30).

    Called only once this cancel's own write has made the row ``cancelled``.
    Best effort: the row is the cancel, and a page that misses this event
    reads it at its next refetch, so a publish that fails (Redis down) is
    logged by the exception's type alone, as the revoke is, and the cancel
    still answers 200. A second cancel that raced this one answers 200 too and
    sends nothing (T-5.2.32).
    """
    try:
        progress_service.publish_status_change(job_id, status_before, "cancelled", _CANCELLED_WORDS)
    except Exception as e:  # noqa: BLE001 - the row already says cancelled
        logger.warning("[job:%s] cancelled, but the change could not be published: %s", job_id, type(e).__name__)


def _cannot_cancel(status_: str) -> HTTPException:
    """The one answer for a cancel that reaches a run already over, whether it
    ended before the route read it or between that read and the write."""
    ended = _ENDED_WORDS.get(status_, f"ended ({status_})")
    return HTTPException(status_code=400, detail=f"This run has already {ended}, so there is nothing to cancel.")


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Best-effort cleanup: DB delete must proceed even if external artifacts fail.
    try:
        chroma_service.delete_collection(job_id)
    except Exception:
        logger.exception(f"[job:{job_id}] Failed to delete ChromaDB collection")

    if job.report_path:
        try:
            report_service.delete_report(job.report_path)
        except Exception:
            logger.exception(f"[job:{job_id}] Failed to delete report file '{job.report_path}'")

    if not job_service.delete_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job not found")


@router.post(
    "/{job_id}/save-as-template",
    response_model=JobTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_job_as_template(
    job_id: str,
    body: SaveAsTemplate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Freeze this run's recipe (everything but the topic) as version 1 of a
    new template (E-8.6)."""
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    params = job_template_service.parameters_from_job(job)
    try:
        template = job_template_service.create_template(
            db, current_user.id, body.name, params, body.description
        )
    except job_template_service.TemplateNameTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a template named '{body.name}'.",
        )
    except job_template_service.InvalidParameters as exc:
        raise HTTPException(
            status_code=422, detail=f"This run cannot be saved as a template: {exc.message}"
        )
    return job_template_service.template_to_dict(db, template, current_user)


@router.get("/{job_id}/videos", response_model=list[VideoResponse])
def get_job_videos(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.job_videos_response(job)

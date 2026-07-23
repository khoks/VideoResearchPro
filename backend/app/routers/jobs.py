import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.job import JobCreate, JobResponse, VideoApproval
from app.schemas.video import VideoResponse
from app.services import chroma_service, job_service, report_service
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


@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    job_data: JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    try:
        # Per E-5.1 phase 2a, stamp the new row with the creating
        # user's id. Phase 2b adds query-time filtering by tenant_id.
        job = job_service.create_job(db, job_data, tenant_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    # T-5.6.5: route to a per-tier queue so SaaS deployment can run
    # dedicated worker pools per tier. On self-host with one worker
    # picking up all queues, this is cosmetic; on SaaS it isolates
    # heavy Free-tier workloads from Studio-tier latency budgets.
    from app.services.task_routing_service import dispatch_for_user

    if job_data.job_type == "topic":
        async_result = dispatch_for_user(execute_topic_job, current_user, job.id)
    elif job_data.job_type == "subscription":
        async_result = dispatch_for_user(
            execute_subscription_job, current_user, job.id
        )
    else:
        async_result = dispatch_for_user(execute_channel_job, current_user, job.id)

    # Store task id synchronously so cancel can revoke the live task even
    # if the worker hasn't picked it up yet.
    job.celery_task_id = async_result.id
    db.commit()
    db.refresh(job)

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
    for jv in job.job_videos:
        jv.approved = (
            (jv.video_id is not None and jv.video_id in approved_set)
            or jv.document_id in approved_set
        )

    # Clear the phase-1 task id so a racing cancel cannot revoke a task that
    # has already completed. The new task id is stored below after .delay().
    job.celery_task_id = None
    db.commit()

    # T-5.6.5: route resume on the same queue as the original job dispatch
    # by looking up the user via job.tenant_id. Falls back to default queue
    # for legacy NULL-tenant jobs.
    from app.services.task_routing_service import dispatch_for_tenant_id
    async_result = dispatch_for_tenant_id(
        resume_job_after_approval, db, job.tenant_id, job_id
    )
    job = job_service.update_job_status(db, job_id, "extracting", progress_pct=30,
                                        progress_message="Starting transcript extraction...")
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
    if job.status in ("completed", "cancelled", "failed"):
        raise HTTPException(status_code=400, detail=f"Job cannot be cancelled (status: {job.status})")

    # Revoke Celery task if running
    if job.celery_task_id:
        from app.tasks.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    job = job_service.update_job_status(db, job_id, "cancelled", progress_message="Job cancelled by user")
    return job_service.job_to_response_dict(job)


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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.job import JobCreate, JobResponse, VideoApproval
from app.schemas.video import VideoResponse
from app.services import job_service
from app.tasks.job_tasks import execute_channel_job, execute_topic_job, resume_job_after_approval

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=201)
def create_job(job_data: JobCreate, db: Session = Depends(get_db)):
    try:
        job = job_service.create_job(db, job_data)
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    # Dispatch Celery task
    if job_data.job_type == "topic":
        execute_topic_job.delay(job.id)
    else:
        execute_channel_job.delay(job.id)

    return job_service.job_to_response_dict(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    jobs = job_service.get_jobs(db, status=status, limit=limit, offset=offset)
    return [job_service.job_to_response_dict(j) for j in jobs]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_service.job_to_response_dict(job)


@router.put("/{job_id}/approve", response_model=JobResponse)
def approve_job(job_id: str, approval: VideoApproval, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "awaiting_approval":
        raise HTTPException(status_code=400, detail=f"Job is not awaiting approval (status: {job.status})")

    # Update video approval status
    approved_set = set(approval.approved_video_ids)
    for video in job.videos:
        video.approved = video.id in approved_set
    db.commit()

    # Dispatch resume task
    resume_job_after_approval.delay(job_id)
    job = job_service.update_job_status(db, job_id, "extracting", progress_pct=30,
                                        progress_message="Starting transcript extraction...")
    return job_service.job_to_response_dict(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
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
def delete_job(job_id: str, db: Session = Depends(get_db)):
    # TODO: Also delete ChromaDB collection and report file
    if not job_service.delete_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job not found")


@router.get("/{job_id}/videos", response_model=list[VideoResponse])
def get_job_videos(job_id: str, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.videos

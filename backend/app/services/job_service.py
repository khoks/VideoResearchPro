import json

from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.schemas.job import JobCreate


def create_job(db: Session, job_data: JobCreate) -> Job:
    # Check concurrent job limit
    active_count = (
        db.query(Job)
        .filter(Job.status.notin_(["completed", "cancelled", "failed"]))
        .count()
    )
    if active_count >= settings.MAX_CONCURRENT_JOBS:
        raise ValueError(f"Maximum concurrent jobs ({settings.MAX_CONCURRENT_JOBS}) reached")

    job = Job(
        job_type=job_data.job_type,
        topic=job_data.topic,
        search_instructions=job_data.search_instructions,
        num_videos=job_data.num_videos,
        min_duration_minutes=job_data.min_duration_minutes,
        max_duration_minutes=job_data.max_duration_minutes,
        channel_type_filters=json.dumps(job_data.channel_type_filters) if job_data.channel_type_filters else None,
        channel_list=json.dumps(job_data.channel_list) if job_data.channel_list else None,
        videos_per_channel=job_data.videos_per_channel,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def get_jobs(db: Session, status: str | None = None, limit: int = 50, offset: int = 0) -> list[Job]:
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    return query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()


def update_job_status(db: Session, job_id: str, status: str, progress_pct: int | None = None,
                      progress_message: str | None = None, error_message: str | None = None) -> Job | None:
    job = get_job(db, job_id)
    if not job:
        return None
    job.status = status
    if progress_pct is not None:
        job.progress_pct = progress_pct
    if progress_message is not None:
        job.progress_message = progress_message
    if error_message is not None:
        job.error_message = error_message
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job_id: str) -> bool:
    job = get_job(db, job_id)
    if not job:
        return False
    db.delete(job)
    db.commit()
    return True


def job_to_response_dict(job: Job) -> dict:
    """Convert a Job ORM object to a dict suitable for JobResponse."""
    videos = job.videos or []
    video_count = len(videos)
    transcript_count = sum(1 for v in videos if v.transcript_status == "fetched")

    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "topic": job.topic,
        "search_instructions": job.search_instructions,
        "num_videos": job.num_videos,
        "min_duration_minutes": job.min_duration_minutes,
        "max_duration_minutes": job.max_duration_minutes,
        "channel_type_filters": json.loads(job.channel_type_filters) if job.channel_type_filters else None,
        "channel_list": json.loads(job.channel_list) if job.channel_list else None,
        "videos_per_channel": job.videos_per_channel,
        "search_queries_used": json.loads(job.search_queries_used) if job.search_queries_used else None,
        "progress_pct": job.progress_pct,
        "progress_message": job.progress_message,
        "error_message": job.error_message,
        "video_count": video_count,
        "transcript_count": transcript_count,
        "has_report": job.report_path is not None,
    }


def job_videos_response(job: Job) -> list[dict]:
    """Build the video list response for a job, stitching per-job approval
    state from the JobVideo join onto the global Video rows.

    The shape matches the pre-refactor `/jobs/{id}/videos` response so existing
    API consumers keep working.
    """
    approval_by_video: dict[str, bool] = {
        jv.video_id: jv.approved for jv in (job.job_videos or [])
    }

    results: list[dict] = []
    for v in job.videos or []:
        results.append({
            # Pre-refactor shape had an internal UUID `id`; we now expose the
            # YouTube `video_id` under both names for back-compat.
            "id": v.video_id,
            "video_id": v.video_id,
            "title": v.title,
            "channel_name": v.channel_name,
            "channel_id": v.channel_id,
            "url": v.url,
            "duration_seconds": v.duration_seconds,
            "published_at": v.published_at,
            "thumbnail_url": v.thumbnail_url,
            "description": v.description,
            "approved": approval_by_video.get(v.video_id, True),
            "transcript_status": v.transcript_status,
            "transcript_word_count": v.transcript_word_count,
            "transcript_language": v.transcript_language,
            "transcript_source": v.transcript_source,
            "embedded_in_chroma": v.embedded_in_chroma,
        })
    return results

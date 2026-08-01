import json

from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.schemas.job import JobCreate


def create_job(
    db: Session, job_data: JobCreate, tenant_id: str | None = None
) -> Job:
    """Create a new Job row.

    `tenant_id` (E-5.1 phase 2a) — when set, stamps the row with the
    creating user's id. Caller (router) passes ``current_user.id``.
    Default ``None`` preserves the legacy single-tenant behaviour
    so service-layer callers that haven't updated yet keep working.
    """
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
        preferred_channels=json.dumps(job_data.preferred_channels) if job_data.preferred_channels else None,
        channel_list=json.dumps(job_data.channel_list) if job_data.channel_list else None,
        videos_per_channel=job_data.videos_per_channel,
        # R4: normalise 'auto' to NULL so the column means exactly one thing —
        # "the user expressed no preference, let the corpus bracket decide".
        output_length=(
            job_data.output_length
            if getattr(job_data, "output_length", None) not in (None, "auto")
            else None
        ),
        # R1: the request half of the visual gate. The install-wide
        # VISUAL_ENABLED setting is the other half and is checked at
        # extraction time, so a job can record the user's intent even on an
        # install where the feature is currently switched off.
        visual_analysis=bool(getattr(job_data, "visual_analysis", False)),
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(
    db: Session, job_id: str, tenant_id: str | None = None
) -> Job | None:
    """Fetch a single Job by id.

    `tenant_id` (E-5.1 phase 2b) — when set, scopes the lookup to a
    single tenant. ``None`` (back-compat default) preserves the
    legacy any-tenant behaviour for internal callers like the
    Celery worker that doesn't have a user context.
    """
    query = db.query(Job).filter(Job.id == job_id)
    if tenant_id is not None:
        query = query.filter(Job.tenant_id == tenant_id)
    return query.first()


def get_jobs(
    db: Session,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    tenant_id: str | None = None,
) -> list[Job]:
    """List Jobs with optional status + tenant filters.

    `tenant_id` (E-5.1 phase 2b) — when set, returns only jobs owned
    by that tenant. ``None`` returns jobs across all tenants
    (legacy behaviour for internal callers).
    """
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    if tenant_id is not None:
        query = query.filter(Job.tenant_id == tenant_id)
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
        "preferred_channels": json.loads(job.preferred_channels) if job.preferred_channels else None,
        "channel_list": json.loads(job.channel_list) if job.channel_list else None,
        "videos_per_channel": job.videos_per_channel,
        "search_queries_used": json.loads(job.search_queries_used) if job.search_queries_used else None,
        "channel_list_resolved": (
            json.loads(job.channel_list_resolved) if job.channel_list_resolved else None
        ),
        "progress_pct": job.progress_pct,
        "progress_message": job.progress_message,
        "error_message": job.error_message,
        "video_count": video_count,
        "transcript_count": transcript_count,
        "has_report": job.report_path is not None,
    }


def job_videos_response(job: Job) -> list[dict]:
    """Build the video list response for a job, stitching per-job approval
    state from the JobVideo join onto the global Document rows.

    Post-M-1.5 (S-1.5.4 page integration), the response includes
    polymorphic fields that drive the frontend ` <ApprovalCard>`:
    ``source_type``, ``source_id``, ``source_metadata`` (parsed JSON),
    and ``classification`` (lifted out of source_metadata if present).
    Legacy YouTube-only consumers ignore the new fields safely.
    """
    import json as _json

    approval_by_video: dict[str, bool] = {
        jv.video_id: jv.approved for jv in (job.job_videos or []) if jv.video_id
    }
    # Also key approvals by document_id so non-video rows (where
    # video_id is NULL) can still resolve their approval state.
    approval_by_document: dict[str, bool] = {
        jv.document_id: jv.approved for jv in (job.job_videos or [])
    }

    results: list[dict] = []
    for v in job.videos or []:
        # Approval state lookup — prefer document_id (canonical post-
        # E-1.10) and fall back to video_id for legacy reasons.
        approved = approval_by_document.get(
            v.document_id, approval_by_video.get(v.video_id, True)
        )

        # Parse source_metadata JSON; lift classification out into a
        # top-level field for the frontend (which renders it via the
        # <ClassificationBadgeRow> + <ApprovalCard> contract). Sibling
        # source_metadata keys (e.g. per-source enrichment like score,
        # subreddit) stay nested.
        source_metadata: dict = {}
        classification: dict | None = None
        if v.source_metadata_json:
            try:
                parsed = _json.loads(v.source_metadata_json)
                if isinstance(parsed, dict):
                    source_metadata = parsed
                    classification = parsed.get("classification")
            except _json.JSONDecodeError:
                pass

        results.append({
            # Pre-refactor shape had an internal UUID `id`; we now expose the
            # YouTube `video_id` under both names for back-compat. For non-
            # video rows, `id` falls back to document_id so the frontend
            # has a stable key for list rendering.
            "id": v.video_id or v.document_id,
            "video_id": v.video_id,
            "document_id": v.document_id,
            "source_type": v.source_type,
            "source_id": v.source_id,
            "source_url": v.source_url,
            "source_metadata": source_metadata,
            "classification": classification,
            "title": v.title,
            "channel_name": v.channel_name,
            "channel_id": v.channel_id,
            "url": v.url,
            "duration_seconds": v.duration_seconds,
            "published_at": v.published_at,
            "thumbnail_url": v.thumbnail_url,
            "description": v.description,
            "approved": approved,
            "transcript_status": v.transcript_status,
            "transcript_word_count": v.transcript_word_count,
            "transcript_language": v.transcript_language,
            "transcript_source": v.transcript_source,
            "embedded_in_chroma": v.embedded_in_chroma,
        })
    return results

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.channel import Channel
from app.models.job import Job
from app.models.document import Document
from app.schemas.channel import ChannelResponse, SubscribeResponse
from app.schemas.video import VideoResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/channels",
    tags=["channels"],
    dependencies=[Depends(get_current_user)],
)


def _video_count_for_channel(db: Session, channel_id: str) -> int:
    return (
        db.query(func.count(Document.video_id))
        .filter(Document.channel_id == channel_id)
        .scalar()
        or 0
    )


def _channel_to_response(db: Session, channel: Channel) -> dict:
    return {
        "channel_id": channel.channel_id,
        "name": channel.name,
        "subscribed": channel.subscribed,
        "subscriber_count": channel.subscriber_count,
        "uploads_playlist_id": channel.uploads_playlist_id,
        "last_synced_at": channel.last_synced_at,
        "video_count": _video_count_for_channel(db, channel.channel_id),
    }


@router.get("", response_model=list[ChannelResponse])
def list_channels(db: Session = Depends(get_db)):
    channels = db.query(Channel).order_by(Channel.name.asc()).all()
    return [_channel_to_response(db, ch) for ch in channels]


@router.get("/{channel_id}", response_model=ChannelResponse)
def get_channel(channel_id: str, db: Session = Depends(get_db)):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _channel_to_response(db, channel)


@router.post("/{channel_id}/subscribe", response_model=SubscribeResponse)
def subscribe_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.subscribed = True
    db.commit()
    db.refresh(channel)

    job_id = _dispatch_subscription_sync(db, channel, tenant_id=current_user.id)
    return SubscribeResponse(channel_id=channel.channel_id, job_id=job_id)


@router.post("/{channel_id}/unsubscribe", response_model=ChannelResponse)
def unsubscribe_channel(channel_id: str, db: Session = Depends(get_db)):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.subscribed = False
    db.commit()
    db.refresh(channel)
    return _channel_to_response(db, channel)


@router.post("/{channel_id}/sync", response_model=SubscribeResponse)
def sync_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    job_id = _dispatch_subscription_sync(db, channel, tenant_id=current_user.id)
    return SubscribeResponse(channel_id=channel.channel_id, job_id=job_id)


@router.get("/{channel_id}/videos", response_model=list[VideoResponse])
def list_channel_videos(
    channel_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    videos = (
        db.query(Document)
        .filter(Document.channel_id == channel_id)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    # VideoResponse requires both `id` and `video_id`; stitch the former from
    # the primary key so the response shape matches other endpoints.
    return [
        {
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
            "approved": True,
            "transcript_status": v.transcript_status,
            "transcript_word_count": v.transcript_word_count,
            "transcript_language": v.transcript_language,
            "transcript_source": v.transcript_source,
            "embedded_in_chroma": v.embedded_in_chroma,
        }
        for v in videos
    ]


def _dispatch_subscription_sync(
    db: Session, channel: Channel, tenant_id: str | None = None
) -> str | None:
    """Create a single-channel subscription Job and dispatch ``execute_subscription_job``.

    Returns the new job_id, or ``None`` when dispatch fails. Dispatch is
    best-effort — a failure to reach the Celery broker must not wedge the
    subscribe/sync endpoints.

    `tenant_id` (E-5.1 phase 2a) — caller threads `current_user.id`
    through; default ``None`` preserves back-compat for any internal
    caller that hasn't been updated yet.
    """
    # Lazy import so a missing Celery broker doesn't break module import.
    from app.tasks.job_tasks import execute_subscription_job

    job = Job(
        job_type="subscription",
        status="pending",
        topic=f"Sync {channel.name}" if channel.name else f"Sync {channel.channel_id}",
        channel_list=json.dumps([channel.channel_id]),
        num_videos=0,
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        async_result = execute_subscription_job.delay(job.id)
        job.celery_task_id = async_result.id
        db.commit()
        db.refresh(job)
    except Exception:
        logger.exception(
            f"Failed to dispatch subscription sync task for channel {channel.channel_id}"
        )
        return job.id

    return job.id

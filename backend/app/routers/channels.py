import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.channel import Channel
from app.models.job import Job
from app.models.document import Document
from app.schemas.channel import ChannelResponse, ChannelWeightRequest, SubscribeResponse
from app.schemas.channel_intelligence import ChannelIntelligenceResponse
from app.services import (
    channel_intelligence_service,
    document_cap_service,
    job_service,
    subscription_service,
    visibility_service,
)

logger = logging.getLogger(__name__)

# Why no sync started, for the reader. Subscribing has already happened by the
# time either of the first two is said, and "Sync now" is the way to start it.
_FIRST_SYNC_WAITS = (
    "You are subscribed to {name}, but the first sync has not started. {why} "
    "Then use Sync now to start it."
)
_FIRST_SYNC_NOT_QUEUED = (
    "You are subscribed to {name}, but the first sync could not be queued. Use Sync now to start it."
)
_SYNC_NOT_QUEUED = "The sync could not be queued. Try Sync now again in a moment."

router = APIRouter(
    prefix="/channels",
    tags=["channels"],
    dependencies=[Depends(get_current_user)],
)


def _video_count_for_channel(db: Session, channel_id: str, tenant_id: str) -> int:
    """Count only documents THIS tenant can see (D-063/D-065) — a global count
    would leak how much other users have ingested from the channel."""
    return (
        db.query(func.count(Document.document_id))
        .filter(
            Document.channel_id == channel_id,
            Document.document_id.in_(
                visibility_service.visible_document_ids(db, tenant_id)
            ),
        )
        .scalar()
        or 0
    )


def _channel_url(channel: Channel) -> str | None:
    """Public page for the creator. Only YouTube channels have a derivable
    URL today; other creator types (E-1.9 phase 2) return None until their
    metadata carries one."""
    if channel.source_type == "video" and channel.channel_id:
        return f"https://www.youtube.com/channel/{channel.channel_id}"
    return None


def _channel_to_response(db: Session, channel: Channel, tenant_id: str) -> dict:
    """Shared channel facts + THIS tenant's subscription state (D-065).

    `source_weight` is the caller's own per-tenant trust weight. It is exposed
    read-only so the channel page (S-8.7.1) can show it; the write path and
    the retrieval re-rank are S-7.1.1 / D-068.
    """
    sub = subscription_service.get_or_create(db, channel.channel_id, tenant_id)
    return {
        "id": channel.channel_id,
        "channel_id": channel.channel_id,
        "name": channel.name,
        "url": _channel_url(channel),
        "subscribed": sub.subscribed,
        "source_weight": sub.source_weight,
        "subscriber_count": channel.subscriber_count,
        "uploads_playlist_id": channel.uploads_playlist_id,
        "last_synced_at": sub.last_synced_at,
        "created_at": channel.created_at,
        "video_count": _video_count_for_channel(db, channel.channel_id, tenant_id),
    }


@router.get("", response_model=list[ChannelResponse])
def list_channels(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Channels this tenant can see: ones they hold subscription state for, or
    that produced a document visible to them (D-065)."""
    channels = (
        db.query(Channel)
        .filter(
            Channel.channel_id.in_(
                subscription_service.visible_channel_ids(db, current_user.id)
            )
        )
        .order_by(Channel.name.asc())
        .all()
    )
    return [_channel_to_response(db, ch, current_user.id) for ch in channels]


@router.get("/{channel_id}", response_model=ChannelResponse)
def get_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _channel_to_response(db, channel, current_user.id)


@router.post("/{channel_id}/subscribe", response_model=SubscribeResponse)
def subscribe_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    # T-5.2.10: subscribing starts a sync; a full library is refused before
    # anything changes (429). A library with room stops at the cap in the task.
    document_cap_service.refuse_if_full(db, current_user)

    subscription_service.set_subscribed(db, channel.channel_id, current_user.id, True)

    # T-5.2.15: subscribing is not a job, so the limit never refuses it. It
    # only keeps the first sync from starting, and the response says so.
    name = channel.name or "this channel"
    try:
        job_service.refuse_if_at_limit(db, current_user.id)
    except ValueError as refused:
        return SubscribeResponse(
            channel_id=channel.channel_id,
            sync_note=_FIRST_SYNC_WAITS.format(name=name, why=refused),
        )

    job_id = _dispatch_subscription_sync(db, channel, tenant_id=current_user.id)
    return SubscribeResponse(
        channel_id=channel.channel_id,
        job_id=job_id,
        sync_note=None if job_id else _FIRST_SYNC_NOT_QUEUED.format(name=name),
    )


@router.post("/{channel_id}/unsubscribe", response_model=ChannelResponse)
def unsubscribe_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Only THIS tenant unsubscribes — other subscribers are unaffected.
    subscription_service.set_subscribed(db, channel.channel_id, current_user.id, False)
    return _channel_to_response(db, channel, current_user.id)


@router.put("/{channel_id}/weight", response_model=ChannelResponse)
def set_channel_weight(
    channel_id: str,
    body: ChannelWeightRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Set THIS tenant's trust weight for the channel (S-7.1.1 / D-068).

    Only the caller's `channel_subscriptions` row changes; another tenant's
    weight, and therefore their ranking, is untouched (D-065). The weight
    re-ranks the caller's job and library Q&A retrieval and is never a
    filter: 0.0 sinks a channel, it does not remove it.
    """
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    subscription_service.set_weight(db, channel.channel_id, current_user.id, body.weight)
    return _channel_to_response(db, channel, current_user.id)


@router.post("/{channel_id}/sync", response_model=SubscribeResponse)
def sync_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    document_cap_service.refuse_if_full(db, current_user)  # T-5.2.10
    try:
        job_service.refuse_if_at_limit(db, current_user.id)  # T-5.2.15
    except ValueError as refused:
        raise HTTPException(status_code=429, detail=str(refused))

    job_id = _dispatch_subscription_sync(db, channel, tenant_id=current_user.id)
    return SubscribeResponse(
        channel_id=channel.channel_id,
        job_id=job_id,
        sync_note=None if job_id else _SYNC_NOT_QUEUED,
    )


@router.get("/{channel_id}/intelligence", response_model=ChannelIntelligenceResponse)
def get_channel_intelligence(
    channel_id: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """What the channel says, over the documents of it this reader can see
    (S-8.7.2, D-063). Cached per (channel, tenant) and recomputed when the
    visible documents, their knowledge or their transcripts change;
    ``refresh=true`` forces it. The Q&A part is always live."""
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel_intelligence_service.get_intelligence(
        db, current_user.id, channel, refresh=refresh
    )


def _dispatch_subscription_sync(
    db: Session, channel: Channel, tenant_id: str | None = None
) -> str | None:
    """Create a single-channel subscription Job and dispatch ``execute_subscription_job``.

    Returns the new job_id, or ``None`` when dispatch fails. Dispatch is
    best-effort — a failure to reach the Celery broker must not wedge the
    subscribe/sync endpoints. A row nothing will run is failed on the way
    out: left pending it would hold one of its owner's places for good.

    The per-user job limit is the caller's to check (T-5.2.15): at the limit
    ``sync_channel`` refuses and ``subscribe_channel`` subscribes without a
    sync. Nothing else calls this.

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
        # T-5.6.5: per-tier queue routing — resolve the tier via tenant_id
        # since the helper doesn't have a User row in scope (it accepts a
        # tenant_id arg from its caller for back-compat).
        from app.services.task_routing_service import dispatch_for_tenant_id
        async_result = dispatch_for_tenant_id(
            execute_subscription_job, db, tenant_id, job.id
        )
    except Exception:
        logger.exception(
            f"Failed to dispatch subscription sync task for channel {channel.channel_id}"
        )
        job.status = "failed"
        job.error_message = "The sync could not be queued."
        db.commit()
        return None

    job.celery_task_id = async_result.id
    db.commit()
    return job.id

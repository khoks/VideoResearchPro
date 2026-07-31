"""Per-tenant channel subscription state — D-065.

Mirrors `visibility_service` for documents: the channel record is shared, the
subscription state is private. Every read of subscription state must go
through here so a new surface cannot accidentally read the legacy global
columns on `channels`.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.channel_subscription import ChannelSubscription
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility

logger = logging.getLogger(__name__)


def get_or_create(db: Session, channel_id: str, tenant_id: str) -> ChannelSubscription:
    """Fetch this tenant's subscription row, creating a neutral one if absent.

    Creating on read keeps callers simple: a tenant who has never touched a
    channel still has well-defined (unsubscribed, weight 1.0) state.
    """
    row = (
        db.query(ChannelSubscription)
        .filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.tenant_id == tenant_id,
        )
        .first()
    )
    if row is None:
        row = ChannelSubscription(channel_id=channel_id, tenant_id=tenant_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def set_subscribed(
    db: Session, channel_id: str, tenant_id: str, subscribed: bool
) -> ChannelSubscription:
    row = get_or_create(db, channel_id, tenant_id)
    row.subscribed = subscribed
    db.commit()
    db.refresh(row)
    return row


def mark_synced(db: Session, channel_id: str, tenant_id: str) -> None:
    row = get_or_create(db, channel_id, tenant_id)
    row.last_synced_at = datetime.utcnow()
    db.commit()


def visible_channel_ids(db: Session, tenant_id: str):
    """Channels this tenant may see: any they hold a subscription row for, OR
    any that produced a document visible to them.

    Returned as a query so callers compose it into an ``IN`` clause.
    """
    from sqlalchemy import union

    subscribed = db.query(ChannelSubscription.channel_id).filter(
        ChannelSubscription.tenant_id == tenant_id
    )
    from_docs = (
        db.query(Document.channel_id)
        .join(DocumentVisibility, DocumentVisibility.video_id == Document.video_id)
        .filter(
            DocumentVisibility.tenant_id == tenant_id,
            Document.channel_id.isnot(None),
        )
    )
    return union(subscribed, from_docs)


def subscribed_channel_ids(db: Session, tenant_id: str) -> list[str]:
    """Channel ids this tenant actively subscribes to (for sync fan-out)."""
    return [
        r[0]
        for r in db.query(ChannelSubscription.channel_id).filter(
            ChannelSubscription.tenant_id == tenant_id,
            ChannelSubscription.subscribed.is_(True),
        )
    ]

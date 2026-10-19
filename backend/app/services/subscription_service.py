"""Per-tenant channel subscription state — D-065.

Mirrors `visibility_service` for documents: the channel record is shared, the
subscription state is private. Every read of subscription state must go
through here so a new surface cannot accidentally read the legacy global
columns on `channels`.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.channel_subscription import ChannelSubscription
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility

logger = logging.getLogger(__name__)

# D-068: the user-settable range. 1.0 is neutral. 0.0 is allowed as input and
# clamped to a floor at query time (`qa_agent.MIN_TRUST_WEIGHT`), so a
# distrusted source sinks to the bottom but can still surface when nothing
# else matches — a weight is a preference, never a filter.
MIN_SOURCE_WEIGHT = 0.0
MAX_SOURCE_WEIGHT = 2.0
NEUTRAL_SOURCE_WEIGHT = 1.0


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


def set_weight(
    db: Session, channel_id: str, tenant_id: str, weight: float
) -> ChannelSubscription:
    """Set THIS tenant's trust weight for a channel (D-068). Raises
    ``ValueError`` outside ``[MIN_SOURCE_WEIGHT, MAX_SOURCE_WEIGHT]``."""
    try:
        value = float(weight)
    except (TypeError, ValueError) as e:
        raise ValueError(f"weight must be a number, got {weight!r}") from e
    if math.isnan(value) or not (MIN_SOURCE_WEIGHT <= value <= MAX_SOURCE_WEIGHT):
        raise ValueError(
            f"weight must be between {MIN_SOURCE_WEIGHT} and {MAX_SOURCE_WEIGHT}, got {value}"
        )
    row = get_or_create(db, channel_id, tenant_id)
    row.source_weight = value
    db.commit()
    db.refresh(row)
    logger.info(
        "subscription: tenant %s set weight %.2f on channel %s",
        tenant_id[:8], value, channel_id,
    )
    return row


def channel_weights(db: Session, tenant_id: str) -> dict[str, float]:
    """THIS tenant's non-neutral trust weights, ``{channel_id: weight}``.

    Resolved at query time by the Q&A routers and handed to the agent
    (D-068): chunks are shared across tenants (D-063), so a per-tenant
    number can never live in chunk metadata. Neutral rows are left out, so
    an empty dict means "no weighting" and retrieval runs exactly as it did
    before weights existed.
    """
    return {
        channel_id: float(weight)
        for channel_id, weight in db.query(
            ChannelSubscription.channel_id, ChannelSubscription.source_weight
        ).filter(
            ChannelSubscription.tenant_id == tenant_id,
            ChannelSubscription.source_weight != NEUTRAL_SOURCE_WEIGHT,
        )
    }


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
        .join(DocumentVisibility, DocumentVisibility.document_id == Document.document_id)
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

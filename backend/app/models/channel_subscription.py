"""Per-tenant subscription state over the shared channel catalogue — D-065.

Mirrors `document_visibility` (D-063): the *record* is shared, the *state* is
private. A channel's identity and public facts (name, subscriber count,
uploads playlist) are the same for everyone and stay deduplicated on
`channels`. What is per-user moves here:

* ``subscribed``    — whether THIS tenant follows the channel
* ``source_weight`` — the trust score that re-ranks retrieval. This was always
  per-user by intent ("user-set trust score" in the Channel docstring) and was
  simply stored globally, so one user's re-weighting silently altered
  everyone's ranking. Since S-7.1.1 (D-068) it is true: set through
  ``PUT /channels/{id}/weight`` (0.0–2.0, 1.0 neutral), resolved per tenant by
  ``subscription_service.channel_weights`` when a job or library question is
  asked, and applied by ``qa_agent`` as ``distance / weight`` over a 3× pool
  AFTER the raw relevance threshold — so it reorders relevant passages and
  can never pull in an off-topic one. Never stored on chunks, never a filter;
  0.0 is clamped to 0.05 so a distrusted source can still surface when
  nothing else matches.
* ``last_synced_at`` — sync progress is per-subscription, since two tenants
  subscribing at different times must not skip each other's backlog.

Keeping the catalogue shared preserves the point of the design: two users
following the same channel resolve its uploads playlist once.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChannelSubscription(Base):
    __tablename__ = "channel_subscriptions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    channel_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("channels.channel_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    subscribed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 1.0 is neutral; higher promotes, lower demotes (D-068 re-rank). Per tenant.
    source_weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "tenant_id", name="uq_channel_subscription"),
        Index("ix_channel_subscriptions_tenant_channel", "tenant_id", "channel_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        mark = "+" if self.subscribed else "-"
        return f"<ChannelSubscription {mark}{self.channel_id} -> {self.tenant_id[:8]}>"

"""Newsletter subscriptions and their sends (S-6.4.2 / E-6.4).

One subscription per reader (``tenant_id`` unique): the cadence it follows
(the scheduler's canonical cadence JSON, D-077), which sections an issue has,
and where the last issue ended. The scheduler row for it is kind
``newsletter`` with ``target_id`` = the subscription id.

``newsletter_sends`` is the idempotency ledger: one row per
``(subscription_id, period_key)``, inserted BEFORE an issue is generated, so
a second dispatch for the same period (a retried tick, two workers) finds
the row and does nothing. It also records how each period ended.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NewsletterSubscription(Base):
    __tablename__ = "newsletter_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Your library digest")
    cadence_json: Mapped[str] = mapped_column(Text, nullable=False)
    sections_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Where the last issue's window ended; the next issue starts here.
    last_issue_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


class NewsletterSend(Base):
    __tablename__ = "newsletter_sends"
    __table_args__ = (UniqueConstraint("subscription_id", "period_key", name="uq_newsletter_sends_period"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("newsletter_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # started | sent | email_failed | skipped | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started")
    output_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

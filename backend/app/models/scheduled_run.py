"""scheduled_runs — the one table the scheduler tick reads (S-8.3.1 / M3).

Nothing in the app ran on a schedule before this. Saved searches (E-8.3),
the newsletter (E-6.4) and Echo connector syncs (S-3.2.1) all need "do X
for tenant T at cadence C", so the schedule lives here, in SQLite, inside
the same backup as everything else, rather than in a Redis-backed beat
store (see the M3 plan's rejected alternatives).

One row per ``(kind, target_id)``: ``kind`` names a registered dispatcher
(``scheduler_service.register_kind``), ``target_id`` is whatever that kind
needs to find its work (a ``saved_searches.id``, a subscription id, …). The
tick never interprets ``target_id``; it hands it to the kind's Celery task.

``cadence_json`` is a human cadence, never a cron string::

    {"cadence": "daily",   "hour": 9,  "minute": 0, "timezone": "Asia/Kolkata"}
    {"cadence": "weekly",  "hour": 9,  "minute": 0, "weekday": 0, "timezone": "UTC"}
    {"cadence": "monthly", "hour": 6,  "minute": 30, "day_of_month": 1, "timezone": "UTC"}
    {"cadence": "every",   "seconds": 3600}

``next_run_at`` is always UTC and naive (SQLite's DateTime drops tzinfo, so
the service keeps every datetime naive-UTC to make comparisons safe).
``claimed_at`` is the short lease the tick takes before dispatching, so two
ticks (or two beats, if an operator misconfigures) never dispatch the same
row twice; a claim older than ``SCHEDULER_LEASE_SECONDS`` is stale and may be
taken again (the holder crashed between claim and advance).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ScheduledRun(Base):
    __tablename__ = "scheduled_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # NULL for system kinds with no owner; otherwise the user whose tier
    # queue the dispatch goes to (task_routing_service.dispatch_for_tenant_id).
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)

    cadence_json: Mapped[str] = mapped_column(Text, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # dispatched | dispatch_failed | no_handler | bad_cadence
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Reset to 0 on a successful dispatch. Bounds the "retry next tick"
    # path so a broker that stays down does not pin a row to every tick.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow_naive, onupdate=_utcnow_naive, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("kind", "target_id", name="uq_scheduled_runs_kind_target"),
        # The tick's hot query: enabled rows ordered by due time.
        Index("ix_scheduled_runs_due", "enabled", "next_run_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        flag = "" if self.enabled else " (disabled)"
        return f"<ScheduledRun {self.kind}:{self.target_id} next={self.next_run_at}{flag}>"

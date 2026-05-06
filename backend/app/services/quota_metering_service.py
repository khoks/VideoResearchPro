"""Quota metering — T-5.5.5 / T-5.2.5.

Per-user, per-resource consumption tracking + enforcement against
per-tier limits. Sits next to the existing ``quota_service.py``
(which tracks process-wide YouTube units globally) but with a
different shape: this service is **per-user** and reads tier limits
from ``tier_service.TIER_CAPABILITIES``.

Resource keys (must match the tier capability table):

- ``qa_exchanges`` — count, monthly. Job-scoped Q&A.
- ``library_qa_exchanges`` — count, monthly.
- ``qa_history_chats`` — count, monthly.
- ``knowledge_extractions`` — count, monthly.
- ``documents`` — count, lifetime (period_kind=``lifetime`` so the cap
  applies to the user's library size, not "per month").
- ``llm_tokens_in`` / ``llm_tokens_out`` — count, daily. Sum tracked
  via instrumented LLM client.
- ``youtube_units`` — count, daily. Already tracked process-wide in
  ``api_quota_log``; the per-user attribution is the new piece.

For each resource, the tier capability table holds a hard cap. The
service exposes:

- ``record_usage(db, user_id, resource, amount=1)`` — increment the
  current period's counter. Failures logged but never raised.
- ``get_usage(db, user_id, resource)`` — current period's consumed
  count.
- ``get_all_usage(db, user_id)`` — list of ``(resource, consumed,
  limit, period_start, period_end)`` for every tracked resource.
- ``check_quota(db, user_id, resource, increment=1) -> (ok, retry_at)``
  — does the increment fit? Returns the next-period start when not.
- ``enforce_quota_or_raise(db, user_id, resource, increment=1)`` —
  raises ``QuotaExceededError`` (HTTP 429) when over limit.

This module is stateless beyond the DB table — multi-worker SaaS
deployments can use it as-is. The ``api_quota_log`` Redis mirror is
for global YouTube quota; per-user is in this table.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.quota_usage import QuotaUsage
from app.models.user import User
from app.services.tier_service import (
    capabilities_for,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resource registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Resource:
    name: str
    period_kind: str  # "daily" | "monthly" | "lifetime"
    tier_limit_key: str  # which TIER_CAPABILITIES key holds the cap


# Map of resource → (period_kind, tier_limit_key). The tier_limit_key
# refers to a key in ``TIER_CAPABILITIES[tier]``; if a resource doesn't
# have a corresponding key (e.g. ``qa_exchanges`` isn't in the v1 cap
# table), the limit is treated as unlimited (-1).
_RESOURCES: dict[str, _Resource] = {
    "qa_exchanges": _Resource(
        "qa_exchanges", "monthly", "qa_exchanges_per_month"
    ),
    "library_qa_exchanges": _Resource(
        "library_qa_exchanges", "monthly", "qa_exchanges_per_month"
    ),
    "qa_history_chats": _Resource(
        "qa_history_chats", "monthly", "qa_exchanges_per_month"
    ),
    "knowledge_extractions": _Resource(
        "knowledge_extractions", "monthly", "knowledge_extractions_per_month"
    ),
    "documents": _Resource(
        "documents", "lifetime", "document_count_cap"
    ),
    "llm_tokens_in": _Resource(
        "llm_tokens_in", "daily", "llm_tokens_per_day"
    ),
    "llm_tokens_out": _Resource(
        "llm_tokens_out", "daily", "llm_tokens_per_day"
    ),
    "youtube_units": _Resource(
        "youtube_units", "daily", "youtube_units_per_day"
    ),
}


def supported_resources() -> list[str]:
    return sorted(_RESOURCES.keys())


# ---------------------------------------------------------------------------
# Period boundaries
# ---------------------------------------------------------------------------


def _period_start(now: datetime, kind: str) -> datetime:
    """Floor ``now`` to the start of the period."""
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if kind == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if kind == "lifetime":
        # Single epoch-zero bucket — every event lands in the same row.
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    raise ValueError(f"Unknown period_kind: {kind}")


def _next_period_start(period_start: datetime, kind: str) -> datetime | None:
    if kind == "daily":
        return period_start + timedelta(days=1)
    if kind == "monthly":
        # Add one calendar month — robust against month-length differences.
        if period_start.month == 12:
            return period_start.replace(year=period_start.year + 1, month=1)
        return period_start.replace(month=period_start.month + 1)
    if kind == "lifetime":
        return None
    raise ValueError(f"Unknown period_kind: {kind}")


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


class QuotaExceededError(HTTPException):
    """HTTP 429 raised when the user's quota for a resource is exhausted.

    The detail body carries enough context for clients to surface a
    sensible message: the resource name, the current usage, the cap,
    and the time at which the period rolls over.
    """

    def __init__(
        self,
        resource: str,
        consumed: int,
        limit: int,
        retry_at: datetime | None,
    ) -> None:
        retry_after_sec: int | None = None
        if retry_at is not None:
            now = datetime.now(timezone.utc)
            retry_after_sec = max(1, int((retry_at - now).total_seconds()))
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "resource": resource,
                "consumed": consumed,
                "limit": limit,
                "retry_after_sec": retry_after_sec,
                "retry_at": retry_at.isoformat() if retry_at else None,
            },
        )
        self.headers = (
            {"Retry-After": str(retry_after_sec)}
            if retry_after_sec is not None
            else None
        )


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def _resolve_resource(resource: str) -> _Resource:
    r = _RESOURCES.get(resource)
    if r is None:
        raise ValueError(
            f"Unknown quota resource '{resource}'. "
            f"Add it to _RESOURCES first."
        )
    return r


def _resolve_limit(user: User, resource: str) -> int:
    """Return the tier's cap for ``resource``, or -1 if uncapped /
    not in the tier table."""
    res = _resolve_resource(resource)
    cap = capabilities_for(user)
    return int(cap.get(res.tier_limit_key, -1))


def _row_for(
    db: Session, user_id: str, res: _Resource, *, now: datetime | None = None
) -> QuotaUsage:
    """Find or create the QuotaUsage row for the current period."""
    now = now or datetime.now(timezone.utc)
    period_start = _period_start(now, res.period_kind)
    row = (
        db.query(QuotaUsage)
        .filter(
            QuotaUsage.user_id == user_id,
            QuotaUsage.resource == res.name,
            QuotaUsage.period_kind == res.period_kind,
            QuotaUsage.period_start == period_start,
        )
        .first()
    )
    if row is None:
        row = QuotaUsage(
            user_id=user_id,
            resource=res.name,
            period_kind=res.period_kind,
            period_start=period_start,
            consumed=0,
        )
        db.add(row)
        db.flush()
    return row


def record_usage(
    db: Session, user_id: str, resource: str, amount: int = 1
) -> int:
    """Increment the user's current-period consumption of ``resource``
    by ``amount``. Returns the new total.

    Failures are logged but never raised — quota tracking must not
    break the call site it's instrumenting.
    """
    if amount <= 0:
        return 0
    try:
        res = _resolve_resource(resource)
        row = _row_for(db, user_id, res)
        row.consumed = (row.consumed or 0) + amount
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return row.consumed
    except Exception:
        logger.exception(
            "quota_metering: record_usage failed user=%s resource=%s amount=%s",
            user_id,
            resource,
            amount,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def get_usage(db: Session, user_id: str, resource: str) -> int:
    """Return the user's current-period consumption of ``resource``.
    Returns 0 if no row exists yet."""
    res = _resolve_resource(resource)
    now = datetime.now(timezone.utc)
    period_start = _period_start(now, res.period_kind)
    row = (
        db.query(QuotaUsage)
        .filter(
            QuotaUsage.user_id == user_id,
            QuotaUsage.resource == res.name,
            QuotaUsage.period_kind == res.period_kind,
            QuotaUsage.period_start == period_start,
        )
        .first()
    )
    return row.consumed if row else 0


@dataclass(frozen=True)
class UsageSnapshot:
    resource: str
    period_kind: str
    period_start: datetime
    period_end: datetime | None
    consumed: int
    limit: int  # -1 = unlimited
    over_limit: bool


def get_all_usage(db: Session, user: User) -> list[UsageSnapshot]:
    """Return a snapshot of every tracked resource for ``user``."""
    now = datetime.now(timezone.utc)
    out: list[UsageSnapshot] = []
    for res in _RESOURCES.values():
        consumed = get_usage(db, user.id, res.name)
        limit = _resolve_limit(user, res.name)
        period_start = _period_start(now, res.period_kind)
        period_end = _next_period_start(period_start, res.period_kind)
        over = limit != -1 and consumed >= limit
        out.append(
            UsageSnapshot(
                resource=res.name,
                period_kind=res.period_kind,
                period_start=period_start,
                period_end=period_end,
                consumed=consumed,
                limit=limit,
                over_limit=over,
            )
        )
    return out


def check_quota(
    db: Session, user: User, resource: str, increment: int = 1
) -> tuple[bool, datetime | None]:
    """True iff the increment fits in the user's remaining quota.

    Returns ``(ok, retry_at)``: when ``ok=False``, ``retry_at`` is the
    UTC datetime at which the next period starts (or ``None`` for
    lifetime-period resources, where retry-after is undefined).
    """
    res = _resolve_resource(resource)
    limit = _resolve_limit(user, resource)
    if limit == -1:  # unlimited
        return True, None
    consumed = get_usage(db, user.id, resource)
    if consumed + increment <= limit:
        return True, None
    period_start = _period_start(datetime.now(timezone.utc), res.period_kind)
    return False, _next_period_start(period_start, res.period_kind)


def enforce_quota_or_raise(
    db: Session, user: User, resource: str, increment: int = 1
) -> None:
    """Raise ``QuotaExceededError`` (HTTP 429) if the increment would
    exceed the cap. Use at the entry of a quota-bearing endpoint
    BEFORE doing the work."""
    ok, retry_at = check_quota(db, user, resource, increment)
    if ok:
        return
    consumed = get_usage(db, user.id, resource)
    limit = _resolve_limit(user, resource)
    raise QuotaExceededError(
        resource=resource,
        consumed=consumed,
        limit=limit,
        retry_at=retry_at,
    )

"""Subscription tier gating (E-5.2).

Three-tier model: ``free`` / ``pro`` / ``studio``. Self-host installs
default everyone to ``free`` and the operator may upgrade users
manually (`UPDATE users SET tier = 'pro' WHERE id = '...'`). SaaS
deployment will populate this column from the billing service.

This module owns three things:

1. The ``Tier`` enum + ordering rules.
2. The ``TIER_CAPABILITIES`` table: per-tier feature set + quotas.
3. ``require_tier(min_tier)`` — a FastAPI dependency factory that
   raises 403 when ``current_user.tier < min_tier``.

Quota *enforcement* (e.g. "you've consumed 9,500 of your 10,000 daily
YouTube units") is layered on top via the existing
``app/services/quota_service.py``; this module owns the **limits**,
not the runtime accounting.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException, status

from app.dependencies import get_current_user
from app.models.user import User


class Tier(str, Enum):
    """Subscription tier, ordered ``FREE < PRO < STUDIO``."""

    FREE = "free"
    PRO = "pro"
    STUDIO = "studio"

    @property
    def rank(self) -> int:
        return _TIER_RANK[self]

    def at_least(self, other: "Tier") -> bool:
        """True iff this tier is >= ``other``."""
        return self.rank >= other.rank


_TIER_RANK: dict[Tier, int] = {
    Tier.FREE: 0,
    Tier.PRO: 1,
    Tier.STUDIO: 2,
}


# The capability table. Quotas are conservative SaaS-launch defaults;
# self-host operators can override at the application layer if their
# workload demands it (the table is consulted, not enforced at the
# infra level).
#
# - youtube_units_per_day: YouTube Data API v3 quota (1 unit = 1 metadata
#   call; 100 = 1 search call).
# - llm_tokens_per_day: cumulative tokens across all use cases.
# - document_count_cap: max rows in the global library attributable to
#   this user. -1 = unlimited.
# - features: opt-in feature names. Endpoints check via
#   ``require_feature("author_studio")`` (sugar over ``require_tier``).
TIER_CAPABILITIES: dict[Tier, dict] = {
    Tier.FREE: {
        "youtube_units_per_day": 10_000,
        "llm_tokens_per_day": 200_000,
        "document_count_cap": 500,
        # T-5.5.5 quota-metered resources (monthly counts).
        "qa_exchanges_per_month": 50,
        "knowledge_extractions_per_month": 10,
        "features": frozenset(
            {
                "topic_jobs",
                "channel_jobs",
                "subscription_jobs",
                "library_qa",
                "qa_history_chat",
                "knowledge_extract",
            }
        ),
    },
    Tier.PRO: {
        "youtube_units_per_day": 50_000,
        "llm_tokens_per_day": 2_000_000,
        "document_count_cap": 5_000,
        "qa_exchanges_per_month": 1_000,
        "knowledge_extractions_per_month": 200,
        "features": frozenset(
            {
                "topic_jobs",
                "channel_jobs",
                "subscription_jobs",
                "library_qa",
                "qa_history_chat",
                "knowledge_extract",
                "author_studio",
                "shelves",
                "saved_searches",
                "public_report_sharing",
            }
        ),
    },
    Tier.STUDIO: {
        "youtube_units_per_day": 250_000,
        "llm_tokens_per_day": 10_000_000,
        "document_count_cap": -1,  # unlimited
        "qa_exchanges_per_month": -1,
        "knowledge_extractions_per_month": 2_000,
        "features": frozenset(
            {
                "topic_jobs",
                "channel_jobs",
                "subscription_jobs",
                "library_qa",
                "qa_history_chat",
                "knowledge_extract",
                "author_studio",
                "shelves",
                "saved_searches",
                "public_report_sharing",
                "byok_llm_keys",
                "team_workspace",
                "data_residency_choice",
            }
        ),
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_user_tier(user: User) -> Tier:
    """Resolve a User row to a ``Tier``, defaulting to ``FREE`` on
    unknown / null values (defense-in-depth — schema NOT NULL +
    server_default='free' should make this branch unreachable, but
    legacy rows from before the f7a8b9c0d1e2 migration won't have the
    column populated)."""
    raw = (user.tier or "free").strip().lower()
    try:
        return Tier(raw)
    except ValueError:
        return Tier.FREE


def capabilities_for(user: User) -> dict:
    """Return the capability dict for the given user's tier."""
    return TIER_CAPABILITIES[get_user_tier(user)]


def has_feature(user: User, feature: str) -> bool:
    """True iff the user's tier includes ``feature``."""
    return feature in capabilities_for(user)["features"]


def quota_limit(user: User, resource: str) -> int:
    """Return the user's tier limit for ``resource``.

    ``resource`` is one of ``youtube_units_per_day`` / ``llm_tokens_per_day``
    / ``document_count_cap``. Returns ``-1`` for unlimited resources
    (as on Studio's ``document_count_cap``).
    """
    return capabilities_for(user)[resource]


# ---------------------------------------------------------------------------
# FastAPI dependency factories
# ---------------------------------------------------------------------------


def require_tier(min_tier: Tier) -> Callable:
    """Dependency factory: raises 403 if ``current_user.tier < min_tier``.

    Usage:
        @router.post("/api/v1/author/books")
        def create_book(_: User = Depends(require_tier(Tier.PRO))):
            ...
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        if not get_user_tier(user).at_least(min_tier):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This feature requires the '{min_tier.value}' tier or higher. "
                    f"Your account is on '{get_user_tier(user).value}'."
                ),
            )
        return user

    return _check


def require_feature(feature: str) -> Callable:
    """Dependency factory: raises 403 if ``current_user.tier`` does not
    grant ``feature``. Convenience over ``require_tier`` when callers
    care about the named capability rather than the tier rank.

    Usage:
        @router.post("/api/v1/author/books")
        def create_book(_: User = Depends(require_feature("author_studio"))):
            ...
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        if not has_feature(user, feature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This feature ('{feature}') is not available on the "
                    f"'{get_user_tier(user).value}' tier. Please upgrade."
                ),
            )
        return user

    return _check

"""Echo (personal-brain) service — I-3 foundation.

Per-user identity / interests / hobbies / work / talents / skills /
personality / life events / locations / routines. Distinct from the
global library; this module manages *about-the-user* data.

Three layers:

1. **CRUD** on PersonalContext rows (``record``, ``get``, ``list``,
   ``delete``, ``revoke_source``).
2. **Connector abstraction** — `EchoConnector` Protocol + a
   registry. Concrete connectors (YouTube watch history, Spotify,
   email, calendar, browser history) live in future PRs and register
   themselves at import.
3. **Cold-start gate** — Echo features are gated behind a readiness
   threshold so the "speak as me" agent doesn't fire prematurely on
   sparse data. ``is_ready(user)`` returns ``(bool, dict)`` with
   diagnostics.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models.personal_context import PersonalContext
from app.models.user import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kinds — accepted values for `personal_context.kind`
# ---------------------------------------------------------------------------

# The set is closed at the API layer (unknown kinds rejected as 400);
# extending requires editing this list + adding a corresponding test.
SUPPORTED_KINDS: frozenset[str] = frozenset(
    {
        "location",
        "interest",
        "hobby",
        "work",
        "talent",
        "skill",
        "personality_trait",
        "life_event",
        "daily_routine",
        "place",
    }
)


class UnsupportedKindError(ValueError):
    pass


def _validate_kind(kind: str) -> None:
    if kind not in SUPPORTED_KINDS:
        raise UnsupportedKindError(
            f"Unknown personal-context kind '{kind}'. "
            f"Supported: {sorted(SUPPORTED_KINDS)}"
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def record_context(
    db: Session,
    *,
    user_id: str,
    kind: str,
    key: str,
    value: Any,
    source: str,
    confidence: float = 1.0,
    expires_at: datetime | None = None,
) -> PersonalContext:
    """Upsert a personal-context row keyed on ``(user_id, kind, key)``.

    ``value`` is JSON-encoded if not already a string. ``confidence``
    is clamped to [0.0, 1.0]. Re-recording the same (user_id, kind,
    key) updates the row's value + captured_at + expires_at +
    confidence; never duplicates.
    """
    _validate_kind(kind)
    if not source or not source.strip():
        raise ValueError("source is required (e.g. 'manual', 'youtube_watch_history')")
    if confidence < 0.0:
        confidence = 0.0
    elif confidence > 1.0:
        confidence = 1.0

    encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    existing = (
        db.query(PersonalContext)
        .filter(
            PersonalContext.user_id == user_id,
            PersonalContext.kind == kind,
            PersonalContext.key == key,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.value = encoded
        existing.source = source
        existing.confidence = confidence
        existing.captured_at = now
        existing.expires_at = expires_at
        db.commit()
        db.refresh(existing)
        return existing

    row = PersonalContext(
        user_id=user_id,
        kind=kind,
        key=key,
        value=encoded,
        source=source,
        confidence=confidence,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_context(
    db: Session, user_id: str, kind: str, key: str
) -> PersonalContext | None:
    return (
        db.query(PersonalContext)
        .filter(
            PersonalContext.user_id == user_id,
            PersonalContext.kind == kind,
            PersonalContext.key == key,
        )
        .first()
    )


def list_context(
    db: Session,
    user_id: str,
    *,
    kind: str | None = None,
    source: str | None = None,
    include_expired: bool = False,
) -> list[PersonalContext]:
    """List personal-context rows, optionally filtered by kind / source."""
    q = db.query(PersonalContext).filter(PersonalContext.user_id == user_id)
    if kind is not None:
        _validate_kind(kind)
        q = q.filter(PersonalContext.kind == kind)
    if source is not None:
        q = q.filter(PersonalContext.source == source)
    if not include_expired:
        now = datetime.now(timezone.utc)
        # Keep rows where expires_at is null OR > now.
        q = q.filter(
            (PersonalContext.expires_at.is_(None))
            | (PersonalContext.expires_at > now)
        )
    return q.order_by(PersonalContext.captured_at.desc()).all()


def delete_context(
    db: Session, user_id: str, kind: str, key: str
) -> bool:
    """Delete a single personal-context row. Returns True iff a row
    was deleted."""
    row = get_context(db, user_id, kind, key)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def revoke_source(db: Session, user_id: str, source: str) -> int:
    """Delete every row attributed to ``source`` for the user. Used
    when the user revokes a connector (e.g. unlinks Spotify). Returns
    the number of rows deleted."""
    rows = (
        db.query(PersonalContext)
        .filter(
            PersonalContext.user_id == user_id,
            PersonalContext.source == source,
        )
        .all()
    )
    for r in rows:
        db.delete(r)
    if rows:
        db.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Connector abstraction
# ---------------------------------------------------------------------------


class EchoConnector(Protocol):
    """Interface every Echo activity-stream connector implements.

    Concrete instances (Spotify, YouTube watch history, email, etc.)
    live in their own modules and register themselves into
    ``_CONNECTORS``. v1 ships zero concrete implementations — the
    Protocol is the contract that future PRs build against.
    """

    name: str  # e.g. "spotify_history", matches the `source` written to rows.

    def authorize_url(self, user: User, redirect_uri: str) -> str: ...

    def revoke(self, db: Session, user: User) -> None: ...

    def sync(self, db: Session, user: User) -> int:
        """Pull new data, persist via ``record_context``, return the
        count of rows added or updated."""

    def supported_kinds(self) -> set[str]:
        """Which `kind` values this connector emits."""


# Connector registry. Future PRs add entries via `register_connector`.
_CONNECTORS: dict[str, EchoConnector] = {}


def register_connector(connector: EchoConnector) -> None:
    """Register an Echo connector. Idempotent on `connector.name`."""
    _CONNECTORS[connector.name] = connector


def get_connector(name: str) -> EchoConnector | None:
    return _CONNECTORS.get(name)


def list_connectors() -> list[str]:
    return sorted(_CONNECTORS.keys())


# ---------------------------------------------------------------------------
# Cold-start readiness gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EchoReadiness:
    ready: bool
    total_rows: int
    distinct_sources: int
    has_personality_trait: bool
    threshold_total: int
    threshold_sources: int


# Tunable thresholds. Conservative defaults — Echo features should not
# fire on cold or near-cold accounts. Operators / SaaS can tune via
# environment overrides if needed.
DEFAULT_TOTAL_THRESHOLD = 100
DEFAULT_SOURCES_THRESHOLD = 3


def is_ready(
    db: Session,
    user_id: str,
    *,
    total_threshold: int = DEFAULT_TOTAL_THRESHOLD,
    sources_threshold: int = DEFAULT_SOURCES_THRESHOLD,
) -> EchoReadiness:
    """Echo is "ready" when the user has accumulated enough personal
    context for the "speak as me" agent (E-3.4) to produce useful
    output without hallucinating from sparse data:

    - At least ``total_threshold`` rows total (default 100).
    - At least ``sources_threshold`` distinct sources (default 3).
    - At least one ``personality_trait`` row.

    Returns an ``EchoReadiness`` with the details so callers can
    show a "you're 60% there" progress UI rather than just a yes/no.
    """
    rows = (
        db.query(PersonalContext)
        .filter(PersonalContext.user_id == user_id)
        .all()
    )
    total = len(rows)
    sources = {r.source for r in rows}
    has_personality = any(r.kind == "personality_trait" for r in rows)
    ready = (
        total >= total_threshold
        and len(sources) >= sources_threshold
        and has_personality
    )
    return EchoReadiness(
        ready=ready,
        total_rows=total,
        distinct_sources=len(sources),
        has_personality_trait=has_personality,
        threshold_total=total_threshold,
        threshold_sources=sources_threshold,
    )

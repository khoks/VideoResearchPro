"""Share tokens for adding to Echo from outside the app (S-3.7.3).

A token is ``pec_`` plus 32 random bytes, URL-safe. Only its SHA-256 hash is
stored (a token is high-entropy, so a plain hash is enough; no salt or slow
hash is needed). ``authenticate`` is the only way a token becomes a user, and
the routers accept it on the share intake endpoints alone (see
``routers/echo.py::share_intake_user``).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.echo_share_token import EchoShareToken

PREFIX = "pec_"
_DISPLAY_CHARS = 10
# Writing last_used_at on every share would turn each share into two writes;
# once a minute is plenty for "last used".
_TOUCH_EVERY = timedelta(minutes=1)


class TokenLimitReached(ValueError):
    """The tenant already has the maximum number of active tokens."""


class ShareTokenNotFound(LookupError):
    """No active token with that id belongs to this tenant."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_token(token: str | None) -> bool:
    return bool(token) and token.startswith(PREFIX)


def active(db: Session, tenant_id: str) -> list[EchoShareToken]:
    return (
        db.query(EchoShareToken)
        .filter(EchoShareToken.tenant_id == tenant_id, EchoShareToken.revoked_at.is_(None))
        .order_by(EchoShareToken.created_at.desc(), EchoShareToken.id.desc())
        .all()
    )


def create(db: Session, tenant_id: str, label: str) -> tuple[EchoShareToken, str]:
    """Make a token. Returns the row and the plaintext, which is never
    available again."""
    clean = " ".join((label or "").split())[:100] or "Browser extension"
    if len(active(db, tenant_id)) >= settings.ECHO_SHARE_TOKENS_MAX:
        raise TokenLimitReached(
            f"You have {settings.ECHO_SHARE_TOKENS_MAX} share tokens already; revoke one first."
        )
    token = PREFIX + secrets.token_urlsafe(32)
    row = EchoShareToken(
        tenant_id=tenant_id,
        label=clean,
        token_hash=_hash(token),
        prefix=token[:_DISPLAY_CHARS],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, token


def revoke(db: Session, tenant_id: str, token_id: str) -> EchoShareToken:
    row = db.get(EchoShareToken, token_id)
    if row is None or row.tenant_id != tenant_id or row.revoked_at is not None:
        raise ShareTokenNotFound(token_id)
    row.revoked_at = _now()
    db.commit()
    return row


def authenticate(db: Session, token: str) -> str | None:
    """The tenant id an active token belongs to, or None."""
    if not looks_like_token(token):
        return None
    row = (
        db.query(EchoShareToken)
        .filter(EchoShareToken.token_hash == _hash(token), EchoShareToken.revoked_at.is_(None))
        .one_or_none()
    )
    if row is None:
        return None
    now = _now()
    last = row.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last >= _TOUCH_EVERY:
        row.last_used_at = now
        db.commit()
    return row.tenant_id

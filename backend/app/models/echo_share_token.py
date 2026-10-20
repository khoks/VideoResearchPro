"""EchoShareToken — a long-lived, revocable credential that can only add to
the user's Echo inbox (S-3.7.3).

The browser extension, and later the OS share target and an iOS Shortcut,
cannot hold a session that expires in hours. This token lasts until revoked,
and it is scoped: it is accepted by the share intake endpoints
(``POST /echo/shares``, ``POST /echo/shares/upload``) and by the connection
check, and nowhere else. A stolen token can add shares; it cannot read
anything, and it cannot mint more tokens.

Only a SHA-256 hash is stored, with a short prefix for the user to recognise
the token by. The plaintext is shown once, when it is made. Registered in
``echo_privacy_service.ECHO_SECRET_TABLES`` (D-089): erased with the brain and
never exported.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EchoShareToken(Base):
    __tablename__ = "echo_share_tokens"
    __table_args__ = (Index("ix_echo_share_tokens_tenant", "tenant_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # What the user called it ("Chrome on the work laptop").
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # sha256(token), hex. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # The first characters, for recognising a token in the list ("pec_3f9a…").
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

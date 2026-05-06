"""Session model — T-5.4.7.

A row per issued JWT, keyed on the JWT ID (`jti`) claim. This gives
the app the ability to:

- Revoke individual sessions (logout from a single device).
- Revoke all sessions for a user ("logout everywhere" — useful after
  password change / suspected compromise).
- Audit the active-session set per user (where am I logged in from?).

The session is created when a token is issued (registration / login)
and consulted on every authenticated request. Tokens whose JTI doesn't
match an active row are rejected — even if the JWT signature still
verifies. This is what enables revocation; without it, the only way to
invalidate a JWT is to wait for it to expire.

The session is "revoked" by setting ``revoked_at`` (rather than
deleting the row) so the audit trail survives.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # The JWT ID claim. This is the identifier used in the token payload;
    # the session row is found by `jti`, never by the row's own id.
    jti: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Updated on every authenticated request. Useful for "your latest
    # active sessions" UI ordering and for stale-session reaping.
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Set on revocation. NULL = active.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    # Capture-at-issuance — useful for telling the user where they're
    # logged in from in the UI.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

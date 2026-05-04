"""PasswordResetToken model — E-5.4 auth hardening.

Single-use tokens for the forgot-password flow. Each row is generated
when a user requests a reset (``POST /api/v1/auth/password-reset/request``)
and consumed when the user submits the new password
(``POST /api/v1/auth/password-reset/confirm``).

Tokens are short-lived (default 30 minutes) and single-use — the
``consumed_at`` timestamp marks them spent. Subsequent attempts to use
the same token fail.

The token *value* stored in this table is a SHA-256 hash of the
random secret; the secret itself is only returned once, in the
response to the request endpoint (or in the operator log when SMTP
is unconfigured). This way, even if the database is compromised,
the raw tokens are not directly usable.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # SHA-256 hex of the actual reset secret. The secret itself is never
    # stored — it's returned to the user once and discarded server-side.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # When the token expires. Defaults to created_at + 30 min in the
    # service layer.
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Set when the token is consumed. Single-use enforcement.
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

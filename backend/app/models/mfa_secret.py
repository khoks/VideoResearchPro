"""MFA secret model — T-5.4.6 TOTP enrollment.

One row per user when MFA is enrolled (or in mid-enrollment). The TOTP
secret itself is stored encrypted (Fernet via ``BYOK_ENCRYPTION_KEY``,
reusing the encryption infrastructure from T-5.6.1). Recovery codes
are stored as JSON-encoded SHA-256 hashes; raw codes are returned to
the user exactly once at enrollment-verification time and never again.

Lifecycle:
- enroll() → row created with ``enabled=False``
- verify-enrollment() → ``enabled=True`` after a valid TOTP code is
  submitted. Recovery codes returned in this same response.
- login flow checks ``enabled`` to decide whether to require a second
  step.
- disable() → row deleted (or ``enabled=False`` reset).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MfaSecret(Base):
    __tablename__ = "mfa_secrets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Unique per user — at most one MFA secret in flight at a time.
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    # Fernet ciphertext of the TOTP secret. Decrypted only at verify time.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # JSON-encoded list of SHA-256 hashes of recovery codes. The raw
    # codes are returned to the user exactly once at enrollment.
    recovery_codes_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

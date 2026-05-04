"""UserCredential model — E-5.6 BYOK LLM keys foundation.

Stores per-user, per-provider API keys (encrypted at rest) so power
users can route their LLM calls to their own provider account rather
than the shared install-wide env-var key. Originally proposed in
[D-009](docs/decisions.md#d-009--twitter-x-stays-byok-paid-api--explicitly-opt-in-2026-04-25)
for Twitter; generalizes to LLM providers here.

Encryption is symmetric (`cryptography.fernet.Fernet`) keyed off the
``BYOK_ENCRYPTION_KEY`` env var. The plaintext secret is **never**
stored — only the Fernet ciphertext (which is base64-encoded URL-safe
text, suitable for ``Text``).

Schema:
- ``(user_id, provider)`` is unique. A user has at most one credential
  per provider; PUT-style overwrite via the service layer.
- ``provider`` is one of: ``openai``, ``anthropic``, ``google``,
  ``local`` (per the LLM-routing provider table).
- ``encrypted_secret`` is the Fernet ciphertext.
- ``label`` is a freeform human-readable name (e.g. "my OpenAI key —
  team org") shown in the UI; never used for routing.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserCredential(Base):
    __tablename__ = "user_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_credentials_user_provider"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
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

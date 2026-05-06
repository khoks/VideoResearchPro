"""OAuth state + identity models — T-5.4.5.

Two tables:

- ``oauth_states`` — short-lived (10 min) row created at the *start*
  of the OAuth flow. Carries the random ``state`` (CSRF protection)
  and the PKCE ``code_verifier`` (proof-of-possession). Consumed at
  callback time; deleted on use OR expiry.

- ``oauth_identities`` — long-lived link between a provider account
  (e.g. ``google:1234567890``) and a Pratidhvani ``users.id``. One
  user can have multiple linked identities (Google + GitHub); each
  ``(provider, provider_user_id)`` pair maps to exactly one user.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_oauth_identities_provider_user",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Provider-side stable user identifier (e.g. Google `sub`, GitHub `id`).
    provider_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    # Email reported by the provider at link time. NOT used for lookup
    # (provider_user_id is the key) — kept for audit / display.
    provider_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

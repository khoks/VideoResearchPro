"""Echo connector state (S-3.2.1): the grant, its credentials, pending OAuth.

Three tables, split by what the user's archive may carry:

* ``echo_connector_grants`` — that the user connected a connector, when, under
  which consent text, as which account, and how syncing is going. Part of the
  brain: exported and erased (``echo_privacy_service.ECHO_TABLES``).
* ``echo_connector_credentials`` — the OAuth tokens, Fernet-encrypted with the
  install's single key (D-043, ``byok_service.encrypt_secret``). Counted and
  erased with the brain but **never written into an export**, encrypted or not
  (``echo_privacy_service.ECHO_SECRET_TABLES``).
* ``echo_connector_oauth_states`` — the CSRF state and PKCE verifier of a
  connect that has not come back yet, bound to the tenant. Single use, expires
  in minutes; secret like the tokens.

All three are keyed per ``(tenant_id, connector)``. Revoking a connector
deletes its grant, credentials, pending states and every ``activity_events``
row it wrote, in one request.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EchoConnectorGrant(Base):
    __tablename__ = "echo_connector_grants"
    __table_args__ = (UniqueConstraint("tenant_id", "connector", name="uq_echo_connector_grants"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    connector: Mapped[str] = mapped_column(String(48), nullable=False)
    # The consent text version the user saw when they connected.
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    # The provider account, for display ("@octocat").
    account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # idle | syncing | error. A revoked grant has no row.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    backfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The connector's own resume point (an ETag, the newest event id seen).
    cursor_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"added": n, "updated": n, "facts": n} from the last sync.
    last_counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class EchoConnectorCredential(Base):
    __tablename__ = "echo_connector_credentials"
    __table_args__ = (UniqueConstraint("tenant_id", "connector", name="uq_echo_connector_credentials"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    connector: Mapped[str] = mapped_column(String(48), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class EchoConnectorOAuthState(Base):
    __tablename__ = "echo_connector_oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    connector: Mapped[str] = mapped_column(String(48), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(256), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

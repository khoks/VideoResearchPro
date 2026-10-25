"""The connector runtime (S-3.2.1): everything around a connector.

A connector (``app/connectors/<name>/``) only talks to its provider. This
module owns the rest, per tenant:

1. **Consent.** ``describe`` gives the consent screen what it must show (the
   disclosure, the privacy weight, the event types) and the disclosure's
   version. ``start_connect`` refuses a version the user did not see.
2. **Connect.** OAuth with a single-use, tenant-bound state and a PKCE
   verifier (``echo_connector_oauth_states``, ten minutes). The redirect URI
   is built here from ``APP_BASE_URL``, never taken from the client, so the
   code can only come back to this app. ``complete_connect`` checks the state
   belongs to the caller, exchanges the code, stores the tokens Fernet
   encrypted (D-043), records the grant, schedules syncs and queues the
   backfill.
3. **Sync.** ``run_sync`` backfills once, then syncs incrementally from the
   last success, storing events idempotently and derived facts below 1.0
   confidence (source ``connector:<name>``). Fail-soft: a provider error marks
   the grant ``error`` with the reason; an auth error, or a stored token
   this install can no longer decrypt, asks the user to reconnect.
4. **Revoke.** One request deletes the grant, tokens, pending states, every
   event and every derived fact of that connector, and its schedule. Revoking
   at the provider is best effort; local data goes regardless.

The scheduler kind is ``echo_sync`` (D-077: registered from
``tasks/echo_connector_tasks.py``, which ``celery_app`` autodiscovers).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors import registry
from app.connectors.base import ActivityConnector, ConnectorError, ConnectorTokens, SyncContext
from app.models.echo_connector import (
    EchoConnectorCredential,
    EchoConnectorGrant,
    EchoConnectorOAuthState,
)
from app.models.personal_context import PersonalContext
from app.services import activity_event_service, byok_service, echo_service, scheduler_service

logger = logging.getLogger(__name__)

KIND = "echo_sync"
# Connectors the roadmap names that this build cannot offer yet, with why.
# Readiness lists them as "not connected" rather than missing (S-3.5.1).
PLANNED_CONNECTORS: tuple[tuple[str, str, str], ...] = (
    ("youtube_likes", "YouTube likes", "Waits on this install's Google connector OAuth client (S-3.2.2)."),
    ("google_calendar", "Google Calendar", "Waits on this install's Google connector OAuth client (S-3.2.5)."),
)
STATE_TTL = timedelta(minutes=10)
MAX_FACT_CONFIDENCE = 0.9
# A grant whose ``last_error`` starts with this needs the user to connect
# again; the connectors panel shows "Reconnect" for it.
RECONNECT_PREFIX = "Reconnect to sync: "


class ConnectorNotFound(LookupError):
    """No such connector, or (for a tenant) no grant for it."""


class ConnectorUnavailable(RuntimeError):
    """The install has no OAuth client for this connector."""


class ConsentMismatch(ValueError):
    """The caller agreed to a different disclosure than the current one."""


class ConnectError(RuntimeError):
    """The OAuth round trip failed (state, code exchange). Deliberately
    vague towards the client, like the login flow (D-040)."""


@dataclass
class SyncOutcome:
    status: str  # ok | error | auth_error | missing
    added: int = 0
    updated: int = 0
    facts: int = 0
    error: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _connector(name: str):
    registry.load_builtin()
    conn = registry.get_connector(name)
    if conn is None:
        raise ConnectorNotFound(name)
    return conn


def redirect_uri(name: str) -> str:
    """Where the provider sends the browser back: the frontend route that
    posts the code to ``complete_connect``. Register the app's callback URL
    as the frontend origin (or this path) with the provider."""
    return f"{settings.APP_BASE_URL.rstrip('/')}/echo/connectors/{name}/callback"


# --------------------------------------------------------------------------- describe

def describe(conn, grant: EchoConnectorGrant | None = None, events: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": conn.name,
        "display_name": conn.display_name,
        "privacy_weight": conn.privacy_weight,
        "consent_disclosure": conn.consent_disclosure,
        "consent_version": conn.consent_version,
        "event_types": list(conn.event_types()),
        "configured": bool(conn.is_configured()),
        "connected": grant is not None,
        "grant": None,
    }
    if grant is not None:
        out["grant"] = {
            "account_label": grant.account_label,
            "granted_at": grant.granted_at,
            "consent_version": grant.consent_version,
            "consent_outdated": grant.consent_version != conn.consent_version,
            "status": grant.status,
            "last_sync_at": grant.last_sync_at,
            "backfilled_at": grant.backfilled_at,
            "last_error": grant.last_error,
            "last_counts": json.loads(grant.last_counts_json) if grant.last_counts_json else None,
            "events": events,
        }
    return out


def get_grant(db: Session, tenant_id: str, name: str) -> EchoConnectorGrant | None:
    return (
        db.query(EchoConnectorGrant)
        .filter(EchoConnectorGrant.tenant_id == tenant_id, EchoConnectorGrant.connector == name)
        .first()
    )


def list_for_tenant(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    registry.load_builtin()
    out = []
    for conn in registry.connectors():
        if not isinstance(conn, ActivityConnector):
            logger.warning("echo: registered connector %r does not implement the contract; skipped", conn)
            continue
        grant = get_grant(db, tenant_id, conn.name)
        count = activity_event_service.count_events(db, tenant_id, conn.name) if grant else 0
        out.append(describe(conn, grant, count))
    return out


# --------------------------------------------------------------------------- connect

def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def start_connect(db: Session, tenant_id: str, name: str, consent_version: str) -> str:
    """Return the provider's authorize URL after recording the tenant-bound
    state. Raises ``ConsentMismatch`` unless ``consent_version`` is the one
    the consent screen showed."""
    conn = _connector(name)
    if not conn.is_configured():
        raise ConnectorUnavailable(name)
    if consent_version != conn.consent_version:
        raise ConsentMismatch(name)
    now = _now()
    # One pending connect per tenant and connector; expired ones go too.
    db.query(EchoConnectorOAuthState).filter(
        EchoConnectorOAuthState.tenant_id == tenant_id, EchoConnectorOAuthState.connector == name
    ).delete(synchronize_session=False)
    db.query(EchoConnectorOAuthState).filter(
        EchoConnectorOAuthState.expires_at < _naive(now)
    ).delete(synchronize_session=False)
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce()
    uri = redirect_uri(name)
    db.add(EchoConnectorOAuthState(
        state=state, tenant_id=tenant_id, connector=name, code_verifier=verifier,
        redirect_uri=uri, consent_version=consent_version, expires_at=_naive(now + STATE_TTL),
    ))
    db.commit()
    return conn.authorize_url(redirect_uri=uri, state=state, code_challenge=challenge)


def complete_connect(db: Session, tenant_id: str, name: str, *, state: str, code: str) -> EchoConnectorGrant:
    """Finish the OAuth round trip for the caller. The state must exist, be
    the caller's, be for this connector and not have expired; it is consumed
    either way."""
    conn = _connector(name)
    row = db.get(EchoConnectorOAuthState, state)
    if row is None or row.tenant_id != tenant_id or row.connector != name:
        raise ConnectError("unknown state")
    expired = row.expires_at <= _naive(_now())
    verifier, uri, consent_version = row.code_verifier, row.redirect_uri, row.consent_version
    db.delete(row)
    db.commit()
    if expired:
        raise ConnectError("state expired")
    try:
        tokens = conn.handle_callback(code=code, redirect_uri=uri, code_verifier=verifier)
    except ConnectorError as e:
        raise ConnectError(str(e)) from e

    _store_tokens(db, tenant_id, name, tokens)
    grant = get_grant(db, tenant_id, name)
    if grant is None:
        grant = EchoConnectorGrant(tenant_id=tenant_id, connector=name, consent_version=consent_version)
        db.add(grant)
    grant.consent_version = consent_version
    grant.granted_at = _now()
    grant.account_label = tokens.account_label
    grant.scopes = tokens.scopes or None
    grant.status = "idle"
    grant.last_error = None
    db.commit()
    db.refresh(grant)

    if conn.schedule:
        try:
            scheduler_service.schedule(db, kind=KIND, target_id=grant.id, cadence=conn.schedule, tenant_id=tenant_id)
        except Exception:
            logger.exception("echo: could not schedule %s syncs for %s", name, tenant_id[:8])
    enqueue_sync(grant.id)
    logger.info("echo: tenant %s connected %s as %s", tenant_id[:8], name, tokens.account_label)
    return grant


def _store_tokens(db: Session, tenant_id: str, name: str, tokens: ConnectorTokens) -> None:
    cred = (
        db.query(EchoConnectorCredential)
        .filter(EchoConnectorCredential.tenant_id == tenant_id, EchoConnectorCredential.connector == name)
        .first()
    )
    if cred is None:
        cred = EchoConnectorCredential(tenant_id=tenant_id, connector=name, access_token_encrypted="")
        db.add(cred)
    cred.access_token_encrypted = byok_service.encrypt_secret(tokens.access_token)
    cred.refresh_token_encrypted = (
        byok_service.encrypt_secret(tokens.refresh_token) if tokens.refresh_token else None
    )
    cred.expires_at = _naive(tokens.expires_at)
    db.commit()


def load_tokens(db: Session, tenant_id: str, name: str) -> ConnectorTokens | None:
    cred = (
        db.query(EchoConnectorCredential)
        .filter(EchoConnectorCredential.tenant_id == tenant_id, EchoConnectorCredential.connector == name)
        .first()
    )
    if cred is None:
        return None
    grant = get_grant(db, tenant_id, name)
    return ConnectorTokens(
        access_token=byok_service.decrypt_secret(cred.access_token_encrypted),
        refresh_token=byok_service.decrypt_secret(cred.refresh_token_encrypted) if cred.refresh_token_encrypted else None,
        expires_at=cred.expires_at,
        scopes=(grant.scopes if grant else "") or "",
        account_label=grant.account_label if grant else None,
    )


# --------------------------------------------------------------------------- sync

def enqueue_sync(grant_id: str) -> str:
    """Queue a sync. ``inline`` runs it now (tests, self-host without a
    worker); ``off`` leaves it to the next scheduled tick or "Sync now"."""
    mode = (settings.ECHO_CONNECTOR_SYNC or "celery").lower()
    if mode == "off":
        return "off"
    if mode == "inline":
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            run_sync(db, grant_id)
        finally:
            db.close()
        return "ran"
    try:
        from app.tasks.echo_connector_tasks import sync_echo_connector

        sync_echo_connector.delay(grant_id, trigger="manual")
        return "queued"
    except Exception:
        logger.exception("echo: could not queue the sync for grant %s", grant_id)
        return "queue_failed"


def run_sync(db: Session, grant_id: str) -> SyncOutcome:
    """Backfill once, then sync from the last success. Never raises for a
    provider failure: the grant records it."""
    grant = db.get(EchoConnectorGrant, grant_id)
    if grant is None:
        # Revoked between scheduling and running.
        scheduler_service.unschedule(db, KIND, grant_id)
        return SyncOutcome("missing")
    try:
        conn = _connector(grant.connector)
    except ConnectorNotFound:
        grant.status, grant.last_error = "error", "This connector is not available on this install."
        db.commit()
        return SyncOutcome("error", error=grant.last_error)
    try:
        tokens = load_tokens(db, grant.tenant_id, grant.connector)
    except (InvalidToken, UnicodeError):
        # The stored ciphertext no longer opens: BYOK_ENCRYPTION_KEY was
        # rotated (or never set, so each process had its own key), or the
        # row is corrupted. Only a fresh connect can mint a token this key
        # reads, so ask for one rather than crash the worker task. The
        # ciphertext and the secret stay out of the log.
        logger.warning(
            "echo: stored %s token for %s could not be decrypted; the grant needs a reconnect",
            grant.connector, grant.tenant_id[:8],
        )
        grant.status = "error"
        grant.last_error = RECONNECT_PREFIX + "the stored access token can no longer be read on this install."
        db.commit()
        return SyncOutcome("auth_error", error=grant.last_error)
    except byok_service.EncryptionConfigurationError:
        # BYOK_ENCRYPTION_KEY itself is malformed. Reconnecting cannot help
        # (storing the new token would fail the same way): the operator must
        # fix the key.
        logger.error("echo: %s sync for %s skipped: BYOK_ENCRYPTION_KEY is not a valid key", grant.connector, grant.tenant_id[:8])
        grant.status = "error"
        grant.last_error = "Sync failed: this install's encryption key is not valid. Ask the operator to fix it."
        db.commit()
        return SyncOutcome("error", error=grant.last_error)
    if tokens is None:
        grant.status, grant.last_error = "error", RECONNECT_PREFIX + "the access token is missing."
        db.commit()
        return SyncOutcome("auth_error", error=grant.last_error)

    started = _now()
    grant.status = "syncing"
    db.commit()
    ctx = SyncContext(
        tenant_id=grant.tenant_id,
        tokens=tokens,
        cursor=json.loads(grant.cursor_json) if grant.cursor_json else {},
    )
    backfill = grant.backfilled_at is None
    try:
        events = conn.initial_backfill(ctx) if backfill else conn.incremental_sync(ctx, grant.last_sync_at)
        counts = activity_event_service.store_events(db, grant.tenant_id, grant.connector, events)
        facts = _store_facts(db, grant, ctx)
    except ConnectorError as e:
        db.rollback()
        grant = db.get(EchoConnectorGrant, grant_id)
        grant.status = "error"
        grant.last_error = (RECONNECT_PREFIX if e.auth else "") + str(e)[:500]
        db.commit()
        logger.warning("echo: %s sync for %s failed: %s", grant.connector, grant.tenant_id[:8], e)
        return SyncOutcome("auth_error" if e.auth else "error", error=grant.last_error)
    except Exception as e:  # unexpected: fail-soft, logged loudly
        db.rollback()
        logger.exception("echo: %s sync crashed for grant %s", grant.connector, grant_id)
        grant = db.get(EchoConnectorGrant, grant_id)
        grant.status, grant.last_error = "error", f"Sync failed: {type(e).__name__}"
        db.commit()
        return SyncOutcome("error", error=grant.last_error)

    grant.cursor_json = json.dumps(ctx.cursor) if ctx.cursor else None
    grant.last_sync_at = started
    if backfill:
        grant.backfilled_at = started
    grant.status = "idle"
    grant.last_error = None
    grant.last_counts_json = json.dumps({"added": counts["added"], "updated": counts["updated"], "facts": facts})
    db.commit()
    return SyncOutcome("ok", added=counts["added"], updated=counts["updated"], facts=facts)


def fact_source(name: str) -> str:
    return f"connector:{name}"


def _store_facts(db: Session, grant: EchoConnectorGrant, ctx: SyncContext) -> int:
    for fact in ctx.facts:
        echo_service.record_context(
            db,
            user_id=grant.tenant_id,
            kind=fact.kind,
            key=fact.key,
            value=fact.value,
            source=fact_source(grant.connector),
            confidence=min(float(fact.confidence), MAX_FACT_CONFIDENCE),
        )
    return len(ctx.facts)


# --------------------------------------------------------------------------- revoke

def _revoke_at_provider(conn, tokens: ConnectorTokens | None) -> bool:
    if tokens is None:
        return False
    try:
        conn.revoke(tokens)
        return True
    except Exception:
        logger.warning("echo: revoking %s at the provider failed; local data is deleted anyway", conn.name)
        return False


def revoke(db: Session, tenant_id: str, name: str) -> dict[str, Any]:
    """Disconnect: revoke at the provider (best effort), then delete the
    grant, tokens, pending states, events and derived facts in one commit."""
    grant = get_grant(db, tenant_id, name)
    tokens = None
    try:
        tokens = load_tokens(db, tenant_id, name)
    except Exception:
        logger.warning("echo: stored %s token for %s could not be decrypted", name, tenant_id[:8])
    conn = registry.get_connector(name)
    if grant is None and tokens is None and conn is None:
        raise ConnectorNotFound(name)
    provider_revoked = _revoke_at_provider(conn, tokens) if conn is not None else False

    events = activity_event_service.delete_connector_events(db, tenant_id, name)
    facts = (
        db.query(PersonalContext)
        .filter(PersonalContext.user_id == tenant_id, PersonalContext.source == fact_source(name))
        .delete(synchronize_session=False)
    )
    db.query(EchoConnectorCredential).filter(
        EchoConnectorCredential.tenant_id == tenant_id, EchoConnectorCredential.connector == name
    ).delete(synchronize_session=False)
    db.query(EchoConnectorOAuthState).filter(
        EchoConnectorOAuthState.tenant_id == tenant_id, EchoConnectorOAuthState.connector == name
    ).delete(synchronize_session=False)
    if grant is not None:
        scheduler_service.unschedule(db, KIND, grant.id)
        db.delete(grant)
    db.commit()
    # S-3.3.3: the revoked facts and the signals that lost their examples
    # leave personal_context_global now, not at the next startup backfill.
    from app.services import echo_personal_vectors

    echo_personal_vectors.sync_soft(db, tenant_id)
    logger.info("echo: tenant %s revoked %s (events=%d facts=%d)", tenant_id[:8], name, events, facts)
    return {"connector": name, "events": events, "facts": facts, "provider_revoked": provider_revoked}


def revoke_all_for_brain_delete(db: Session, tenant_id: str) -> int:
    """Before the full delete erases the rows: revoke every grant at its
    provider (best effort) and drop the schedules, which are not Echo rows.
    Returns how many providers accepted the revoke."""
    accepted = 0
    for grant in db.query(EchoConnectorGrant).filter(EchoConnectorGrant.tenant_id == tenant_id).all():
        conn = registry.get_connector(grant.connector)
        try:
            tokens = load_tokens(db, tenant_id, grant.connector)
        except Exception:
            tokens = None
        if conn is not None and _revoke_at_provider(conn, tokens):
            accepted += 1
        scheduler_service.unschedule(db, KIND, grant.id)
    return accepted


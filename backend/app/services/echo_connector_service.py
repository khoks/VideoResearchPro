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
   confidence (source ``connector:<name>``), except the keys the user deleted
   (T-3.2.4.4, ``echo_fact_tombstones``) and the keys a row the user wrote
   holds (T-3.2.1.11). An access token past its ``expires_at`` is renewed
   first through the connector's ``refresh_tokens`` and stored encrypted
   (T-3.2.2.5); a 401 on a call made through ``SyncContext.call`` renews once
   and retries that call once. One reader of a grant spends its refresh token
   at a time, and the others use the result (T-3.2.1.12, ``_await_refresh``).
   Two syncs of a grant may run at once (a schedule and "Sync now"), and both
   finish: events and facts are stored by inserts the database decides, so
   neither fails on the other's row (T-3.2.1.13).
   Fail-soft: a provider error marks the grant ``error`` with the reason; only
   what a sync cannot get past asks the user to reconnect: a provider refusing
   the refresh token or a token it just issued, an auth error on a grant that
   cannot be renewed, or a stored token this install can no longer decrypt.
   No token reaches a log line or ``last_error`` (``_scrub``).
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
import time
import traceback
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import InvalidToken
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors import registry
from app.connectors.base import (
    ActivityConnector,
    ConnectorError,
    ConnectorTokens,
    RefreshableConnector,
    SyncContext,
    TokenRenewalFailed,
)
from app.models.echo_connector import (
    EchoConnectorCredential,
    EchoConnectorGrant,
    EchoConnectorOAuthState,
)
from app.models.personal_context import PersonalContext
from app.services import (
    activity_event_service,
    byok_service,
    echo_fact_tombstones,
    echo_service,
    scheduler_service,
)

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
# An access token this close to its expiry is renewed before the sync, so
# it cannot lapse between the check and the provider call.
REFRESH_SKEW = timedelta(seconds=60)
# A refresh claim older than this belongs to a reader that died: the next one
# may take it. Well above a provider call (connectors time out at 20 s).
REFRESH_CLAIM_TTL = timedelta(seconds=120)
# How long a second reader waits for the first's renewed token, then how often
# it looks. Past the wait it stops with an error the next sync retries.
REFRESH_WAIT_SECONDS = 30.0
REFRESH_POLL_SECONDS = 0.25


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
    # Derived facts skipped because a row the user wrote holds the key.
    facts_kept_manual: int = 0
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
    # T-5.6.9: the tokens are stored encrypted. With a malformed key that
    # fails only after the user has signed in at the provider, so refuse now.
    byok_service.require_valid_key()
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


def _credential(db: Session, tenant_id: str, name: str) -> EchoConnectorCredential | None:
    """The row as the database holds it now, not as this session last saw it:
    another reader may have renewed the tokens."""
    return (
        db.query(EchoConnectorCredential)
        .populate_existing()
        .filter(EchoConnectorCredential.tenant_id == tenant_id, EchoConnectorCredential.connector == name)
        .first()
    )


def _store_tokens(db: Session, tenant_id: str, name: str, tokens: ConnectorTokens) -> None:
    """A fresh connect: new tokens, and any refresh claim on the old ones is
    moot."""
    cred = _credential(db, tenant_id, name)
    if cred is None:
        cred = EchoConnectorCredential(tenant_id=tenant_id, connector=name, access_token_encrypted="")
        db.add(cred)
    _write_tokens(cred, tokens)
    cred.refresh_claim = cred.refresh_claimed_at = None
    db.commit()


def _write_tokens(cred: EchoConnectorCredential, tokens: ConnectorTokens) -> None:
    access = byok_service.encrypt_secret(tokens.access_token)
    refresh = byok_service.encrypt_secret(tokens.refresh_token) if tokens.refresh_token else None
    cred.access_token_encrypted, cred.refresh_token_encrypted = access, refresh
    cred.expires_at = _naive(tokens.expires_at)


def _read_tokens(cred: EchoConnectorCredential) -> tuple[str, str | None]:
    refresh = byok_service.decrypt_secret(cred.refresh_token_encrypted) if cred.refresh_token_encrypted else None
    return byok_service.decrypt_secret(cred.access_token_encrypted), refresh


def load_tokens(db: Session, tenant_id: str, name: str) -> ConnectorTokens | None:
    cred = _credential(db, tenant_id, name)
    if cred is None:
        return None
    grant = get_grant(db, tenant_id, name)
    access, refresh = _read_tokens(cred)
    return ConnectorTokens(
        access_token=access,
        refresh_token=refresh,
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
    tenant_id, name = grant.tenant_id, grant.connector
    grant.status = "syncing"
    db.commit()
    ctx = SyncContext(
        tenant_id=tenant_id,
        tokens=tokens,
        cursor=json.loads(grant.cursor_json) if grant.cursor_json else {},
    )
    held = [tokens]  # every token of this sync, to keep out of what it reports

    def renew() -> ConnectorTokens:
        fresh = _renew(db, tenant_id, name, conn, ctx.tokens)
        held.append(fresh)
        return fresh

    if tokens.refresh_token and isinstance(conn, RefreshableConnector):
        ctx.renew = renew
    backfill = grant.backfilled_at is None
    try:
        if needs_refresh(tokens):
            ctx.tokens = renew()
        events = conn.initial_backfill(ctx) if backfill else conn.incremental_sync(ctx, grant.last_sync_at)
        counts = activity_event_service.store_events(db, tenant_id, name, events)
        facts, kept = _store_facts(db, tenant_id, name, ctx)
    except ConnectorError as e:
        db.rollback()
        reason = _scrub(str(e), *held)
        logger.warning("echo: %s sync for %s failed: %s", name, tenant_id[:8], reason)
        grant = db.get(EchoConnectorGrant, grant_id)
        if grant is None:  # disconnected while it ran
            return SyncOutcome("missing")
        grant.status = "error"
        grant.last_error = (RECONNECT_PREFIX if e.auth else "") + reason[:500]
        db.commit()
        return SyncOutcome("auth_error" if e.auth else "error", error=grant.last_error)
    except Exception as e:  # unexpected: fail-soft, logged loudly
        db.rollback()
        logger.error("echo: %s sync crashed for grant %s:\n%s", name, grant_id, _scrub(traceback.format_exc(), *held))
        grant = db.get(EchoConnectorGrant, grant_id)
        if grant is None:
            return SyncOutcome("missing")
        grant.status, grant.last_error = "error", f"Sync failed: {type(e).__name__}"
        db.commit()
        return SyncOutcome("error", error=grant.last_error)

    grant.cursor_json = json.dumps(ctx.cursor) if ctx.cursor else None
    grant.last_sync_at = started
    if backfill:
        grant.backfilled_at = started
    grant.status = "idle"
    grant.last_error = None
    summary = {"added": counts["added"], "updated": counts["updated"], "facts": facts}
    if kept:
        summary["facts_kept_manual"] = kept
    grant.last_counts_json = json.dumps(summary)
    db.commit()
    return SyncOutcome("ok", added=counts["added"], updated=counts["updated"], facts=facts, facts_kept_manual=kept)


def needs_refresh(tokens: ConnectorTokens, now: datetime | None = None) -> bool:
    """Whether the access token has expired (or will within ``REFRESH_SKEW``).
    A token with no ``expires_at`` (GitHub's) never needs one."""
    expires_at = _naive(tokens.expires_at)
    if expires_at is None:
        return False
    return expires_at <= _naive((now or _now()) + REFRESH_SKEW)


def _scrub(text: str, *held: ConnectorTokens) -> str:
    """``text`` with every token value in it blanked. A provider's error body
    or a connector's message can echo what it was sent, and what this returns
    goes to the log and to ``last_error``, which the panel shows. Scrub before
    truncating: half a token is still a leak."""
    for tokens in held:
        for secret in (tokens.access_token, tokens.refresh_token):
            if secret:
                text = text.replace(secret, "[token]").replace(urllib.parse.quote(secret, safe=""), "[token]")
    return text


def _claim_refresh(db: Session, tenant_id: str, name: str, claim: str) -> bool:
    """Take the right to spend this grant's refresh token. Atomic: the UPDATE's
    WHERE repeats the check, so of two readers one sees rowcount 1. A lease, so
    a reader that dies holding it blocks the others for ``REFRESH_CLAIM_TTL``
    at most. Commits at once: nothing is held open during the provider call."""
    now = _naive(_now())
    cred = EchoConnectorCredential
    result = db.execute(
        update(cred)
        .where(
            cred.tenant_id == tenant_id,
            cred.connector == name,
            or_(cred.refresh_claimed_at.is_(None), cred.refresh_claimed_at < now - REFRESH_CLAIM_TTL),
        )
        .values(refresh_claim=claim, refresh_claimed_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _release_refresh(db: Session, tenant_id: str, name: str, claim: str) -> None:
    """Give the claim back, if it is still this reader's. Best effort: a
    claim left behind lapses on its own."""
    cred = EchoConnectorCredential
    try:
        db.execute(
            update(cred)
            .where(cred.tenant_id == tenant_id, cred.connector == name, cred.refresh_claim == claim)
            .values(refresh_claim=None, refresh_claimed_at=None)
            .execution_options(synchronize_session=False)
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("echo: could not release the %s refresh claim for %s: %s", name, tenant_id[:8], type(e).__name__)


def _await_refresh(
    db: Session, tenant_id: str, name: str, held: ConnectorTokens
) -> tuple[str | None, ConnectorTokens]:
    """Settle who renews (T-3.2.1.12). A scheduled sync and "Sync now" can both
    find the token expired, and a provider that rotates refresh tokens answers
    a second use of the old one with ``invalid_grant`` (some revoke the whole
    grant for it). So one reader claims the refresh per connector and the
    others wait for its result.

    Returns ``(claim, tokens)``: a claim means this reader spends ``tokens``'
    refresh token and must release it; None means another reader already
    renewed and ``tokens`` is its result. Every pass reads the row AFTER trying
    to claim, so a reader that finished just before this one claimed is seen
    rather than renewed over. Raises ``TokenRenewalFailed`` past the wait."""
    claim = str(uuid.uuid4())
    deadline = time.monotonic() + REFRESH_WAIT_SECONDS
    while True:
        claimed = _claim_refresh(db, tenant_id, name, claim)
        current = load_tokens(db, tenant_id, name)
        if current is None:  # disconnected: run_sync reports the grant gone
            raise TokenRenewalFailed("the connector was disconnected during the sync")
        if current.access_token != held.access_token and not needs_refresh(current):
            if claimed:
                _release_refresh(db, tenant_id, name, claim)
            return None, current
        if claimed:
            return claim, current
        if time.monotonic() >= deadline:
            raise _renewal_failed("another sync is still renewing it")
        time.sleep(REFRESH_POLL_SECONDS)


def _renewal_failed(why: str) -> TokenRenewalFailed:
    return TokenRenewalFailed(f"Sync failed: could not renew the access token ({why}). The next sync tries again.")


def _renew(db: Session, tenant_id: str, name: str, conn, held: ConnectorTokens) -> ConnectorTokens:
    """T-3.2.2.5, T-3.2.1.12: replace ``held``, expired or just refused by the
    provider, and store the new tokens encrypted like the first (D-043).

    Returns the tokens to use, from this reader's refresh or another's. Raises
    ``ConnectorError``, which ``run_sync`` records on the grant: with
    ``auth=True`` (reconnect) for a missing refresh token, a connector that
    cannot refresh, or a refresh the provider refuses; ``TokenRenewalFailed``
    (the next sync retries) for anything else, since the refresh token may
    still be good. Neither token is ever logged."""
    who = (name, tenant_id[:8])
    if not held.refresh_token:
        logger.info("echo: the %s access token for %s expired with no refresh token; reconnect needed", *who)
        raise ConnectorError("the access token expired and there is no refresh token to renew it.", auth=True)
    if not isinstance(conn, RefreshableConnector):
        logger.warning("echo: the %s access token for %s expired and the connector cannot refresh it", *who)
        raise ConnectorError("the access token expired and this connector cannot renew it.", auth=True)
    claim, current = _await_refresh(db, tenant_id, name, held)
    if claim is None:
        logger.info("echo: using the %s access token another sync renewed for %s", *who)
        return current
    try:
        return _spend_refresh_token(db, tenant_id, name, conn, current, claim)
    finally:
        _release_refresh(db, tenant_id, name, claim)


def _spend_refresh_token(
    db: Session, tenant_id: str, name: str, conn, tokens: ConnectorTokens, claim: str
) -> ConnectorTokens:
    """Call the provider under ``claim`` and store what it returns, releasing
    the claim in the same commit. Nothing is held open during the call, so the
    row can change meanwhile: a fresh connect, or a reader that took a lapsed
    claim and finished first. Then that write stands and this returns it."""
    who = (name, tenant_id[:8])
    try:
        fresh = conn.refresh_tokens(tokens)
    except ConnectorError as e:
        if e.auth:
            # A refusal is a revocation unless the token it refused is no
            # longer the stored one: a reader that outlived its claim got there
            # first, and its result is good.
            latest = load_tokens(db, tenant_id, name)
            if latest is not None and latest.refresh_token != tokens.refresh_token:
                logger.info("echo: another sync rotated the %s refresh token for %s; using its result", *who)
                return latest
            logger.warning("echo: %s refused to renew the access token for %s; reconnect needed", *who)
            raise ConnectorError("the provider no longer accepts this connection.", auth=True) from None
        reason = _scrub(str(e), tokens)
        logger.warning("echo: renewing the %s access token for %s failed: %s", *who, reason)
        raise _renewal_failed(reason[:300]) from None
    except Exception as e:  # a connector bug or a transport error: fail-soft
        logger.error("echo: renewing the %s access token for %s crashed: %s", *who, type(e).__name__)
        raise _renewal_failed(type(e).__name__) from None
    if fresh is None or not getattr(fresh, "access_token", None):
        logger.error("echo: the %s connector returned no access token on refresh for %s", *who)
        raise _renewal_failed("the provider returned no access token")

    renewed = ConnectorTokens(
        access_token=fresh.access_token,
        # Most providers do not rotate the refresh token: keep the stored one.
        refresh_token=fresh.refresh_token or tokens.refresh_token,
        expires_at=fresh.expires_at,
        scopes=fresh.scopes or tokens.scopes,
        account_label=tokens.account_label,
    )
    cred = _credential(db, tenant_id, name)
    if cred is None:
        # Disconnected while the provider answered: never bring the token back.
        raise TokenRenewalFailed("the connector was disconnected during the sync")
    try:
        if _read_tokens(cred) != (tokens.access_token, tokens.refresh_token):
            logger.info("echo: the %s tokens for %s changed during the refresh; keeping the stored ones", *who)
            return load_tokens(db, tenant_id, name)
        _write_tokens(cred, renewed)
    except byok_service.EncryptionConfigurationError:
        db.rollback()
        logger.error("echo: %s sync for %s skipped: BYOK_ENCRYPTION_KEY is not a valid key", *who)
        raise TokenRenewalFailed(
            "Sync failed: this install's encryption key is not valid. Ask the operator to fix it."
        ) from None
    # Stored even if the claim lapsed: nothing else wrote, so a rotated token
    # is the only live copy.
    if cred.refresh_claim == claim:
        cred.refresh_claim = cred.refresh_claimed_at = None
    db.commit()
    logger.info("echo: renewed the %s access token for %s", *who)
    return renewed


def fact_source(name: str) -> str:
    return f"connector:{name}"


def _store_facts(db: Session, tenant_id: str, name: str, ctx: SyncContext) -> tuple[int, int]:
    """Upsert the sync's derived facts, skipping every key the user deleted
    (T-3.2.4.4) and every key a row the user wrote holds (T-3.2.1.11). Returns
    how many were written, and how many of the second kind were skipped."""
    blocked = echo_fact_tombstones.blocked_keys(db, tenant_id, name)
    stored = kept = 0
    for fact in ctx.facts:
        if (fact.kind, fact.key) in blocked:
            continue
        written = echo_service.record_derived_context(
            db,
            user_id=tenant_id,
            kind=fact.kind,
            key=fact.key,
            value=fact.value,
            source=fact_source(name),
            confidence=min(float(fact.confidence), MAX_FACT_CONFIDENCE),
        )
        if written is None:
            kept += 1
        else:
            stored += 1
    return stored, kept


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


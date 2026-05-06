"""OAuth 2.0 + PKCE flow — T-5.4.5.

Two providers ship: ``google`` and ``github``. Each is a small
config-driven adapter implementing the ``OAuthProvider`` protocol;
adding a third (e.g. Microsoft, GitLab) is a 30-line file + a Settings
entry.

Flow:

1. ``start_flow(provider, redirect_uri)`` →
   - generates ``state`` (32 bytes random hex) for CSRF protection.
   - generates PKCE verifier + S256 challenge.
   - persists ``oauth_states`` row with 10 min TTL.
   - returns the provider's authorization URL.

2. User authorizes in the provider's UI; provider redirects to the
   app's callback with ``code`` and ``state``.

3. ``complete_flow(provider, state, code)`` →
   - looks up + deletes the ``oauth_states`` row (single-use).
   - exchanges ``code`` for an access token via the provider's token
     endpoint, including the PKCE code_verifier as proof.
   - fetches user info (email + provider_user_id) via the userinfo
     endpoint.
   - finds an existing ``OAuthIdentity`` row OR (on first link)
     finds-or-creates the ``User`` (matched by email) and writes the
     identity row.
   - returns the resolved ``User``.

Tests inject a mock ``http_get`` / ``http_post`` so the flow can be
exercised without real provider calls.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.oauth import OAuthIdentity, OAuthState
from app.models.user import User
from app.services import auth_service

logger = logging.getLogger(__name__)


STATE_TTL_MIN = 10
STATE_BYTES = 32
PKCE_VERIFIER_BYTES = 64


class OAuthError(RuntimeError):
    pass


class OAuthProviderUnconfiguredError(OAuthError):
    pass


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthUserInfo:
    """Normalized user info shape across providers."""

    provider_user_id: str
    email: str | None


class OAuthProvider(Protocol):
    name: str

    def authorize_url(
        self, *, redirect_uri: str, state: str, code_challenge: str
    ) -> str: ...

    def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        http_post: Callable[..., Any] | None = None,
    ) -> str: ...

    def fetch_user_info(
        self,
        access_token: str,
        *,
        http_get: Callable[..., Any] | None = None,
    ) -> OAuthUserInfo: ...


@dataclass(frozen=True)
class _GenericOAuthProvider:
    """Shared scaffolding for the two configured providers."""

    name: str
    client_id_attr: str
    client_secret_attr: str
    auth_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    scope: str
    parse_user_info: Callable[[dict], OAuthUserInfo]

    def _client_id(self) -> str:
        v = getattr(settings, self.client_id_attr, None)
        if not v:
            raise OAuthProviderUnconfiguredError(
                f"OAuth provider '{self.name}' is not configured. "
                f"Set {self.client_id_attr} and {self.client_secret_attr}."
            )
        return v

    def _client_secret(self) -> str:
        v = getattr(settings, self.client_secret_attr, None)
        if not v:
            raise OAuthProviderUnconfiguredError(
                f"OAuth provider '{self.name}' is not configured. "
                f"Set {self.client_id_attr} and {self.client_secret_attr}."
            )
        return v

    def is_configured(self) -> bool:
        try:
            self._client_id()
            self._client_secret()
            return True
        except OAuthProviderUnconfiguredError:
            return False

    def authorize_url(
        self, *, redirect_uri: str, state: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.auth_endpoint}?{urllib.parse.urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        http_post: Callable[..., Any] | None = None,
    ) -> str:
        body = {
            "grant_type": "authorization_code",
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        post = http_post or _default_http_post
        resp = post(
            self.token_endpoint,
            data=body,
            headers={"Accept": "application/json"},
        )
        payload = _safe_json(resp)
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            err = (
                payload.get("error_description")
                or payload.get("error")
                or "no access_token in response"
                if isinstance(payload, dict)
                else "no access_token in response"
            )
            raise OAuthError(f"Token exchange failed: {err}")
        return str(token)

    def fetch_user_info(
        self,
        access_token: str,
        *,
        http_get: Callable[..., Any] | None = None,
    ) -> OAuthUserInfo:
        get = http_get or _default_http_get
        resp = get(
            self.userinfo_endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        payload = _safe_json(resp)
        if not isinstance(payload, dict):
            raise OAuthError(
                f"Userinfo response from '{self.name}' was not a JSON object"
            )
        return self.parse_user_info(payload)


def _safe_json(resp: Any) -> Any:
    """Read JSON from an httpx response (or any object exposing
    ``.json()``). Returns the parsed object or an empty dict on
    parse failure so callers can branch on ``.get(...)``."""
    try:
        return resp.json()
    except Exception:
        try:
            return {"error": resp.text}
        except Exception:
            return {}


def _default_http_get(url: str, *, headers: dict | None = None) -> Any:
    with httpx.Client(timeout=10.0) as client:
        return client.get(url, headers=headers or {})


def _default_http_post(
    url: str, *, data: dict | None = None, headers: dict | None = None
) -> Any:
    with httpx.Client(timeout=10.0) as client:
        return client.post(url, data=data or {}, headers=headers or {})


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


def _google_user_info(payload: dict) -> OAuthUserInfo:
    sub = payload.get("sub") or payload.get("id")
    if not sub:
        raise OAuthError("Google userinfo missing 'sub'")
    return OAuthUserInfo(
        provider_user_id=str(sub),
        email=str(payload.get("email")) if payload.get("email") else None,
    )


def _github_user_info(payload: dict) -> OAuthUserInfo:
    uid = payload.get("id")
    if not uid:
        raise OAuthError("GitHub userinfo missing 'id'")
    # GitHub's /user only returns email if it's set to public; private
    # email requires a second call to /user/emails. Out of scope for v1
    # — we accept None and leave email-linking to the caller.
    return OAuthUserInfo(
        provider_user_id=str(uid),
        email=str(payload.get("email")) if payload.get("email") else None,
    )


_GOOGLE = _GenericOAuthProvider(
    name="google",
    client_id_attr="OAUTH_GOOGLE_CLIENT_ID",
    client_secret_attr="OAUTH_GOOGLE_CLIENT_SECRET",
    auth_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
    scope="openid email profile",
    parse_user_info=_google_user_info,
)

_GITHUB = _GenericOAuthProvider(
    name="github",
    client_id_attr="OAUTH_GITHUB_CLIENT_ID",
    client_secret_attr="OAUTH_GITHUB_CLIENT_SECRET",
    auth_endpoint="https://github.com/login/oauth/authorize",
    token_endpoint="https://github.com/login/oauth/access_token",
    userinfo_endpoint="https://api.github.com/user",
    scope="read:user user:email",
    parse_user_info=_github_user_info,
)


_PROVIDERS: dict[str, _GenericOAuthProvider] = {
    "google": _GOOGLE,
    "github": _GITHUB,
}


def get_provider(name: str) -> _GenericOAuthProvider:
    p = _PROVIDERS.get(name.lower())
    if p is None:
        raise OAuthError(f"Unknown OAuth provider '{name}'")
    return p


def configured_providers() -> list[str]:
    return [name for name, p in _PROVIDERS.items() if p.is_configured()]


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636 S256."""
    verifier = secrets.token_urlsafe(PKCE_VERIFIER_BYTES)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


def start_flow(
    db: Session, provider_name: str, redirect_uri: str
) -> str:
    """Return the provider's authorization URL after persisting an
    OAuthState row carrying the CSRF state + PKCE verifier."""
    provider = get_provider(provider_name)
    if not provider.is_configured():
        raise OAuthProviderUnconfiguredError(
            f"OAuth provider '{provider_name}' is not configured."
        )

    state = secrets.token_urlsafe(STATE_BYTES)
    code_verifier, code_challenge = _generate_pkce_pair()

    row = OAuthState(
        state=state,
        provider=provider.name,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MIN),
    )
    db.add(row)
    db.commit()

    return provider.authorize_url(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )


def complete_flow(
    db: Session,
    provider_name: str,
    state: str,
    code: str,
    *,
    http_post: Callable[..., Any] | None = None,
    http_get: Callable[..., Any] | None = None,
) -> User:
    """Validate state, exchange code for token, fetch user info, link
    or create the User row, return it."""
    state_row = (
        db.query(OAuthState).filter(OAuthState.state == state).first()
    )
    if state_row is None:
        raise OAuthError("Unknown or already-consumed state")
    expires_at = state_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(state_row)
        db.commit()
        raise OAuthError("State expired; please retry the OAuth flow")
    if state_row.provider != provider_name:
        raise OAuthError("State / provider mismatch")

    provider = get_provider(provider_name)
    access_token = provider.exchange_code(
        code=code,
        redirect_uri=state_row.redirect_uri,
        code_verifier=state_row.code_verifier,
        http_post=http_post,
    )
    user_info = provider.fetch_user_info(access_token, http_get=http_get)

    # Single-use state.
    db.delete(state_row)
    db.commit()

    return _link_or_create_user(db, provider.name, user_info)


def _link_or_create_user(
    db: Session, provider_name: str, info: OAuthUserInfo
) -> User:
    """Find existing OAuth identity or (on first OAuth login):
    - if the email is already a Pratidhvani user, link the identity to
      that user (so users can switch from password to OAuth without
      losing data);
    - otherwise create a fresh User with a random password (the user
      can later set a real password via reset).
    """
    existing = (
        db.query(OAuthIdentity)
        .filter(
            OAuthIdentity.provider == provider_name,
            OAuthIdentity.provider_user_id == info.provider_user_id,
        )
        .first()
    )
    if existing is not None:
        user = auth_service.get_user_by_id(db, existing.user_id)
        if user is None:
            # Stale identity → user was deleted. Recreate.
            db.delete(existing)
            db.commit()
        else:
            return user

    if info.email is None:
        raise OAuthError(
            f"Provider '{provider_name}' did not return an email address. "
            f"Cannot link or create the account without one."
        )

    user = auth_service.get_user_by_email(db, info.email)
    if user is None:
        # First OAuth login + no existing email match → create User.
        user = auth_service.create_user(
            db,
            email=info.email,
            password=secrets.token_urlsafe(32),  # random; user resets later
        )

    identity = OAuthIdentity(
        user_id=user.id,
        provider=provider_name,
        provider_user_id=info.provider_user_id,
        provider_email=info.email,
    )
    db.add(identity)
    db.commit()
    return user


def _reap_expired_states(db: Session) -> int:
    """Delete expired OAuthState rows. Idempotent. Best-effort cleanup
    that callers can run periodically; returns the number deleted."""
    rows = (
        db.query(OAuthState)
        .filter(OAuthState.expires_at <= datetime.now(timezone.utc))
        .all()
    )
    for r in rows:
        db.delete(r)
    if rows:
        db.commit()
    return len(rows)

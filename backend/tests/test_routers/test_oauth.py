"""Tests for T-5.4.5 — OAuth (Google + GitHub PKCE)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.models.oauth import OAuthIdentity, OAuthState
from app.models.user import User
from app.services import auth_service, oauth_service


@pytest.fixture(autouse=True)
def _configure_providers(monkeypatch):
    """Configure both Google + GitHub for the test suite."""
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "github-secret")


# ---------------------------------------------------------------------------
# /providers
# ---------------------------------------------------------------------------


def test_providers_lists_configured(unauthenticated_client, db):
    r = unauthenticated_client.get("/api/v1/auth/oauth/providers")
    assert r.status_code == 200
    body = r.json()
    assert "google" in body["providers"]
    assert "github" in body["providers"]


def test_providers_omits_unconfigured(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", None)
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", None)
    r = unauthenticated_client.get("/api/v1/auth/oauth/providers")
    assert "google" in r.json()["providers"]
    assert "github" not in r.json()["providers"]


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


def test_start_returns_authorize_url_and_persists_state(unauthenticated_client, db):
    r = unauthenticated_client.get(
        "/api/v1/auth/oauth/google/start"
        "?redirect_uri=https://app.example.com/oauth/callback"
    )
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=google-client-id" in url
    assert "code_challenge_method=S256" in url
    assert "state=" in url

    rows = db.query(OAuthState).all()
    assert len(rows) == 1
    assert rows[0].provider == "google"
    assert len(rows[0].code_verifier) >= 43  # base64-ish
    assert rows[0].redirect_uri == "https://app.example.com/oauth/callback"


def test_start_503_when_provider_unconfigured(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", None)
    r = unauthenticated_client.get(
        "/api/v1/auth/oauth/google/start"
        "?redirect_uri=https://app.example.com/oauth/callback"
    )
    assert r.status_code == 503


def test_start_400_for_unknown_provider(unauthenticated_client):
    r = unauthenticated_client.get(
        "/api/v1/auth/oauth/yahoo/start?redirect_uri=https://x.example.com"
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# /callback (mocked provider responses)
# ---------------------------------------------------------------------------


def _start_and_grab_state(client, db, provider: str = "google") -> str:
    client.get(
        f"/api/v1/auth/oauth/{provider}/start"
        f"?redirect_uri=https://app.example.com/oauth/callback"
    )
    return db.query(OAuthState).first().state


def _mock_response(payload: dict) -> MagicMock:
    """Build a fake httpx-style response that returns ``payload`` from
    ``.json()``."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.text = ""
    return resp


def test_callback_creates_user_and_identity_on_first_login(
    unauthenticated_client, db, monkeypatch
):
    state = _start_and_grab_state(unauthenticated_client, db, "google")

    # Stub the token exchange + userinfo HTTP calls.
    fake_post = MagicMock(return_value=_mock_response({"access_token": "oauth-tok"}))
    fake_get = MagicMock(
        return_value=_mock_response(
            {"sub": "google-user-1234", "email": "newuser@example.com"}
        )
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", fake_post)
    monkeypatch.setattr(oauth_service, "_default_http_get", fake_get)

    r = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=xyz&state={state}"
    )
    assert r.status_code == 200
    assert "access_token" in r.json()

    # User row was created.
    user = auth_service.get_user_by_email(db, "newuser@example.com")
    assert user is not None

    # Identity row links them.
    identities = (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.user_id == user.id)
        .all()
    )
    assert len(identities) == 1
    assert identities[0].provider == "google"
    assert identities[0].provider_user_id == "google-user-1234"

    # State row consumed.
    assert db.query(OAuthState).count() == 0


def test_callback_links_identity_to_existing_email_user(
    unauthenticated_client, db, monkeypatch
):
    """If a Pratidhvani user with the OAuth-reported email already
    exists (e.g. originally registered with password), the OAuth login
    links the identity to THAT user instead of creating a duplicate."""
    existing = auth_service.create_user(
        db, email="existing@example.com", password="pw" * 6
    )
    state = _start_and_grab_state(unauthenticated_client, db, "google")

    fake_post = MagicMock(return_value=_mock_response({"access_token": "tok"}))
    fake_get = MagicMock(
        return_value=_mock_response(
            {"sub": "google-9999", "email": "existing@example.com"}
        )
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", fake_post)
    monkeypatch.setattr(oauth_service, "_default_http_get", fake_get)

    r = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=xyz&state={state}"
    )
    assert r.status_code == 200

    # No duplicate user.
    users = db.query(User).filter(User.email == "existing@example.com").all()
    assert len(users) == 1
    assert users[0].id == existing.id

    # Identity links to the existing user.
    identity = db.query(OAuthIdentity).first()
    assert identity.user_id == existing.id


def test_callback_returns_existing_user_on_repeat_oauth_login(
    unauthenticated_client, db, monkeypatch
):
    """Second OAuth login: identity already linked → just re-authenticate."""
    # First flow.
    state1 = _start_and_grab_state(unauthenticated_client, db, "google")
    fake_post = MagicMock(return_value=_mock_response({"access_token": "tok1"}))
    fake_get = MagicMock(
        return_value=_mock_response(
            {"sub": "g-recurring", "email": "rec@example.com"}
        )
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", fake_post)
    monkeypatch.setattr(oauth_service, "_default_http_get", fake_get)
    unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=c1&state={state1}"
    )

    user = auth_service.get_user_by_email(db, "rec@example.com")
    assert user is not None
    assert db.query(OAuthIdentity).count() == 1

    # Second flow.
    state2 = _start_and_grab_state(unauthenticated_client, db, "google")
    r = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=c2&state={state2}"
    )
    assert r.status_code == 200
    # Still exactly one identity row (not duplicated).
    assert db.query(OAuthIdentity).count() == 1


def test_callback_401_for_unknown_state(unauthenticated_client, db):
    r = unauthenticated_client.get(
        "/api/v1/auth/oauth/google/callback?code=xyz&state=fakeofakeofake"
    )
    assert r.status_code == 401


def test_callback_401_for_expired_state(unauthenticated_client, db, monkeypatch):
    state = _start_and_grab_state(unauthenticated_client, db, "google")
    # Force the row to be expired.
    row = db.query(OAuthState).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    r = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=xyz&state={state}"
    )
    assert r.status_code == 401


def test_callback_401_when_token_exchange_fails(
    unauthenticated_client, db, monkeypatch
):
    state = _start_and_grab_state(unauthenticated_client, db, "google")
    fake_post = MagicMock(
        return_value=_mock_response(
            {"error": "invalid_grant", "error_description": "code expired"}
        )
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", fake_post)

    r = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=xyz&state={state}"
    )
    assert r.status_code == 401


def test_callback_401_when_userinfo_missing_email(
    unauthenticated_client, db, monkeypatch
):
    """A provider that doesn't return an email can't be linked unless
    the identity already exists. First-time login must 401 in this case."""
    state = _start_and_grab_state(unauthenticated_client, db, "github")
    fake_post = MagicMock(return_value=_mock_response({"access_token": "tok"}))
    fake_get = MagicMock(
        return_value=_mock_response({"id": 555, "email": None})
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", fake_post)
    monkeypatch.setattr(oauth_service, "_default_http_get", fake_get)

    r = unauthenticated_client.get(
        f"/api/v1/auth/oauth/github/callback?code=xyz&state={state}"
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# State single-use semantics
# ---------------------------------------------------------------------------


def test_state_is_single_use(unauthenticated_client, db, monkeypatch):
    state = _start_and_grab_state(unauthenticated_client, db, "google")
    fake_post = MagicMock(return_value=_mock_response({"access_token": "tok"}))
    fake_get = MagicMock(
        return_value=_mock_response(
            {"sub": "g-once", "email": "once@example.com"}
        )
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", fake_post)
    monkeypatch.setattr(oauth_service, "_default_http_get", fake_get)

    r1 = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=c&state={state}"
    )
    assert r1.status_code == 200

    # Second call with the same state must fail (state row was deleted).
    r2 = unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=c&state={state}"
    )
    assert r2.status_code == 401


# ---------------------------------------------------------------------------
# PKCE wiring
# ---------------------------------------------------------------------------


def test_token_exchange_includes_code_verifier(
    unauthenticated_client, db, monkeypatch
):
    """The persisted code_verifier must be sent in the token-exchange POST
    body so the provider can validate the PKCE binding."""
    state = _start_and_grab_state(unauthenticated_client, db, "google")
    persisted_verifier = db.query(OAuthState).first().code_verifier

    captured: dict = {}

    def capturing_post(url, *, data, headers):
        captured["url"] = url
        captured["data"] = data
        return _mock_response({"access_token": "tok"})

    fake_get = MagicMock(
        return_value=_mock_response(
            {"sub": "g-pkce", "email": "pkce@example.com"}
        )
    )
    monkeypatch.setattr(oauth_service, "_default_http_post", capturing_post)
    monkeypatch.setattr(oauth_service, "_default_http_get", fake_get)

    unauthenticated_client.get(
        f"/api/v1/auth/oauth/google/callback?code=c&state={state}"
    )
    assert captured["data"]["code_verifier"] == persisted_verifier
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["url"] == "https://oauth2.googleapis.com/token"

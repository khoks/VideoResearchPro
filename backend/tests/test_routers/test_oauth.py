"""Tests for T-5.4.5 — OAuth (Google + GitHub PKCE), and T-5.4.10 — a first
sign-in needs an email the provider verified."""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.oauth import OAuthIdentity, OAuthState
from app.models.user import User
from app.services import auth_service, oauth_service
from app.utils import app_origins


@pytest.fixture(autouse=True)
def _configure_providers(monkeypatch):
    """Configure both Google + GitHub for the test suite."""
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "github-secret")
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://localhost:5173")
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "https://app.example.com")


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
# T-4.11.2.4: the redirect allow-list
#
# Mutation checks (each failed the named test when this shipped): dropping the
# check from `start_flow`, comparing without the port, or dropping the
# credentials or the backslash refusal (`test_start_refuses_an_address_off_the_list`);
# leaving APP_BASE_URL out of the list (`test_a_dev_install_keeps_working_untouched`).
# ---------------------------------------------------------------------------


DEV = "http://localhost:5173/login/oauth/google/callback"


def _start(client, redirect_uri: str, provider: str = "google"):
    return client.get(
        f"/api/v1/auth/oauth/{provider}/start", params={"redirect_uri": redirect_uri}
    )


def _sent_to_provider(response) -> str:
    query = urllib.parse.urlparse(response.json()["authorize_url"]).query
    return urllib.parse.parse_qs(query)["redirect_uri"][0]


def test_a_dev_install_keeps_working_untouched(unauthenticated_client, db, monkeypatch):
    """No setting at all: APP_BASE_URL's default names where Vite serves."""
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "")
    assert type(settings).model_fields["APP_BASE_URL"].default == "http://localhost:5173"

    r = _start(unauthenticated_client, DEV)

    assert r.status_code == 200
    assert _sent_to_provider(r) == DEV
    assert db.query(OAuthState).one().redirect_uri == DEV


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://evil.example/login/oauth/google/callback",
        # Same host, another scheme or port.
        "https://localhost:5173/login/oauth/google/callback",
        "http://localhost:5174/login/oauth/google/callback",
        "http://localhost/login/oauth/google/callback",
        "http://app.example.com/oauth/callback",
        # Look-alikes that start with an allowed origin.
        "http://localhost:5173.evil.example/cb",
        "https://app.example.com.evil.example/cb",
        "http://localhost:5173@evil.example/cb",
        "https://app.example.com:443@evil.example/cb",
        # Credentials before an allowed host. Nothing needs them.
        "http://user:secret@localhost:5173/cb",
        "http://evil.example@localhost:5173/cb",
        # Two parsers, two hosts. A browser turns the backslash into a slash.
        "http://evil.example\\@localhost:5173/cb",
        "http://localhost:5173\\.evil.example/cb",
        # urlsplit quietly drops these; a provider might not.
        "http://local\thost:5173/cb",
        "http://localhost:5173/cb\nX-Injected: 1",
        " http://localhost:5173/cb",
        # Not web addresses.
        "javascript:alert(1)//localhost:5173/",
        "data:text/html,http://localhost:5173/",
        "file:///localhost:5173/etc/passwd",
        "//localhost:5173/cb",
        "/login/oauth/google/callback",
        # Unparseable.
        "http://localhost:notaport/cb",
        "http://[::1/cb",
    ],
)
def test_start_refuses_an_address_off_the_list(unauthenticated_client, db, redirect_uri):
    r = _start(unauthenticated_client, redirect_uri)
    assert r.status_code == 400, redirect_uri
    assert "OAUTH_ALLOWED_REDIRECT_ORIGINS" in r.json()["detail"]
    assert "authorize_url" not in r.json()
    assert db.query(OAuthState).count() == 0, "nothing is stored"


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://app.example.com/oauth/callback",
        "https://app.example.com:443/oauth/callback",  # the default port, spelt out
        "https://APP.example.com/oauth/callback",
        "HTTPS://app.example.com/oauth/callback",
        "https://app.example.com/oauth/callback?from=login",
        DEV,
    ],
)
def test_the_provider_gets_exactly_what_was_sent(unauthenticated_client, db, redirect_uri):
    r = _start(unauthenticated_client, redirect_uri)
    assert r.status_code == 200, redirect_uri
    assert _sent_to_provider(r) == redirect_uri
    assert db.query(OAuthState).one().redirect_uri == redirect_uri


def test_127_0_0_1_is_not_localhost(unauthenticated_client, db):
    """Nothing else here treats them alike: CORS lists localhost alone, so a
    page opened at 127.0.0.1:5173 cannot call the API on the default config,
    and a provider registers each as its own callback."""
    assert _start(unauthenticated_client, "http://127.0.0.1:5173/cb").status_code == 400


def test_127_0_0_1_works_once_named(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "http://127.0.0.1:5173")
    assert _start(unauthenticated_client, "http://127.0.0.1:5173/cb").status_code == 200


def test_app_base_url_counts_by_its_origin(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "")
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://research.example.org/app/")
    assert _start(unauthenticated_client, "https://research.example.org/elsewhere").status_code == 200
    assert _start(unauthenticated_client, "http://research.example.org/app/").status_code == 400


def test_a_list_of_origins_reads_loosely(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(
        settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", " https://one.example , https://two.example:8443/ ,, "
    )
    assert _start(unauthenticated_client, "https://one.example/cb").status_code == 200
    assert _start(unauthenticated_client, "https://two.example:8443/cb").status_code == 200
    assert _start(unauthenticated_client, "https://two.example/cb").status_code == 400


def test_a_bad_entry_is_logged_and_only_ever_allows_less(unauthenticated_client, monkeypatch):
    # The list and its warnings live in app_origins since CORS reads it too
    # (T-4.11.3.3); the parse is cached by value, so start from an empty cache.
    log = MagicMock()
    monkeypatch.setattr(app_origins, "logger", log)
    app_origins._parse.cache_clear()
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "not an origin, https://one.example")
    assert _start(unauthenticated_client, "https://one.example/cb").status_code == 200
    log.warning.assert_called_once()


def test_an_unconfigured_provider_still_answers_503_first(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", None)
    assert _start(unauthenticated_client, "https://evil.example/cb").status_code == 503


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
            {"sub": "google-user-1234", "email": "newuser@example.com", "email_verified": True}
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
            {"sub": "google-9999", "email": "existing@example.com", "email_verified": True}
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
            {"sub": "g-recurring", "email": "rec@example.com", "email_verified": True}
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
            {"sub": "g-once", "email": "once@example.com", "email_verified": True}
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
            {"sub": "g-pkce", "email": "pkce@example.com", "email_verified": True}
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


# ---------------------------------------------------------------------------
# Verified email (T-5.4.10, amends D-042)
#
# A first OAuth sign-in links an existing account by email, or creates one,
# only when the provider verified the address. Google: the OIDC
# ``email_verified`` claim. GitHub: the primary address in /user/emails and
# its ``verified`` flag; /user's public email is never trusted. Unverified is
# refused with 403 and one message whether or not an account exists, and
# nothing is linked or created. Each refusal test below fails if the gate in
# ``oauth_service._link_or_create_user`` is removed. A /user/emails lookup
# that fails is not "unverified" but unknown: the generic, retryable 401.
# ---------------------------------------------------------------------------

GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"


def _routed_get(responses: dict[str, object]) -> MagicMock:
    """A fake GET answering each URL with its own payload, recording calls."""

    def get(url, *, headers=None):
        return _mock_response(responses[url])

    return MagicMock(side_effect=get)


def _sign_in(client, db, monkeypatch, provider: str, get: MagicMock):
    state = _start_and_grab_state(client, db, provider)
    monkeypatch.setattr(
        oauth_service, "_default_http_post",
        MagicMock(return_value=_mock_response({"access_token": "provider-tok"})),
    )
    monkeypatch.setattr(oauth_service, "_default_http_get", get)
    return client.get(f"/api/v1/auth/oauth/{provider}/callback?code=c&state={state}")


def _refusal_audited(db, provider: str) -> bool:
    rows = db.query(AuditLog).filter(AuditLog.event == "login_failure").all()
    return any(
        json.loads(r.metadata_json or "{}") == {"reason": "oauth_email_unverified", "provider": provider}
        for r in rows
    )


def test_google_unverified_email_with_an_existing_account_is_refused(
    unauthenticated_client, db, monkeypatch
):
    existing = auth_service.create_user(db, email="victim@example.com", password="pw" * 6)
    get = MagicMock(return_value=_mock_response(
        {"sub": "g-attacker", "email": "victim@example.com", "email_verified": False}
    ))
    r = _sign_in(unauthenticated_client, db, monkeypatch, "google", get)

    assert r.status_code == 403
    assert r.json()["detail"] == oauth_service.unverified_email_message("google")
    assert "sign in with your email and password" in r.json()["detail"]
    assert db.query(OAuthIdentity).count() == 0, "the existing account gained no sign-in"
    assert db.query(User).count() == 1
    assert auth_service.get_user_by_email(db, "victim@example.com").id == existing.id
    assert _refusal_audited(db, "google")


def test_google_without_the_email_verified_claim_is_refused(
    unauthenticated_client, db, monkeypatch
):
    """A missing claim is not a verified address."""
    auth_service.create_user(db, email="victim@example.com", password="pw" * 6)
    get = MagicMock(return_value=_mock_response({"sub": "g-x", "email": "victim@example.com"}))
    r = _sign_in(unauthenticated_client, db, monkeypatch, "google", get)
    assert r.status_code == 403
    assert db.query(OAuthIdentity).count() == 0


def test_google_unverified_new_address_creates_nothing_and_reads_the_same(
    unauthenticated_client, db, monkeypatch
):
    """No account exists: still refused, with the very same message, so the
    refusal does not tell anyone which addresses are registered."""
    get = MagicMock(return_value=_mock_response(
        {"sub": "g-new", "email": "nobody@example.com", "email_verified": False}
    ))
    r = _sign_in(unauthenticated_client, db, monkeypatch, "google", get)
    assert r.status_code == 403
    assert r.json()["detail"] == oauth_service.unverified_email_message("google")
    assert auth_service.get_user_by_email(db, "nobody@example.com") is None
    assert db.query(OAuthIdentity).count() == 0


def test_github_verified_primary_links_the_existing_account(
    unauthenticated_client, db, monkeypatch
):
    """A private profile email (/user says null) still signs in: the primary
    verified address comes from /user/emails."""
    existing = auth_service.create_user(db, email="dev@example.com", password="pw" * 6)
    get = _routed_get({
        GITHUB_USER: {"id": 7001, "email": None},
        GITHUB_EMAILS: [
            {"email": "old@example.com", "primary": False, "verified": False, "visibility": None},
            {"email": "dev@example.com", "primary": True, "verified": True, "visibility": "private"},
        ],
    })
    r = _sign_in(unauthenticated_client, db, monkeypatch, "github", get)

    assert r.status_code == 200, r.text
    identity = db.query(OAuthIdentity).one()
    assert identity.user_id == existing.id
    assert identity.provider_user_id == "7001"
    assert identity.provider_email == "dev@example.com"
    assert db.query(User).count() == 1
    emails_calls = [c for c in get.call_args_list if c.args[0] == GITHUB_EMAILS]
    assert len(emails_calls) == 1
    assert emails_calls[0].kwargs["headers"]["Authorization"] == "Bearer provider-tok"


def test_github_unverified_public_email_is_refused(
    unauthenticated_client, db, monkeypatch
):
    auth_service.create_user(db, email="victim@example.com", password="pw" * 6)
    get = _routed_get({
        GITHUB_USER: {"id": 7002, "email": "victim@example.com"},
        GITHUB_EMAILS: [
            {"email": "victim@example.com", "primary": True, "verified": False, "visibility": "public"},
        ],
    })
    r = _sign_in(unauthenticated_client, db, monkeypatch, "github", get)

    assert r.status_code == 403
    assert r.json()["detail"] == oauth_service.unverified_email_message("github")
    assert "GitHub has not verified" in r.json()["detail"]
    assert db.query(OAuthIdentity).count() == 0
    assert db.query(User).count() == 1
    assert _refusal_audited(db, "github")


def _audited(db, reason: str, provider: str) -> bool:
    rows = db.query(AuditLog).filter(AuditLog.event == "login_failure").all()
    return any(
        json.loads(r.metadata_json or "{}") == {"reason": reason, "provider": provider}
        for r in rows
    )


def _github_get_with_failing_emails(failure: str, profile_email: str | None) -> MagicMock:
    """/user answers; /user/emails fails the way ``failure`` names."""

    def get(url, *, headers=None):
        if url == GITHUB_USER:
            return _mock_response({"id": 7003, "email": profile_email})
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out")
        resp = MagicMock()
        resp.text = ""
        if failure == "bad_gateway":
            resp.json.side_effect = ValueError("not JSON")
            resp.text = "<html><body>502 Bad Gateway</body></html>"
        elif failure == "rate_limited":
            resp.json.return_value = {
                "message": "API rate limit exceeded for user ID 7003.",
                "documentation_url": "https://docs.github.com/rest/overview/rate-limits-for-the-rest-api",
            }
        elif failure == "not_found":  # as for a token without ``user:email``
            resp.json.return_value = {"message": "Not Found", "documentation_url": "https://docs.github.com"}
        elif failure == "no_primary":
            resp.json.return_value = []
        return resp

    return MagicMock(side_effect=get)


@pytest.mark.parametrize("profile_email", ["victim@example.com", None], ids=["public-email", "private-email"])
@pytest.mark.parametrize("failure", ["rate_limited", "bad_gateway", "timeout", "not_found", "no_primary"])
def test_github_failed_email_lookup_is_the_generic_retryable_failure(
    unauthenticated_client, db, monkeypatch, failure, profile_email
):
    """A failed /user/emails says nothing about verification (review of #384).
    A first sign-in gets the generic 401, audited as ``oauth_failure``, not
    the 403 telling a user whose address may well be verified to go and
    verify it, and the same whether or not the profile email is public. The
    public email alone still links or creates nothing."""
    auth_service.create_user(db, email="victim@example.com", password="pw" * 6)
    get = _github_get_with_failing_emails(failure, profile_email)
    r = _sign_in(unauthenticated_client, db, monkeypatch, "github", get)

    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "OAuth authentication failed"
    assert db.query(OAuthIdentity).count() == 0
    assert db.query(User).count() == 1
    assert _audited(db, "oauth_failure", "github")
    assert not _refusal_audited(db, "github"), "an outage is not recorded as a policy refusal"


def test_a_new_link_records_when_the_provider_vouched(unauthenticated_client, db, monkeypatch):
    """D-042 option (B'): the identity row keeps the verification, so links
    made under T-5.4.10 are told apart from older ones (NULL)."""
    auth_service.create_user(db, email="dev@example.com", password="pw" * 6)
    before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    get = _routed_get({
        GITHUB_USER: {"id": 7010, "email": None},
        GITHUB_EMAILS: [{"email": "dev@example.com", "primary": True, "verified": True}],
    })
    assert _sign_in(unauthenticated_client, db, monkeypatch, "github", get).status_code == 200

    verified_at = db.query(OAuthIdentity).one().email_verified_at
    assert verified_at is not None
    assert verified_at.replace(tzinfo=None) >= before


def test_github_uses_the_primary_address_not_the_public_one(
    unauthenticated_client, db, monkeypatch
):
    existing = auth_service.create_user(db, email="public@example.com", password="pw" * 6)
    get = _routed_get({
        GITHUB_USER: {"id": 7004, "email": "public@example.com"},
        GITHUB_EMAILS: [
            {"email": "public@example.com", "primary": False, "verified": True, "visibility": "public"},
            {"email": "primary@example.com", "primary": True, "verified": True, "visibility": None},
        ],
    })
    r = _sign_in(unauthenticated_client, db, monkeypatch, "github", get)
    assert r.status_code == 200, r.text
    created = auth_service.get_user_by_email(db, "primary@example.com")
    assert created is not None and created.id != existing.id
    assert db.query(OAuthIdentity).one().user_id == created.id


def test_github_new_verified_user_is_created(unauthenticated_client, db, monkeypatch):
    get = _routed_get({
        GITHUB_USER: {"id": 7005, "email": None},
        GITHUB_EMAILS: [{"email": "Fresh@Example.com", "primary": True, "verified": True}],
    })
    r = _sign_in(unauthenticated_client, db, monkeypatch, "github", get)
    assert r.status_code == 200, r.text
    user = auth_service.get_user_by_email(db, "fresh@example.com")
    assert user is not None
    identity = db.query(OAuthIdentity).one()
    assert identity.user_id == user.id and identity.provider == "github"


def test_a_linked_identity_signs_in_whatever_the_email_says(
    unauthenticated_client, db, monkeypatch
):
    """The gate is for a first link. A returning user is found by provider id,
    so a later failed /user/emails lookup does not lock them out."""
    first = _routed_get({
        GITHUB_USER: {"id": 7006, "email": None},
        GITHUB_EMAILS: [{"email": "back@example.com", "primary": True, "verified": True}],
    })
    assert _sign_in(unauthenticated_client, db, monkeypatch, "github", first).status_code == 200
    user = auth_service.get_user_by_email(db, "back@example.com")

    again = _routed_get({
        GITHUB_USER: {"id": 7006, "email": None},
        GITHUB_EMAILS: {"message": "Bad credentials"},
    })
    r = _sign_in(unauthenticated_client, db, monkeypatch, "github", again)
    assert r.status_code == 200, r.text
    me = unauthenticated_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.json()["id"] == user.id
    assert db.query(OAuthIdentity).count() == 1


def test_github_authorize_url_requests_the_user_email_scope(unauthenticated_client, db):
    """/user/emails answers only with ``user:email``; without it every GitHub
    first sign-in would be refused."""
    r = unauthenticated_client.get(
        "/api/v1/auth/oauth/github/start?redirect_uri=https://app.example.com/oauth/callback"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["authorize_url"]).query)
    assert "user:email" in query["scope"][0].split()

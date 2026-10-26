"""T-5.2.8 / D-111 — the tier switch and the restart are operator-only.

Checked at the production callers: ``PUT /auth/me/tier``, ``POST
/admin/restart`` and ``GET /auth/me`` (which tells the Subscription page
whether to offer the switch); since the review, also ``POST /auth/register``,
the OAuth callback and the app's startup, which keep a listed address from
being claimed by whoever registers it first. The rule itself is in
``test_services/test_auth_service.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.oauth import OAuthIdentity, OAuthState
from app.services import auth_service, oauth_service


@pytest.fixture(autouse=True)
def no_allow_list(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")


@pytest.fixture
def member(db, test_user):
    """A second account, registered after ``test_user`` (the operator by
    default, as the earliest account)."""
    test_user.created_at = datetime(2026, 5, 1)
    user = auth_service.create_user(db, email="member@example.com", password="pw" * 6)
    user.created_at = datetime(2026, 5, 1) + timedelta(days=1)
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def no_restart(monkeypatch):
    """Never let a test restart this machine's services: the trampoline
    thread is replaced, and the host reads as Windows so the operator path
    reaches it on any platform."""
    thread = MagicMock()
    monkeypatch.setattr("app.routers.admin.threading.Thread", thread)
    monkeypatch.setattr("app.routers.admin.sys", SimpleNamespace(platform="win32"))
    return thread


# ------------------------------------------------------------------ GET /auth/me

def test_me_says_whether_the_caller_is_the_operator(client, member):
    assert client.get("/api/v1/auth/me").json()["is_operator"] is True
    _, headers = member
    assert client.get("/api/v1/auth/me", headers=headers).json()["is_operator"] is False


def test_me_follows_the_allow_list(client, member, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "MEMBER@example.com")
    _, headers = member
    assert client.get("/api/v1/auth/me", headers=headers).json()["is_operator"] is True
    assert client.get("/api/v1/auth/me").json()["is_operator"] is False


# ------------------------------------------------------------------ PUT /auth/me/tier

def test_a_member_cannot_switch_their_tier(client, db, member):
    user, headers = member
    r = client.put("/api/v1/auth/me/tier", json={"tier": "studio"}, headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "Only this install's operator can do this."
    db.refresh(user)
    assert user.tier == "free", "nothing changed"
    assert db.query(AuditLog).filter_by(user_id=user.id, event="tier_changed").count() == 0


def test_the_operator_can_switch(client, db, test_user, member):
    r = client.put("/api/v1/auth/me/tier", json={"tier": "pro"})
    assert r.status_code == 200 and r.json()["tier"] == "pro"
    db.refresh(test_user)
    assert test_user.tier == "pro"


def test_a_listed_operator_can_switch_and_the_first_account_cannot(client, db, test_user, member, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "member@example.com")
    user, headers = member
    assert client.put("/api/v1/auth/me/tier", json={"tier": "studio"}, headers=headers).status_code == 200
    db.refresh(user)
    assert user.tier == "studio"
    assert client.put("/api/v1/auth/me/tier", json={"tier": "studio"}).status_code == 403


def test_the_tier_switch_still_needs_a_sign_in(unauthenticated_client):
    assert unauthenticated_client.put("/api/v1/auth/me/tier", json={"tier": "pro"}).status_code == 401


# ------------------------------------------------------------------ POST /admin/restart

def test_a_member_cannot_restart_the_services(client, member, no_restart):
    _, headers = member
    r = client.post("/api/v1/admin/restart", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "Only this install's operator can do this."
    no_restart.assert_not_called()


def test_the_operator_can_restart(client, member, no_restart):
    r = client.post("/api/v1/admin/restart", params={"skip_frontend": True, "delay": 3})
    assert r.status_code == 202, r.text
    assert r.json()["skip_frontend"] is True
    no_restart.assert_called_once()
    assert no_restart.call_args.kwargs["args"] == (True, 3)
    no_restart.return_value.start.assert_called_once()


def test_a_listed_operator_can_restart_and_the_first_account_cannot(client, member, monkeypatch, no_restart):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "member@example.com")
    _, headers = member
    assert client.post("/api/v1/admin/restart").status_code == 403
    assert client.post("/api/v1/admin/restart", headers=headers).status_code == 202


def test_the_restart_still_needs_a_sign_in(unauthenticated_client, no_restart):
    assert unauthenticated_client.post("/api/v1/admin/restart").status_code == 401
    no_restart.assert_not_called()


# ------------------------------------------------------------------ claiming a listed address
#
# D-111 review: a listed address makes whoever holds the account an operator,
# and POST /auth/register verifies no email. An address listed before anyone
# registered it must not be open to sign-up, or anyone could claim it.

def _oauth_configured(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", "github-client-id")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "github-secret")


def _oauth_sign_in(client, db, monkeypatch, provider: str, userinfo: dict, emails: list | None = None):
    """Run the OAuth callback with the provider's HTTP calls stubbed.

    ``emails`` is GitHub's /user/emails answer; without it that lookup gets
    an error object, as GitHub returns when it refuses.
    """
    client.get(f"/api/v1/auth/oauth/{provider}/start?redirect_uri=https://app.example.com/oauth/callback")
    state = db.query(OAuthState).first().state
    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "provider-token"}

    def get(url, *, headers=None):
        resp = MagicMock()
        if url.endswith("/user/emails"):
            resp.json.return_value = emails if emails is not None else {"message": "Not Found"}
        else:
            resp.json.return_value = userinfo
        return resp

    monkeypatch.setattr(oauth_service, "_default_http_post", MagicMock(return_value=token_resp))
    monkeypatch.setattr(oauth_service, "_default_http_get", get)
    return client.get(f"/api/v1/auth/oauth/{provider}/callback?code=c&state={state}")


def test_registering_a_listed_address_is_refused(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = unauthenticated_client.post(
        "/api/v1/auth/register", json={"email": "OPS@company.com", "password": "attacker-pw"}
    )
    assert r.status_code == 403
    assert r.json()["detail"] == auth_service.REGISTER_OPERATOR_EMAIL_REFUSED
    assert "Register the account before listing it" in r.json()["detail"]
    assert auth_service.get_user_by_email(db, "ops@company.com") is None, "no account was created"


def test_an_unlisted_address_still_registers_while_a_list_is_set(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = unauthenticated_client.post(
        "/api/v1/auth/register", json={"email": "someone@company.com", "password": "pw" * 6}
    )
    assert r.status_code == 201
    assert not auth_service.is_operator(db, auth_service.get_user_by_email(db, "someone@company.com"))


def test_an_account_registered_before_it_was_listed_is_the_operator(client, test_user, member, monkeypatch, no_restart):
    """The documented order: register, then list. Listing an existing
    account makes it the operator, and registering it again stays a 409."""
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "test@example.com")
    assert client.get("/api/v1/auth/me").json()["is_operator"] is True
    assert client.put("/api/v1/auth/me/tier", json={"tier": "pro"}).status_code == 200
    assert client.post("/api/v1/admin/restart").status_code == 202
    again = client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "pw" * 6})
    assert again.status_code == 409


def test_oauth_with_a_verified_listed_address_creates_the_operator(unauthenticated_client, db, monkeypatch):
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = _oauth_sign_in(
        unauthenticated_client, db, monkeypatch, "google",
        {"sub": "g-ops", "email": "ops@company.com", "email_verified": True},
    )
    assert r.status_code == 200, r.text
    me = unauthenticated_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.json()["email"] == "ops@company.com"
    assert me.json()["is_operator"] is True


def test_oauth_with_a_listed_github_verified_primary_creates_the_operator(unauthenticated_client, db, monkeypatch):
    """GitHub's verification comes from /user/emails (T-5.4.10): the primary
    address, verified."""
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = _oauth_sign_in(
        unauthenticated_client, db, monkeypatch, "github", {"id": 4242, "email": None},
        emails=[{"email": "ops@company.com", "primary": True, "verified": True}],
    )
    assert r.status_code == 200, r.text
    assert auth_service.is_operator(db, auth_service.get_user_by_email(db, "ops@company.com"))


def test_oauth_with_a_listed_github_public_email_alone_creates_nothing(unauthenticated_client, db, monkeypatch):
    """Before T-5.4.10 /user's public email counted as verified; now only
    /user/emails can vouch for it."""
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = _oauth_sign_in(unauthenticated_client, db, monkeypatch, "github", {"id": 4242, "email": "ops@company.com"})
    assert r.status_code == 403
    assert auth_service.get_user_by_email(db, "ops@company.com") is None


def test_oauth_with_an_unverified_listed_address_creates_nothing(unauthenticated_client, db, monkeypatch):
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = _oauth_sign_in(
        unauthenticated_client, db, monkeypatch, "google",
        {"sub": "g-attacker", "email": "ops@company.com", "email_verified": False},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == oauth_service.unverified_email_message("google")
    assert auth_service.get_user_by_email(db, "ops@company.com") is None
    assert db.query(OAuthIdentity).count() == 0


def test_oauth_with_an_unverified_listed_address_is_not_linked_to_the_operator(unauthenticated_client, db, test_user, monkeypatch):
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "test@example.com")
    r = _oauth_sign_in(
        unauthenticated_client, db, monkeypatch, "google",
        {"sub": "g-attacker", "email": "test@example.com"},
    )
    assert r.status_code == 403
    assert db.query(OAuthIdentity).count() == 0, "the operator's account gained no sign-in"


def test_oauth_with_an_unverified_unlisted_address_is_refused_too(unauthenticated_client, db, monkeypatch):
    """T-5.4.10 extends the gate from listed addresses to every first sign-in."""
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = _oauth_sign_in(
        unauthenticated_client, db, monkeypatch, "google", {"sub": "g-member", "email": "member@company.com"}
    )
    assert r.status_code == 403
    assert auth_service.get_user_by_email(db, "member@company.com") is None


def test_oauth_with_a_verified_unlisted_address_signs_in_as_a_member(unauthenticated_client, db, test_user, monkeypatch):
    _oauth_configured(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ops@company.com")
    r = _oauth_sign_in(
        unauthenticated_client, db, monkeypatch, "google",
        {"sub": "g-member", "email": "member@company.com", "email_verified": True},
    )
    assert r.status_code == 200, r.text
    assert not auth_service.is_operator(db, auth_service.get_user_by_email(db, "member@company.com"))


# ------------------------------------------------------------------ startup warning

def test_startup_warns_about_each_listed_address_with_no_account(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "test@example.com, Ops@Company.com,later@company.com")
    monkeypatch.setattr("app.database.SessionLocal", sessionmaker(bind=db.get_bind()))
    with patch("app.services.auth_service.logger") as log:
        with TestClient(app):
            pass
    warned = [c.args[1] for c in log.warning.call_args_list]
    assert warned == ["later@company.com", "ops@company.com"], "one per unregistered entry, none for test@example.com"
    assert "register the account before listing it" in log.warning.call_args_list[0].args[0]


def test_startup_reads_nothing_without_a_list(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("app.database.SessionLocal", factory)
    with patch("app.services.auth_service.logger") as log:
        with TestClient(app):
            pass
    factory.assert_not_called()
    log.warning.assert_not_called()

"""The account security page's backend contract (2026-11-03).

The page at ``/account/security`` lists active sessions, recent account
activity and two-step verification, and the sign-in page offers OAuth.
These tests pin what changed on the server for it, at the routers:

* ``GET /auth/sessions`` says which sessions still work (``active``,
  ``expires_at``): rows are never deleted, so before this every sign-in
  since the account was made read as a live session.
* ``GET /auth/audit-log?scope=account`` keeps sign-in, password, session,
  two-step, plan and Echo export/delete events, and drops the product
  analytics (suggestion impressions, onboarding, Echo drafts) the same
  table carries.
* An OAuth sign-in to an account with two-step verification on stops at
  the second factor, like a password sign-in.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pyotp
import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.oauth import OAuthState
from app.models.session import Session as SessionRow
from app.services import audit_service, auth_service, byok_service, mfa_service, oauth_service
from app.services.audit_service import Event


@pytest.fixture(autouse=True)
def _stable_fernet_key(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def _login(client, email: str, password: str = "goodpw1234") -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _enable_mfa(db, user) -> str:
    secret, _uri = mfa_service.enroll(db, user)
    mfa_service.verify_enrollment(db, user, pyotp.TOTP(secret).now())
    return secret


# ---------------------------------------------------------------------------
# Sessions: which ones still work
# ---------------------------------------------------------------------------


def test_sessions_say_which_still_work(unauthenticated_client, db):
    auth_service.create_user(db, email="sess-active@x.com", password="goodpw1234")
    old = _login(unauthenticated_client, "sess-active@x.com")
    revoked = _login(unauthenticated_client, "sess-active@x.com")
    current = _login(unauthenticated_client, "sess-active@x.com")

    rows = {r.jti: r for r in db.query(SessionRow).all()}
    by_token = {
        tok: auth_service.decode_token(tok)["jti"] for tok in (old, revoked, current)
    }
    # One session older than a token lives, one revoked, one fresh.
    rows[by_token[old]].created_at = datetime.now(timezone.utc) - timedelta(
        hours=settings.JWT_EXPIRY_HOURS, minutes=1
    )
    db.commit()
    unauthenticated_client.delete(
        f"/api/v1/auth/sessions/{by_token[revoked]}", headers=_auth(current)
    )

    r = unauthenticated_client.get("/api/v1/auth/sessions", headers=_auth(current))
    assert r.status_code == 200
    listed = {s["jti"]: s for s in r.json()}
    assert listed[by_token[current]]["active"] is True
    assert listed[by_token[current]]["is_current"] is True
    assert listed[by_token[old]]["active"] is False, "an expired session is not live"
    assert listed[by_token[revoked]]["active"] is False, "a revoked session is not live"

    created = datetime.fromisoformat(listed[by_token[current]]["created_at"])
    expires = datetime.fromisoformat(listed[by_token[current]]["expires_at"])
    created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    assert expires - created == timedelta(hours=settings.JWT_EXPIRY_HOURS)


# ---------------------------------------------------------------------------
# Audit log: the account scope
# ---------------------------------------------------------------------------


def _seed_mixed_events(db, user_id: str) -> None:
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    events = [
        Event.LOGIN_SUCCESS.value,
        Event.SUGGESTION_SHOWN.value,
        Event.MFA_ENABLED.value,
        Event.ONBOARDING_STARTED.value,
        "echo_drafted",  # recorded as a free string by echo_draft_service
        Event.SESSION_REVOKED.value,
        Event.SUGGESTION_CLICKED.value,
        Event.PASSWORD_RESET_COMPLETED.value,
    ]
    for i, event in enumerate(events):
        db.add(AuditLog(event=event, user_id=user_id, created_at=base + timedelta(minutes=i)))
    db.commit()


def test_audit_log_account_scope_drops_product_analytics(client, test_user, db):
    _seed_mixed_events(db, test_user.id)

    r = client.get("/api/v1/auth/audit-log?scope=account")

    assert r.status_code == 200
    assert [row["event"] for row in r.json()] == [
        "password_reset_completed",
        "session_revoked",
        "mfa_enabled",
        "login_success",
    ], "newest first, security events only"


def test_audit_log_default_scope_still_returns_everything(client, test_user, db):
    _seed_mixed_events(db, test_user.id)
    r = client.get("/api/v1/auth/audit-log")
    assert r.status_code == 200
    assert len(r.json()) == 8


def test_audit_log_account_scope_pages(client, test_user, db):
    _seed_mixed_events(db, test_user.id)
    first = client.get("/api/v1/auth/audit-log?scope=account&limit=3&offset=0").json()
    second = client.get("/api/v1/auth/audit-log?scope=account&limit=3&offset=3").json()
    assert [r["event"] for r in first] == ["password_reset_completed", "session_revoked", "mfa_enabled"]
    assert [r["event"] for r in second] == ["login_success"]


def test_audit_log_rejects_an_unknown_scope(client):
    assert client.get("/api/v1/auth/audit-log?scope=everything").status_code == 422


def test_account_events_leave_out_the_analytics_events():
    analytics = {
        Event.SUGGESTION_SHOWN,
        Event.SUGGESTION_CLICKED,
        Event.ONBOARDING_STARTED,
        Event.ONBOARDING_COMPLETED,
        Event.ONBOARDING_SKIPPED,
        Event.FIRST_JOB_CREATED,
        Event.FIRST_REPORT_OPENED,
    }
    assert not (audit_service.ACCOUNT_EVENTS & analytics)
    for needed in (Event.LOGIN_SUCCESS, Event.LOGIN_FAILURE, Event.PASSWORD_RESET_COMPLETED,
                   Event.SESSION_REVOKED, Event.MFA_DISABLED):
        assert needed in audit_service.ACCOUNT_EVENTS


# ---------------------------------------------------------------------------
# OAuth sign-in stops at the second factor
# ---------------------------------------------------------------------------


@pytest.fixture
def _google(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")


def _google_callback(client, db, monkeypatch, email: str):
    client.get(
        "/api/v1/auth/oauth/google/start?redirect_uri=https://app.example.com/login/oauth/google/callback"
    )
    state = db.query(OAuthState).first().state
    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "provider-tok"}
    user_resp = MagicMock()
    user_resp.json.return_value = {"sub": "g-1", "email": email, "email_verified": True}
    monkeypatch.setattr(oauth_service, "_default_http_post", MagicMock(return_value=token_resp))
    monkeypatch.setattr(oauth_service, "_default_http_get", MagicMock(return_value=user_resp))
    return client.get(f"/api/v1/auth/oauth/google/callback?code=c&state={state}")


def test_oauth_sign_in_with_two_step_on_asks_for_the_code(
    unauthenticated_client, db, monkeypatch, _google
):
    user = auth_service.create_user(db, email="mfa-oauth@x.com", password="goodpw1234")
    secret = _enable_mfa(db, user)

    r = _google_callback(unauthenticated_client, db, monkeypatch, "mfa-oauth@x.com")

    assert r.status_code == 200
    body = r.json()
    assert body["requires_mfa"] is True
    assert "access_token" not in body
    assert db.query(SessionRow).count() == 0, "no session before the second factor"

    done = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": body["mfa_token"], "code": pyotp.TOTP(secret).now()},
    )
    assert done.status_code == 200
    assert done.json()["access_token"]
    assert db.query(SessionRow).count() == 1


def test_oauth_sign_in_without_two_step_still_signs_in(
    unauthenticated_client, db, monkeypatch, _google
):
    auth_service.create_user(db, email="plain-oauth@x.com", password="goodpw1234")
    r = _google_callback(unauthenticated_client, db, monkeypatch, "plain-oauth@x.com")
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert "requires_mfa" not in r.json()


# ---------------------------------------------------------------------------
# The second-factor ticket is not a credential
# ---------------------------------------------------------------------------
#
# The ticket the first step hands out is signed with the access-token key and
# carries a `sub` but no `jti`. Until decode_access_token, every bearer check
# took it, so whoever had the password (or the provider account) could skip
# the code and use the ticket as an access token for its five minutes.

# Routes that read the caller through get_current_user, plus logout, whose
# get_current_jti read the ticket too.
_PROTECTED = [
    ("get", "/api/v1/auth/me"),
    ("get", "/api/v1/jobs"),
    ("get", "/api/v1/auth/sessions"),
    ("post", "/api/v1/auth/logout"),
]


def _password_ticket(client, db, email: str) -> tuple[str, str]:
    user = auth_service.create_user(db, email=email, password="goodpw1234")
    secret = _enable_mfa(db, user)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "goodpw1234"})
    assert r.status_code == 200
    assert r.json()["requires_mfa"] is True
    return r.json()["mfa_token"], secret


@pytest.mark.parametrize("method,path", _PROTECTED)
def test_the_password_step_ticket_authenticates_nothing(unauthenticated_client, db, method, path):
    ticket, _secret = _password_ticket(unauthenticated_client, db, f"ticket-{method}@x.com")

    r = getattr(unauthenticated_client, method)(path, headers=_auth(ticket))

    assert r.status_code == 401, f"the second-factor ticket authenticated {method.upper()} {path}"


def test_the_ticket_still_finishes_sign_in_and_the_token_it_buys_works(unauthenticated_client, db):
    # The other half: the guard refuses the ticket, not access tokens.
    ticket, secret = _password_ticket(unauthenticated_client, db, "ticket-ok@x.com")
    done = unauthenticated_client.post(
        "/api/v1/auth/login/mfa", json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()}
    )
    assert done.status_code == 200
    me = unauthenticated_client.get("/api/v1/auth/me", headers=_auth(done.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "ticket-ok@x.com"


def test_the_oauth_step_ticket_authenticates_nothing(unauthenticated_client, db, monkeypatch, _google):
    user = auth_service.create_user(db, email="ticket-oauth@x.com", password="goodpw1234")
    _enable_mfa(db, user)
    body = _google_callback(unauthenticated_client, db, monkeypatch, "ticket-oauth@x.com").json()
    assert body["requires_mfa"] is True

    for method, path in _PROTECTED:
        r = getattr(unauthenticated_client, method)(path, headers=_auth(body["mfa_token"]))
        assert r.status_code == 401, f"the OAuth ticket authenticated {method.upper()} {path}"


def test_the_ticket_does_not_open_the_progress_socket(unauthenticated_client, db, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    from tests.test_routers.test_url_tokens import _FakeManager

    fake = _FakeManager()
    monkeypatch.setattr("app.routers.ws.manager", fake)
    ticket, _secret = _password_ticket(unauthenticated_client, db, "ticket-ws@x.com")

    with pytest.raises(WebSocketDisconnect) as exc:
        with unauthenticated_client.websocket_connect(f"/ws/jobs?token={ticket}"):
            pass
    assert exc.value.code == 1008
    assert fake.connected == 0

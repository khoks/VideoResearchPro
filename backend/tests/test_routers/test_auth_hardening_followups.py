"""Auth hardening follow-ups from #388 and #389, at the routers (E-5.4, E-5.6).

* T-5.4.12: a password reset signs the account out everywhere, in the same
  commit as the new password, and says so in the audit log.
* T-5.4.13: one second-factor ticket takes at most
  ``mfa_service.MFA_TICKET_MAX_ATTEMPTS`` codes, counted on its ``jti`` (not
  the caller's address), and buys one session. A dead ticket refuses even
  the right code; sign-in starts over.
* T-5.4.14: ``POST /auth/password/change`` for a signed-in user: the current
  password under the account lockout, the other sessions signed out and
  this one kept, an account Google or GitHub made told to use the reset,
  rate-limited like sign-in, and never a 401 (the web client signs out on
  one).
* T-5.4.15: the ``/ws/jobs`` handshake runs the HTTP routes' bearer check
  (``auth_service.authenticate_access_token``), so a token whose session was
  revoked no longer opens it.
* T-5.6.9: every route that encrypts or decrypts with the shared Fernet key
  answers a malformed ``BYOK_ENCRYPTION_KEY`` with 503 and the cause, never
  a bare 500: two-step verification (enrol, confirm, turn off, sign in) and
  Echo connectors (connect), plus an exception handler for any other route.

Mutation checks (run when this shipped; each made the named test fail, and
the cheap ones are pinned as ``test_mutation_*``): dropping the revocation
from ``confirm_password_reset``
(``test_a_reset_signs_the_account_out_everywhere``); deleting the
``count_ticket_attempt`` call in ``login_mfa`` or raising the cap
(``test_a_ticket_takes_five_codes_then_refuses_even_the_right_one``); keying
the count on the address instead of the ticket
(``test_the_cap_follows_the_ticket_not_the_address``); dropping
``use_ticket`` (``test_a_ticket_buys_one_session``); passing ``keep_jti=None``
from the change route (``test_change_keeps_this_session_and_signs_out_the_others``);
checking the current password without the lockout
(``test_a_wrong_current_password_counts_toward_the_lock``); the old
decode-only socket handshake (``test_a_revoked_session_cannot_open_the_socket``);
letting ``_verify_totp_against_row`` swallow the key error again
(``test_sign_in_code_with_a_malformed_key_says_why``); dropping the enrol
route's catch (``test_setting_up_two_step_with_a_malformed_key_says_why``);
dropping the up-front check from ``start_connect``
(``test_connecting_a_connector_with_a_malformed_key_is_refused_up_front``);
removing the app's exception handler
(``test_any_other_route_meets_the_handler_not_a_500``); an OAuth-created
account marked as having a password
(``test_an_account_google_made_is_told_to_use_the_reset``).
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import jwt
import pyotp
import pytest
from cryptography.fernet import Fernet
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.echo_connector import EchoConnectorCredential, EchoConnectorGrant
from app.models.mfa_secret import MfaSecret
from app.models.mfa_step_ticket import MfaStepTicket
from app.models.oauth import OAuthState
from app.models.session import Session as SessionRow
from app.models.user import User
from app.routers import mfa as mfa_router
from app.services import auth_service, byok_service, mfa_service, oauth_service, rate_limit_service
from app.services.audit_service import Event
from tests.conftest import TestingSessionLocal
from tests.test_routers.test_auth_hardening import _reset_secret
from tests.test_routers.test_url_tokens import _FakeManager

PASSWORD = "goodpw1234"
CHANGE = "/api/v1/auth/password/change"
LOGIN_MFA = "/api/v1/auth/login/mfa"
# Set, but not 32 url-safe base64 bytes.
MALFORMED_KEY = "malformed-placeholder-5c2e"


@pytest.fixture
def stable_key(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def _break_the_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", MALFORMED_KEY)
    byok_service._get_fernet.cache_clear()


@pytest.fixture
def malformed_key(monkeypatch):
    _break_the_key(monkeypatch)
    yield
    byok_service._get_fernet.cache_clear()


def _login(client, email: str, password: str = PASSWORD) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _me(client, token: str) -> int:
    return client.get("/api/v1/auth/me", headers=_auth(token)).status_code


def _events(db, event: Event, user_id: str | None = None) -> list[AuditLog]:
    q = db.query(AuditLog).filter(AuditLog.event == event.value)
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    return q.order_by(AuditLog.created_at).all()


def _meta(row: AuditLog) -> dict:
    return json.loads(row.metadata_json or "{}")


# ---------------------------------------------------------------------------
# T-5.4.12: a reset signs the account out everywhere
# ---------------------------------------------------------------------------


def _reset(client, monkeypatch, email: str, new_password: str = "newpw12345"):
    secret = _reset_secret(client, monkeypatch, email)
    return client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": new_password},
    )


def test_a_reset_signs_the_account_out_everywhere(unauthenticated_client, db, monkeypatch):
    auth_service.create_user(db, email="reset-out@x.com", password=PASSWORD)
    phone = _login(unauthenticated_client, "reset-out@x.com")
    laptop = _login(unauthenticated_client, "reset-out@x.com")
    assert _me(unauthenticated_client, phone) == 200

    assert _reset(unauthenticated_client, monkeypatch, "reset-out@x.com").status_code == 200

    assert _me(unauthenticated_client, phone) == 401, "a reset must end a session already signed in"
    assert _me(unauthenticated_client, laptop) == 401
    db.expire_all()
    assert db.query(SessionRow).filter(SessionRow.revoked_at.is_(None)).count() == 0
    # The new password signs in, and that session works.
    fresh = _login(unauthenticated_client, "reset-out@x.com", "newpw12345")
    assert _me(unauthenticated_client, fresh) == 200


def test_a_reset_writes_the_sign_out_to_the_audit_log(unauthenticated_client, db, monkeypatch):
    user = auth_service.create_user(db, email="reset-audit@x.com", password=PASSWORD)
    _login(unauthenticated_client, "reset-audit@x.com")
    _login(unauthenticated_client, "reset-audit@x.com")

    assert _reset(unauthenticated_client, monkeypatch, "reset-audit@x.com").status_code == 200

    (signed_out,) = _events(db, Event.SESSIONS_REVOKED_ALL, user.id)
    assert _meta(signed_out) == {"revoked_count": 2, "keep_current": False, "reason": "password_reset"}
    (completed,) = _events(db, Event.PASSWORD_RESET_COMPLETED, user.id)
    assert _meta(completed) == {"sessions_revoked": 2}


def test_mutation_a_reset_without_the_revocation_leaves_sessions_alive(unauthenticated_client, db, monkeypatch):
    # The pre-T-5.4.12 service: the first test fails against it.
    monkeypatch.setattr(auth_service, "_mark_sessions_revoked", lambda *a, **k: 0)
    auth_service.create_user(db, email="reset-mut@x.com", password=PASSWORD)
    phone = _login(unauthenticated_client, "reset-mut@x.com")
    assert _reset(unauthenticated_client, monkeypatch, "reset-mut@x.com").status_code == 200
    assert _me(unauthenticated_client, phone) == 200


# ---------------------------------------------------------------------------
# T-5.4.13: attempts per second-factor ticket
# ---------------------------------------------------------------------------


def _mfa_user(db, email: str) -> tuple[User, str, list[str]]:
    user = auth_service.create_user(db, email=email, password=PASSWORD)
    secret, _uri = mfa_service.enroll(db, user)
    codes = mfa_service.verify_enrollment(db, user, pyotp.TOTP(secret).now())
    return user, secret, codes


def _ticket(client, email: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["requires_mfa"] is True, r.text
    return r.json()["mfa_token"]


def _wrong_code(secret: str) -> str:
    right = pyotp.TOTP(secret)
    now = datetime.now(timezone.utc)
    valid = {right.at(now + timedelta(seconds=30 * k)) for k in (-1, 0, 1)}
    return next(c for c in (f"{n:06d}" for n in range(1_000_000)) if c not in valid)


def test_a_ticket_takes_five_codes_then_refuses_even_the_right_one(unauthenticated_client, db, stable_key):
    assert mfa_service.MFA_TICKET_MAX_ATTEMPTS == 5
    user, secret, _codes = _mfa_user(db, "cap@x.com")
    ticket = _ticket(unauthenticated_client, "cap@x.com")
    wrong = _wrong_code(secret)

    for attempt in range(1, 5):
        r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": wrong})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid TOTP or recovery code", attempt
    last = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": wrong})
    assert last.status_code == 401
    assert last.json()["detail"] == mfa_router.TICKET_EXHAUSTED_DETAIL, "the fifth miss closes the ticket"

    right = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    assert right.status_code == 401, "a dead ticket refuses the right code"
    assert right.json()["detail"] == mfa_router.TICKET_EXHAUSTED_DETAIL
    assert db.query(SessionRow).count() == 0

    # Sign-in starts over: a new password step, a new ticket, and it works.
    again = unauthenticated_client.post(
        LOGIN_MFA, json={"mfa_token": _ticket(unauthenticated_client, "cap@x.com"), "code": pyotp.TOTP(secret).now()}
    )
    assert again.status_code == 200
    reasons = [_meta(r)["reason"] for r in _events(db, Event.MFA_LOGIN_FAILURE, user.id)]
    assert reasons == ["invalid_code"] * 4 + ["too_many_attempts", "too_many_attempts"]


def test_mutation_without_the_cap_the_sixth_code_signs_in(unauthenticated_client, db, stable_key, monkeypatch):
    monkeypatch.setattr(mfa_service, "MFA_TICKET_MAX_ATTEMPTS", 10**6)
    _user, secret, _codes = _mfa_user(db, "cap-mut@x.com")
    ticket = _ticket(unauthenticated_client, "cap-mut@x.com")
    for _ in range(5):
        unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": _wrong_code(secret)})
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


def test_the_cap_follows_the_ticket_not_the_address(unauthenticated_client, db, stable_key):
    _user, secret, _codes = _mfa_user(db, "cap-ip@x.com")
    spent = _ticket(unauthenticated_client, "cap-ip@x.com")
    fresh = _ticket(unauthenticated_client, "cap-ip@x.com")
    wrong = _wrong_code(secret)

    # Five misses from five addresses still close the ticket.
    for i in range(5):
        unauthenticated_client.post(
            LOGIN_MFA, json={"mfa_token": spent, "code": wrong}, headers={"X-Forwarded-For": f"203.0.113.{i + 1}"}
        )
    r = unauthenticated_client.post(
        LOGIN_MFA,
        json={"mfa_token": spent, "code": pyotp.TOTP(secret).now()},
        headers={"X-Forwarded-For": "198.51.100.77"},
    )
    assert r.status_code == 401 and r.json()["detail"] == mfa_router.TICKET_EXHAUSTED_DETAIL
    # Another ticket, from the address that spent the first, is untouched.
    r = unauthenticated_client.post(
        LOGIN_MFA,
        json={"mfa_token": fresh, "code": pyotp.TOTP(secret).now()},
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    assert r.status_code == 200


def test_the_sign_in_page_knows_the_refusals_that_end_the_step():
    """The page goes back to the first step on these two exact strings, so a
    reworded detail would leave the reader typing codes into a dead ticket."""
    step = Path(__file__).resolve().parents[3] / "frontend/src/components/auth/MfaCodeStep.tsx"
    source = step.read_text(encoding="utf-8")
    assert f"'{mfa_router.TICKET_EXPIRED_DETAIL}'" in source
    assert f"'{mfa_router.TICKET_EXHAUSTED_DETAIL}'" in source


def test_a_ticket_buys_one_session(unauthenticated_client, db, stable_key):
    _user, secret, codes = _mfa_user(db, "once@x.com")
    ticket = _ticket(unauthenticated_client, "once@x.com")
    assert unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": codes[0]}).status_code == 200

    replay = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": codes[1]})

    assert replay.status_code == 401
    assert replay.json()["detail"] == mfa_router.TICKET_EXPIRED_DETAIL
    assert db.query(SessionRow).count() == 1
    db.expire_all()
    stored = json.loads(db.query(MfaSecret).one().recovery_codes_json)
    assert len(stored) == len(codes) - 1, "the replay did not spend a recovery code"


def test_a_ticket_without_an_id_is_refused(unauthenticated_client, db, stable_key):
    """Issued before T-5.4.13: nothing to count it on, so sign-in starts over."""
    user, secret, _codes = _mfa_user(db, "noid@x.com")
    now = datetime.now(timezone.utc)
    old = jwt.encode(
        {"sub": user.id, "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()),
         "mfa_step": True, "typ": "mfa_step"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": old, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 401
    assert r.json()["detail"] == mfa_router.TICKET_EXPIRED_DETAIL


def test_rows_of_expired_tickets_are_swept(unauthenticated_client, db, stable_key):
    _user, secret, _codes = _mfa_user(db, "sweep@x.com")
    db.add(MfaStepTicket(jti="gone", user_id="someone", attempts=2,
                         expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)))
    db.commit()
    ticket = _ticket(unauthenticated_client, "sweep@x.com")
    unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": _wrong_code(secret)})
    db.expire_all()
    assert [r.jti for r in db.query(MfaStepTicket).all()] == [mfa_service.decode_mfa_step_ticket(ticket).jti]


# ---------------------------------------------------------------------------
# T-5.4.14: change the password while signed in
# ---------------------------------------------------------------------------


def _change(client, token: str, current: str, new: str):
    return client.post(CHANGE, json={"current_password": current, "new_password": new}, headers=_auth(token))


def test_change_keeps_this_session_and_signs_out_the_others(unauthenticated_client, db):
    user = auth_service.create_user(db, email="change@x.com", password=PASSWORD)
    here = _login(unauthenticated_client, "change@x.com")
    elsewhere = _login(unauthenticated_client, "change@x.com")

    r = _change(unauthenticated_client, here, PASSWORD, "brand-new-pw")

    assert r.status_code == 200, r.text
    assert r.json()["sessions_revoked"] == 1
    assert _me(unauthenticated_client, here) == 200, "the session that changed it stays signed in"
    assert _me(unauthenticated_client, elsewhere) == 401
    assert unauthenticated_client.post(
        "/api/v1/auth/login", json={"email": "change@x.com", "password": PASSWORD}
    ).status_code == 401
    assert _me(unauthenticated_client, _login(unauthenticated_client, "change@x.com", "brand-new-pw")) == 200

    (changed,) = _events(db, Event.PASSWORD_CHANGED, user.id)
    assert _meta(changed) == {"sessions_revoked": 1}
    (signed_out,) = _events(db, Event.SESSIONS_REVOKED_ALL, user.id)
    assert _meta(signed_out) == {"revoked_count": 1, "keep_current": True, "reason": "password_change"}


def test_a_wrong_current_password_counts_toward_the_lock(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 3)
    user = auth_service.create_user(db, email="change-lock@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "change-lock@x.com")

    for _ in range(3):
        r = _change(unauthenticated_client, token, "not-the-password", "brand-new-pw")
        assert r.status_code == 400, "never 401: the web client signs out on a 401"
        assert r.json()["detail"] == "The current password is not right."

    db.expire_all()
    assert auth_service.is_locked(auth_service.get_user_by_id(db, user.id))
    locked = _change(unauthenticated_client, token, PASSWORD, "brand-new-pw")
    assert locked.status_code == 429, "locked: even the right password waits"
    assert "Forgot it?" in locked.json()["detail"]
    # The lock is the account's: sign-in is refused too, and the session lives.
    assert unauthenticated_client.post(
        "/api/v1/auth/login", json={"email": "change-lock@x.com", "password": PASSWORD}
    ).status_code == 401
    assert _me(unauthenticated_client, token) == 200
    reasons = [_meta(r)["reason"] for r in _events(db, Event.PASSWORD_CHANGE_FAILED, user.id)]
    assert reasons == ["wrong_password"] * 3 + ["locked_out"]
    assert len(_events(db, Event.ACCOUNT_LOCKED, user.id)) == 1


def test_a_right_current_password_clears_earlier_misses(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 3)
    user = auth_service.create_user(db, email="change-clear@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "change-clear@x.com")
    _change(unauthenticated_client, token, "not-the-password", "brand-new-pw")
    assert _change(unauthenticated_client, token, PASSWORD, "brand-new-pw").status_code == 200
    db.expire_all()
    assert auth_service.get_user_by_id(db, user.id).failed_login_attempts == 0


@pytest.fixture
def _google(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")


def _google_sign_in(client, db, monkeypatch, email: str) -> str:
    client.get("/api/v1/auth/oauth/google/start?redirect_uri=https://app.example.com/login/oauth/google/callback")
    state = db.query(OAuthState).first().state
    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "provider-tok"}
    user_resp = MagicMock()
    user_resp.json.return_value = {"sub": "g-77", "email": email, "email_verified": True}
    monkeypatch.setattr(oauth_service, "_default_http_post", MagicMock(return_value=token_resp))
    monkeypatch.setattr(oauth_service, "_default_http_get", MagicMock(return_value=user_resp))
    r = client.get(f"/api/v1/auth/oauth/google/callback?code=c&state={state}")
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_an_account_google_made_is_told_to_use_the_reset(unauthenticated_client, db, monkeypatch, _google):
    token = _google_sign_in(unauthenticated_client, db, monkeypatch, "only-google@x.com")
    user = auth_service.get_user_by_email(db, "only-google@x.com")
    assert user.has_password is False, "an OAuth sign-in that creates the account sets no known password"

    r = _change(unauthenticated_client, token, "anything", "brand-new-pw")

    assert r.status_code == 400
    assert "no password" in r.json()["detail"] and "Forgot it?" in r.json()["detail"]
    db.expire_all()
    assert auth_service.get_user_by_id(db, user.id).failed_login_attempts == 0, "not a guess: nothing counted"
    assert _me(unauthenticated_client, token) == 200


def test_linking_google_to_a_password_account_keeps_its_password(unauthenticated_client, db, monkeypatch, _google):
    auth_service.create_user(db, email="has-pw@x.com", password=PASSWORD)
    token = _google_sign_in(unauthenticated_client, db, monkeypatch, "has-pw@x.com")
    assert _change(unauthenticated_client, token, PASSWORD, "brand-new-pw").status_code == 200


def test_a_reset_gives_a_google_account_a_password_it_can_change(unauthenticated_client, db, monkeypatch, _google):
    _google_sign_in(unauthenticated_client, db, monkeypatch, "google-then-reset@x.com")
    assert _reset(unauthenticated_client, monkeypatch, "google-then-reset@x.com", "first-pw-123").status_code == 200
    db.expire_all()
    assert auth_service.get_user_by_email(db, "google-then-reset@x.com").has_password is True
    token = _login(unauthenticated_client, "google-then-reset@x.com", "first-pw-123")
    assert _change(unauthenticated_client, token, "first-pw-123", "second-pw-123").status_code == 200


@pytest.mark.parametrize("new", ["Zq9!x", "Q" * 129])
def test_the_new_password_is_measured_and_never_echoed(unauthenticated_client, db, new):
    auth_service.create_user(db, email="change-len@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "change-len@x.com")
    r = _change(unauthenticated_client, token, PASSWORD, new)
    assert r.status_code == 400
    assert "6 to 128" in r.json()["detail"]
    assert new not in r.text
    assert PASSWORD not in r.text


def test_a_wrong_current_password_is_not_echoed(unauthenticated_client, db):
    auth_service.create_user(db, email="change-echo@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "change-echo@x.com")
    r = _change(unauthenticated_client, token, "Distinct-Wrong-77", "brand-new-pw")
    assert "Distinct-Wrong-77" not in r.text and "brand-new-pw" not in r.text


def test_change_needs_a_session(unauthenticated_client):
    r = unauthenticated_client.post(CHANGE, json={"current_password": "a", "new_password": "brand-new-pw"})
    assert r.status_code == 401


def test_change_is_rate_limited_like_sign_in(unauthenticated_client, db, monkeypatch):
    auth_service.create_user(db, email="change-rate@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "change-rate@x.com")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MIN", 2)
    rate_limit_service.reset()

    codes = [_change(unauthenticated_client, token, "not-the-password", "brand-new-pw").status_code for _ in range(3)]

    assert codes == [400, 400, 429]
    # Its own bucket: changing a password does not use up sign-in attempts.
    assert unauthenticated_client.post(
        "/api/v1/auth/login", json={"email": "change-rate@x.com", "password": PASSWORD}
    ).status_code == 200


# ---------------------------------------------------------------------------
# T-5.4.15: the progress socket checks the session
# ---------------------------------------------------------------------------


@pytest.fixture
def socket_db(db, monkeypatch):
    """The handshake opens its own short-lived session from
    ``app.database.SessionLocal``; point that at the test database."""
    monkeypatch.setattr("app.database.SessionLocal", TestingSessionLocal)
    fake = _FakeManager()
    monkeypatch.setattr("app.routers.ws.manager", fake)
    return fake


def _socket_opens(client, token: str) -> bool:
    try:
        with client.websocket_connect(f"/ws/jobs?token={token}") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "pong"
        return True
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
        return False


def test_a_revoked_session_cannot_open_the_socket(unauthenticated_client, db, socket_db):
    auth_service.create_user(db, email="ws-out@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "ws-out@x.com")
    assert _socket_opens(unauthenticated_client, token)

    assert unauthenticated_client.post("/api/v1/auth/logout", headers=_auth(token)).status_code == 200

    assert not _socket_opens(unauthenticated_client, token), "a signed-out token opened the socket"
    assert socket_db.connected == 1


@pytest.mark.parametrize("how", ["sign_out_everywhere", "password_reset", "password_change_elsewhere"])
def test_every_way_of_ending_a_session_closes_the_socket_to_it(unauthenticated_client, db, socket_db, monkeypatch, how):
    email = f"ws-{how}@x.com"
    auth_service.create_user(db, email=email, password=PASSWORD)
    token = _login(unauthenticated_client, email)
    other = _login(unauthenticated_client, email)
    if how == "sign_out_everywhere":
        unauthenticated_client.delete("/api/v1/auth/sessions", headers=_auth(other))
    elif how == "password_reset":
        assert _reset(unauthenticated_client, monkeypatch, email).status_code == 200
    else:
        assert _change(unauthenticated_client, other, PASSWORD, "brand-new-pw").status_code == 200
    assert not _socket_opens(unauthenticated_client, token)


def test_a_deleted_user_cannot_open_the_socket(unauthenticated_client, db, socket_db):
    user = auth_service.create_user(db, email="ws-gone@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "ws-gone@x.com")
    db.delete(user)
    db.commit()
    assert not _socket_opens(unauthenticated_client, token)


def test_the_socket_check_fails_closed():
    from app.routers.ws import _authenticate

    def _down():
        raise RuntimeError("db down")

    token, _ = auth_service.create_access_token("anyone")
    assert _authenticate(token, _down) is None


def test_mutation_the_old_decode_only_handshake_lets_a_revoked_token_in(unauthenticated_client, db, socket_db, monkeypatch):
    from app.routers import ws

    def _decode_only(token, session_factory=None):
        payload = auth_service.decode_access_token(token)
        return payload.get("sub") if payload else None

    monkeypatch.setattr(ws, "_authenticate", _decode_only)
    auth_service.create_user(db, email="ws-mut@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "ws-mut@x.com")
    unauthenticated_client.post("/api/v1/auth/logout", headers=_auth(token))
    assert _socket_opens(unauthenticated_client, token)


# ---------------------------------------------------------------------------
# T-5.6.9: a malformed BYOK_ENCRYPTION_KEY answers 503 with the cause
# ---------------------------------------------------------------------------


def _says_the_key_is_bad(r, what: str) -> None:
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail.startswith(what), detail
    assert "BYOK_ENCRYPTION_KEY" in detail and "not a valid key" in detail
    assert MALFORMED_KEY not in r.text


def test_setting_up_two_step_with_a_malformed_key_says_why(unauthenticated_client, db, malformed_key):
    auth_service.create_user(db, email="enc-enrol@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "enc-enrol@x.com")

    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=_auth(token))

    _says_the_key_is_bad(r, "Two-step verification cannot be set up")
    assert db.query(MfaSecret).count() == 0


def test_confirming_two_step_with_a_malformed_key_says_why(unauthenticated_client, db, stable_key, monkeypatch):
    user = auth_service.create_user(db, email="enc-confirm@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "enc-confirm@x.com")
    secret, _uri = mfa_service.enroll(db, user)
    _break_the_key(monkeypatch)

    r = unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment", json={"code": pyotp.TOTP(secret).now()}, headers=_auth(token)
    )

    _says_the_key_is_bad(r, "Two-step verification cannot be turned on")
    assert mfa_service.is_enabled(db, user.id) is False


def test_sign_in_code_with_a_malformed_key_says_why(unauthenticated_client, db, stable_key, monkeypatch):
    user, secret, codes = _mfa_user(db, "enc-login@x.com")
    _break_the_key(monkeypatch)
    ticket = _ticket(unauthenticated_client, "enc-login@x.com")

    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})

    _says_the_key_is_bad(r, "The authenticator code cannot be checked")
    assert "recovery code still works" in r.json()["detail"]
    # Recovery codes are hashed, not encrypted: they still sign in.
    ok = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": codes[0]})
    assert ok.status_code == 200
    db.expire_all()
    assert db.query(MfaStepTicket).one().attempts == 2, "the refused code still spent an attempt"


def test_turning_two_step_off_with_a_malformed_key(unauthenticated_client, db, stable_key, monkeypatch):
    user, secret, codes = _mfa_user(db, "enc-off@x.com")
    token, _ = auth_service.create_access_token(user.id, db=db)
    _break_the_key(monkeypatch)

    r = unauthenticated_client.request(
        "DELETE", "/api/v1/auth/mfa", json={"code": pyotp.TOTP(secret).now()}, headers=_auth(token)
    )
    _says_the_key_is_bad(r, "The code cannot be checked")
    assert mfa_service.is_enabled(db, user.id) is True

    r = unauthenticated_client.request("DELETE", "/api/v1/auth/mfa", json={"code": codes[0]}, headers=_auth(token))
    assert r.status_code == 200
    assert mfa_service.is_enabled(db, user.id) is False


def test_mutation_swallowing_the_key_error_reads_as_a_wrong_code(unauthenticated_client, db, stable_key, monkeypatch):
    # The pre-T-5.6.9 check: any decrypt failure was "the code does not match".
    def _swallowing(row, code):
        try:
            secret = byok_service.decrypt_secret(row.secret_encrypted)
        except Exception:
            return False
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)

    monkeypatch.setattr(mfa_service, "_verify_totp_against_row", _swallowing)
    _user, secret, _codes = _mfa_user(db, "enc-mut@x.com")
    _break_the_key(monkeypatch)
    ticket = _ticket(unauthenticated_client, "enc-mut@x.com")
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 401


class _FakeConnector:
    name = "keytest"
    display_name = "Key test"
    privacy_weight = "low"
    consent_disclosure = "Reads nothing."
    consent_version = "2026-11-04"
    schedule = None

    def event_types(self):
        return []

    def is_configured(self):
        return True

    def authorize_url(self, *, redirect_uri, state, code_challenge):
        return "https://keytest.example/authorize?" + urllib.parse.urlencode({"state": state})

    def handle_callback(self, *, code, redirect_uri, code_verifier):
        from app.connectors.base import ConnectorTokens

        return ConnectorTokens(access_token="placeholder-access", scopes="read", account_label="me")


@pytest.fixture
def keytest_connector(monkeypatch):
    from app.connectors import registry

    registry.register_connector(_FakeConnector())
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.example")
    yield
    registry.unregister_connector("keytest")


def _studio_token(db, email: str) -> tuple[User, str]:
    user = auth_service.create_user(db, email=email, password=PASSWORD)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, token


def test_connecting_a_connector_with_a_malformed_key_is_refused_up_front(
    unauthenticated_client, db, keytest_connector, malformed_key
):
    from app.models.echo_connector import EchoConnectorOAuthState

    _user, token = _studio_token(db, "enc-conn@x.com")
    r = unauthenticated_client.post(
        "/api/v1/echo/connectors/keytest/authorize",
        json={"consent_version": _FakeConnector.consent_version},
        headers=_auth(token),
    )
    _says_the_key_is_bad(r, "Connectors cannot be connected")
    assert db.query(EchoConnectorOAuthState).count() == 0, "no round trip to the provider was started"


def test_finishing_a_connect_with_a_malformed_key_says_why(
    unauthenticated_client, db, keytest_connector, stable_key, monkeypatch
):
    _user, token = _studio_token(db, "enc-cb@x.com")
    r = unauthenticated_client.post(
        "/api/v1/echo/connectors/keytest/authorize",
        json={"consent_version": _FakeConnector.consent_version},
        headers=_auth(token),
    )
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["authorize_url"]).query)["state"][0]
    _break_the_key(monkeypatch)

    r = unauthenticated_client.post(
        "/api/v1/echo/connectors/keytest/callback", json={"code": "c", "state": state}, headers=_auth(token)
    )

    _says_the_key_is_bad(r, "The connector's access could not be stored")
    assert "placeholder-access" not in r.text
    assert db.query(EchoConnectorCredential).count() == 0
    assert db.query(EchoConnectorGrant).count() == 0


def test_any_other_route_meets_the_handler_not_a_500(unauthenticated_client, malformed_key):
    """The net: a route that does not catch the error itself."""

    def _encrypts():
        byok_service.encrypt_secret("placeholder")
        return {"ok": True}

    app.add_api_route("/api/v1/__t569_encrypts", _encrypts, methods=["GET"])
    try:
        r = unauthenticated_client.get("/api/v1/__t569_encrypts")
    finally:
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/v1/__t569_encrypts"]
    _says_the_key_is_bad(r, "Nothing stored encrypted can be saved or read")


def test_the_reset_and_change_flows_never_touch_the_key(unauthenticated_client, db, monkeypatch, malformed_key):
    """Passwords are hashed, not encrypted: a broken key must not stop them."""
    auth_service.create_user(db, email="enc-pw@x.com", password=PASSWORD)
    token = _login(unauthenticated_client, "enc-pw@x.com")
    assert _change(unauthenticated_client, token, PASSWORD, "brand-new-pw").status_code == 200
    assert _reset(unauthenticated_client, monkeypatch, "enc-pw@x.com").status_code == 200

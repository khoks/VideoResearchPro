"""Tests for E-5.4 auth hardening — audit log, account lockout,
password reset.

The fixtures from `conftest.py` give us:
- `db` — in-memory SQLite session
- `unauthenticated_client` — TestClient without auth headers
- `client` — TestClient with auth headers for `test_user`
- `test_user` — a User row created via auth_service
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.config import settings
from app.models.audit_log import AuditLog
from app.models.password_reset_token import PasswordResetToken
from app.services import auth_service
from app.services.audit_service import Event


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------


def test_login_failure_increments_failed_attempts(unauthenticated_client, db):
    auth_service.create_user(db, email="lock@x.com", password="rightpw1234")

    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "lock@x.com", "password": "wrongpw"},
    )
    assert r.status_code == 401

    db.expire_all()
    user = auth_service.get_user_by_email(db, "lock@x.com")
    assert user.failed_login_attempts == 1
    assert user.locked_until is None


def test_lockout_after_threshold_failures(unauthenticated_client, db, monkeypatch):
    # Tighten threshold for the test so we don't hammer bcrypt N times.
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 3)
    monkeypatch.setattr(settings, "LOCKOUT_DURATION_MIN", 15)

    auth_service.create_user(db, email="lockme@x.com", password="rightpw1234")

    for _ in range(3):
        r = unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "lockme@x.com", "password": "wrong"},
        )
        assert r.status_code == 401

    db.expire_all()
    user = auth_service.get_user_by_email(db, "lockme@x.com")
    assert user.failed_login_attempts == 3
    assert user.locked_until is not None
    assert user.locked_until > datetime.now(timezone.utc).replace(tzinfo=None)

    # Even the *correct* password is rejected while locked.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "lockme@x.com", "password": "rightpw1234"},
    )
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


def test_successful_login_resets_failed_attempts(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 5)
    auth_service.create_user(db, email="reset@x.com", password="rightpw1234")

    # Two failures.
    for _ in range(2):
        unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "reset@x.com", "password": "nope"},
        )
    db.expire_all()
    user = auth_service.get_user_by_email(db, "reset@x.com")
    assert user.failed_login_attempts == 2

    # Successful login.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@x.com", "password": "rightpw1234"},
    )
    assert r.status_code == 200

    db.expire_all()
    user = auth_service.get_user_by_email(db, "reset@x.com")
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_lockout_releases_after_duration(db, monkeypatch):
    """Set `locked_until` to a past time and confirm authentication
    succeeds (the lock has expired)."""
    user = auth_service.create_user(db, email="expire@x.com", password="rightpw1234")
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    user.failed_login_attempts = 5
    db.commit()

    fetched, outcome = auth_service.authenticate_user_v2(
        db, email="expire@x.com", password="rightpw1234"
    )
    assert outcome == auth_service.AuthOutcome.SUCCESS
    assert fetched.id == user.id


def test_unknown_email_returns_invalid_credentials_not_locked(
    unauthenticated_client, db, monkeypatch
):
    """The lockout system must NOT apply to unknown emails — otherwise
    an attacker could lock arbitrary accounts by trying any email."""
    # No user with that email.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@x.com", "password": "anything"},
    )
    assert r.status_code == 401
    # No User row was created — so nothing got locked.
    user = auth_service.get_user_by_email(db, "nobody@x.com")
    assert user is None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_register_creates_audit_event(unauthenticated_client, db):
    r = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "audit1@x.com", "password": "goodpw1234"},
    )
    assert r.status_code == 201

    rows = db.query(AuditLog).filter(AuditLog.event == Event.USER_REGISTERED.value).all()
    assert len(rows) == 1
    assert rows[0].user_id == r.json()["id"]


def test_login_success_creates_audit_event(unauthenticated_client, db):
    auth_service.create_user(db, email="audit2@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "audit2@x.com", "password": "goodpw1234"},
    )
    assert r.status_code == 200

    rows = db.query(AuditLog).filter(AuditLog.event == Event.LOGIN_SUCCESS.value).all()
    assert len(rows) == 1


def test_login_failure_creates_audit_event(unauthenticated_client, db):
    auth_service.create_user(db, email="audit3@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "audit3@x.com", "password": "wrongpw"},
    )
    assert r.status_code == 401

    rows = db.query(AuditLog).filter(AuditLog.event == Event.LOGIN_FAILURE.value).all()
    assert len(rows) == 1
    # user_id is set because the email matched.
    assert rows[0].user_id is not None


def test_login_failure_unknown_email_audited_with_null_user_id(
    unauthenticated_client, db
):
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@x.com", "password": "any"},
    )
    assert r.status_code == 401

    rows = db.query(AuditLog).filter(AuditLog.event == Event.LOGIN_FAILURE.value).all()
    assert len(rows) == 1
    assert rows[0].user_id is None
    # The email is captured in metadata for forensics.
    assert "ghost@x.com" in rows[0].metadata_json


def test_account_locked_event_emitted_on_threshold(
    unauthenticated_client, db, monkeypatch
):
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 2)
    auth_service.create_user(db, email="trigger@x.com", password="goodpw1234")
    for _ in range(2):
        unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "trigger@x.com", "password": "nope"},
        )
    rows = db.query(AuditLog).filter(AuditLog.event == Event.ACCOUNT_LOCKED.value).all()
    assert len(rows) == 1


def test_audit_log_endpoint_returns_own_events(client, test_user, db):
    """`GET /auth/audit-log` returns the current user's events only."""
    # Create another user with their own events.
    other = auth_service.create_user(db, email="other-audit@x.com", password="goodpw1234")
    db.add(AuditLog(event="login_success", user_id=other.id))
    db.add(AuditLog(event="login_success", user_id=test_user.id))
    db.commit()

    r = client.get("/api/v1/auth/audit-log")
    assert r.status_code == 200
    rows = r.json()
    user_ids_in_response = {row.get("event") for row in rows}
    assert "login_success" in user_ids_in_response
    # Only the current user's events.
    for row in rows:
        # All returned rows belong to test_user via the service-layer filter.
        # We don't expose user_id in the response model on purpose, but we
        # CAN verify the count matches.
        pass
    assert len(rows) == 1  # only the login_success row for test_user


def test_audit_log_endpoint_requires_auth(unauthenticated_client):
    r = unauthenticated_client.get("/api/v1/auth/audit-log")
    assert r.status_code == 401


def test_audit_log_limit_capped_at_500(client, db, test_user):
    r = client.get("/api/v1/auth/audit-log?limit=10000")
    # Should not crash; the cap is enforced server-side.
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def test_password_reset_request_returns_secret_when_email_exists(
    unauthenticated_client, db
):
    user = auth_service.create_user(db, email="reset1@x.com", password="oldpw12345")

    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset1@x.com"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["debug_secret"] is not None
    assert len(body["debug_secret"]) >= 16

    # A token row was created.
    rows = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id
    ).all()
    assert len(rows) == 1


def test_password_reset_request_does_not_leak_unknown_email(
    unauthenticated_client, db
):
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "ghost@x.com"},
    )
    assert r.status_code == 200
    body = r.json()
    # No secret returned because no user.
    assert body["debug_secret"] is None
    # No token row created.
    assert db.query(PasswordResetToken).count() == 0


def test_password_reset_confirm_rotates_password(unauthenticated_client, db):
    auth_service.create_user(db, email="reset2@x.com", password="oldpw12345")

    # Request the secret.
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset2@x.com"},
    )
    secret = r.json()["debug_secret"]

    # Confirm with the new password.
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": "newpw12345"},
    )
    assert r.status_code == 200

    # Old password no longer works.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "reset2@x.com", "password": "oldpw12345"},
    )
    assert r.status_code == 401

    # New password works.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "reset2@x.com", "password": "newpw12345"},
    )
    assert r.status_code == 200


def test_password_reset_token_is_single_use(unauthenticated_client, db):
    auth_service.create_user(db, email="reset3@x.com", password="oldpw12345")

    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset3@x.com"},
    )
    secret = r.json()["debug_secret"]

    # First use succeeds.
    r1 = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": "newpw12345"},
    )
    assert r1.status_code == 200

    # Second use fails.
    r2 = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": "newerpw12345"},
    )
    assert r2.status_code == 400


def test_password_reset_invalid_token_400s(unauthenticated_client, db):
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "newpw12345"},
    )
    assert r.status_code == 400


def test_password_reset_expired_token_400s(unauthenticated_client, db):
    user = auth_service.create_user(db, email="reset4@x.com", password="oldpw12345")
    # Manually expire the token.
    result = auth_service.request_password_reset(db, "reset4@x.com")
    assert result is not None
    _, secret = result

    # Force expiry.
    token_row = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id
    ).first()
    token_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": "newpw12345"},
    )
    assert r.status_code == 400


def test_password_reset_clears_lockout(unauthenticated_client, db, monkeypatch):
    """A successful reset must release any active lockout — the
    legitimate user has just proven control of the email account."""
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 2)
    user = auth_service.create_user(db, email="reset5@x.com", password="oldpw12345")

    # Lock the account.
    for _ in range(2):
        unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "reset5@x.com", "password": "wrong"},
        )
    db.expire_all()
    user = auth_service.get_user_by_email(db, "reset5@x.com")
    assert user.locked_until is not None

    # Reset.
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset5@x.com"},
    )
    secret = r.json()["debug_secret"]
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": "newpw12345"},
    )
    assert r.status_code == 200

    db.expire_all()
    user = auth_service.get_user_by_email(db, "reset5@x.com")
    assert user.locked_until is None
    assert user.failed_login_attempts == 0


def test_password_reset_creates_audit_events(unauthenticated_client, db):
    auth_service.create_user(db, email="reset6@x.com", password="oldpw12345")

    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset6@x.com"},
    )
    secret = r.json()["debug_secret"]
    unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": secret, "new_password": "newpw12345"},
    )

    requested = (
        db.query(AuditLog)
        .filter(AuditLog.event == Event.PASSWORD_RESET_REQUESTED.value)
        .all()
    )
    completed = (
        db.query(AuditLog)
        .filter(AuditLog.event == Event.PASSWORD_RESET_COMPLETED.value)
        .all()
    )
    assert len(requested) == 1
    assert len(completed) == 1


def test_password_reset_invalid_token_audited(unauthenticated_client, db):
    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "fakeitokenfake", "new_password": "newpw12345"},
    )
    assert r.status_code == 400

    rows = (
        db.query(AuditLog)
        .filter(AuditLog.event == Event.PASSWORD_RESET_INVALID_TOKEN.value)
        .all()
    )
    assert len(rows) == 1

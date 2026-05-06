"""Tests for T-5.4.6 — MFA / TOTP enrollment + login flow."""
from __future__ import annotations

import pyotp
import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.models.mfa_secret import MfaSecret
from app.services import auth_service, byok_service, mfa_service


@pytest.fixture(autouse=True)
def _stable_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", key)
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def _login_token(client, email: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200
    body = r.json()
    # Should be the no-MFA path so an access_token is returned directly.
    return body["access_token"]


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


def test_enroll_returns_secret_and_provisioning_uri(unauthenticated_client, db):
    auth_service.create_user(db, email="m1@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "m1@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["secret"], str) and len(body["secret"]) >= 16
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert "Pratidhvani" in body["provisioning_uri"]

    # Row created in disabled state.
    row = db.query(MfaSecret).first()
    assert row is not None
    assert row.enabled is False


def test_verify_enrollment_enables_mfa_and_returns_recovery_codes(
    unauthenticated_client, db
):
    auth_service.create_user(db, email="m2@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "m2@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]

    code = pyotp.TOTP(secret).now()
    r = unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": code},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    codes = body["recovery_codes"]
    assert len(codes) == mfa_service.RECOVERY_CODE_COUNT
    # Codes are uppercase hex.
    for c in codes:
        assert c == c.upper()
        int(c, 16)  # parses as hex

    # Server stores hashes only.
    row = db.query(MfaSecret).first()
    assert row.enabled is True
    import json as _json
    stored = _json.loads(row.recovery_codes_json)
    # No raw code is in the stored list.
    for c in codes:
        assert c not in stored


def test_verify_enrollment_with_wrong_code_fails(unauthenticated_client, db):
    auth_service.create_user(db, email="m3@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "m3@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}
    unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)

    r = unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": "000000"},
        headers=headers,
    )
    assert r.status_code == 400


def test_enroll_409_when_already_enabled(unauthenticated_client, db):
    auth_service.create_user(db, email="m4@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "m4@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]
    unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )

    # Second enrollment attempt without first disabling.
    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Status + disable
# ---------------------------------------------------------------------------


def test_mfa_status_initially_disabled(unauthenticated_client, db):
    auth_service.create_user(db, email="ms@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "ms@x.com", "goodpw1234")
    r = unauthenticated_client.get(
        "/api/v1/auth/mfa/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_disable_requires_valid_code(unauthenticated_client, db):
    auth_service.create_user(db, email="md@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "md@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]
    unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )

    # Wrong code → 400.
    r = unauthenticated_client.request(
        "DELETE",
        "/api/v1/auth/mfa",
        json={"code": "000000"},
        headers=headers,
    )
    assert r.status_code == 400

    # Correct code → 200 + row deleted.
    r = unauthenticated_client.request(
        "DELETE",
        "/api/v1/auth/mfa",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert r.status_code == 200
    assert db.query(MfaSecret).count() == 0


# ---------------------------------------------------------------------------
# Login flow
# ---------------------------------------------------------------------------


def test_login_without_mfa_returns_access_token(unauthenticated_client, db):
    auth_service.create_user(db, email="nomfa@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "nomfa@x.com", "password": "goodpw1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body.get("requires_mfa") is None or body.get("requires_mfa") is False


def test_login_with_mfa_returns_mfa_token(unauthenticated_client, db):
    auth_service.create_user(db, email="ml@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "ml@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}
    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]
    unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )

    # Now log in fresh — should return MFA-required.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "ml@x.com", "password": "goodpw1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["requires_mfa"] is True
    assert "mfa_token" in body
    assert "access_token" not in body


def test_login_mfa_step_with_totp_succeeds(unauthenticated_client, db):
    auth_service.create_user(db, email="mlt@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "mlt@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}
    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]
    unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )

    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "mlt@x.com", "password": "goodpw1234"},
    )
    mfa_token = r.json()["mfa_token"]

    r = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body


def test_login_mfa_step_with_recovery_code_succeeds_once(unauthenticated_client, db):
    auth_service.create_user(db, email="mr@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "mr@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}
    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]
    enrol = unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    recovery = enrol.json()["recovery_codes"]

    # Login flow → MFA token → recovery code consumed.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "mr@x.com", "password": "goodpw1234"},
    )
    mfa_token = r.json()["mfa_token"]
    r = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": recovery[0]},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()

    # Same code does NOT work a second time.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "mr@x.com", "password": "goodpw1234"},
    )
    mfa_token = r.json()["mfa_token"]
    r = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": recovery[0]},
    )
    assert r.status_code == 401


def test_login_mfa_step_invalid_code_401s(unauthenticated_client, db):
    auth_service.create_user(db, email="mb@x.com", password="goodpw1234")
    token = _login_token(unauthenticated_client, "mb@x.com", "goodpw1234")
    headers = {"Authorization": f"Bearer {token}"}
    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = r.json()["secret"]
    unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )

    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "mb@x.com", "password": "goodpw1234"},
    )
    mfa_token = r.json()["mfa_token"]

    r = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": "000000"},
    )
    assert r.status_code == 401


def test_login_mfa_step_with_bogus_token_401s(unauthenticated_client, db):
    r = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": "fake-token", "code": "123456"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Auth required on management endpoints
# ---------------------------------------------------------------------------


def test_mfa_management_endpoints_require_auth(unauthenticated_client):
    r1 = unauthenticated_client.post("/api/v1/auth/mfa/enroll")
    r2 = unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment", json={"code": "123456"}
    )
    r3 = unauthenticated_client.get("/api/v1/auth/mfa/status")
    r4 = unauthenticated_client.request(
        "DELETE", "/api/v1/auth/mfa", json={"code": "123456"}
    )
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 401
    assert r4.status_code == 401

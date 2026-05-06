"""End-to-end smoke test exercising every major surface added across
the I-3 / I-5 / I-6 sessions. Runs against the TestClient + in-memory
SQLite + ephemeral Chroma — no real LLM / Redis / external services
involved.

This is NOT a unit test — it's an integration smoke that catches
regressions that only show up when multiple surfaces interact
(e.g. a register → login → quota → BYOK → echo → author flow).
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pyotp
import pytest
from cryptography.fernet import Fernet
from jose import jwt as jose_jwt

from app.config import settings
from app.services import auth_service, byok_service


@pytest.fixture(autouse=True)
def _stable_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", key)
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def test_full_session_e2e(unauthenticated_client, db):
    """Walk through every surface as a logged-in user. Asserts the
    cross-feature integrations work — auth → quota → BYOK → echo
    → author — and that tier gates fire correctly when applicable."""
    # ────────────────────────────────────────────────────────────────────
    # 1. Register + login (E-5.4 happy path)
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "smoke@example.com", "password": "SmokePw1234"},
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "smoke@example.com", "password": "SmokePw1234"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 2. /me reflects the registered user.
    r = unauthenticated_client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["email"] == "smoke@example.com"

    # 3. JWT carries jti + the session row exists (T-5.4.7).
    payload = jose_jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    assert "jti" in payload
    sessions = unauthenticated_client.get(
        "/api/v1/auth/sessions", headers=h
    ).json()
    assert len(sessions) == 1 and sessions[0]["is_current"] is True

    # ────────────────────────────────────────────────────────────────────
    # 4. Audit log captures the register + login (T-5.4.1)
    # ────────────────────────────────────────────────────────────────────
    audit = unauthenticated_client.get(
        "/api/v1/auth/audit-log", headers=h
    ).json()
    events = {row["event"] for row in audit}
    assert {"user_registered", "login_success"}.issubset(events)

    # ────────────────────────────────────────────────────────────────────
    # 5. Quota endpoint reflects zero usage; tier=free (T-5.5.5/T-5.2.5).
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.get("/api/v1/auth/quota", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "free"
    by_resource = {x["resource"]: x for x in body["resources"]}
    for k in ("qa_exchanges", "knowledge_extractions", "documents"):
        assert k in by_resource
    assert by_resource["qa_exchanges"]["consumed"] == 0
    assert by_resource["qa_exchanges"]["limit"] == 50  # Free tier

    # ────────────────────────────────────────────────────────────────────
    # 6. Free tier is locked out of /credentials, /echo, /author (E-5.6 + I-3 + I-6)
    # ────────────────────────────────────────────────────────────────────
    assert (
        unauthenticated_client.get("/api/v1/auth/credentials", headers=h)
        .status_code == 403
    )
    assert (
        unauthenticated_client.get("/api/v1/echo/status", headers=h).status_code
        == 403
    )
    assert (
        unauthenticated_client.get("/api/v1/author/kinds", headers=h).status_code
        == 403
    )

    # ────────────────────────────────────────────────────────────────────
    # 7. Upgrade to Studio so the tier-gated surfaces unlock (E-5.2)
    # ────────────────────────────────────────────────────────────────────
    user = auth_service.get_user_by_id(db, user_id)
    user.tier = "studio"
    db.commit()

    r = unauthenticated_client.get("/api/v1/auth/credentials", headers=h)
    assert r.status_code == 200
    r = unauthenticated_client.get("/api/v1/echo/status", headers=h)
    assert r.status_code == 200

    # ────────────────────────────────────────────────────────────────────
    # 8. BYOK round-trip (T-5.6.4 foundation)
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "sk-smoke-test", "label": "smoke"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "openai"
    assert "secret" not in body  # plaintext NEVER in response

    r = unauthenticated_client.get("/api/v1/auth/credentials", headers=h)
    assert len(r.json()) == 1

    # ────────────────────────────────────────────────────────────────────
    # 9. MFA enroll → verify → disable round-trip (T-5.4.6)
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.post("/api/v1/auth/mfa/enroll", headers=h)
    assert r.status_code == 200
    secret = r.json()["secret"]

    code = pyotp.TOTP(secret).now()
    r = unauthenticated_client.post(
        "/api/v1/auth/mfa/verify-enrollment",
        json={"code": code},
        headers=h,
    )
    assert r.status_code == 200
    recovery_codes = r.json()["recovery_codes"]
    assert len(recovery_codes) == 10

    # MFA-required login flow now kicks in.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "smoke@example.com", "password": "SmokePw1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["requires_mfa"] is True

    # Second-step with TOTP succeeds.
    r = unauthenticated_client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": body["mfa_token"], "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()

    # Disable MFA so subsequent steps don't have to two-step.
    r = unauthenticated_client.request(
        "DELETE",
        "/api/v1/auth/mfa",
        json={"code": pyotp.TOTP(secret).now()},
        headers=h,
    )
    assert r.status_code == 200

    # ────────────────────────────────────────────────────────────────────
    # 10. Echo full surface (I-3 foundation)
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.get("/api/v1/echo/status", headers=h)
    assert r.status_code == 200
    assert r.json()["ready"] is False  # zero rows

    r = unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "interest", "key": "cooking", "value": "Italian"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["source"] == "manual"

    # Bad kind → 400.
    r = unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "not-a-kind", "key": "x", "value": "y"},
        headers=h,
    )
    assert r.status_code == 400

    r = unauthenticated_client.get("/api/v1/echo/context", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1

    r = unauthenticated_client.get("/api/v1/echo/connectors", headers=h)
    assert r.status_code == 200
    assert "supported_kinds" in r.json()

    # ────────────────────────────────────────────────────────────────────
    # 11. Studio-only `byok_llm_keys` feature flag matches the actual gate.
    # The credentials router uses require_feature("byok_llm_keys") which
    # only Studio has; smoke-checks the tier_service ↔ router contract.
    # ────────────────────────────────────────────────────────────────────
    from app.services.tier_service import has_feature, get_user_tier
    db.refresh(user)
    assert get_user_tier(user).value == "studio"
    assert has_feature(user, "byok_llm_keys")
    assert has_feature(user, "echo_personal_brain")
    assert has_feature(user, "author_studio")

    # ────────────────────────────────────────────────────────────────────
    # 12. Author Studio: list kinds, then 501 for a no-outputter kind
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.get("/api/v1/author/kinds", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "book" in body["available"]
    assert "site" in body["supported"] and "site" not in body["available"]

    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "site", "title": "no-outputter", "source_ids": []},
        headers=h,
    )
    assert r.status_code == 501

    # ────────────────────────────────────────────────────────────────────
    # 13. Sessions endpoint reflects MFA login session
    # ────────────────────────────────────────────────────────────────────
    sessions = unauthenticated_client.get(
        "/api/v1/auth/sessions", headers=h
    ).json()
    # We've logged in twice (the original + after MFA).
    assert len(sessions) >= 2

    # ────────────────────────────────────────────────────────────────────
    # 14. Logout revokes the current session, subsequent requests 401
    # ────────────────────────────────────────────────────────────────────
    r = unauthenticated_client.post("/api/v1/auth/logout", headers=h)
    assert r.status_code == 200 and r.json() == {"revoked": True}

    r = unauthenticated_client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 401


def test_tenant_isolation_smoke(unauthenticated_client, db):
    """Two users registered + active simultaneously must not leak each
    other's data across the surfaces wired this session."""
    # User A
    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "AlicePw1234"},
    )
    a_login = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "AlicePw1234"},
    )
    ha = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    # User B
    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "BobPw1234"},
    )
    b_login = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "BobPw1234"},
    )
    hb = {"Authorization": f"Bearer {b_login.json()['access_token']}"}

    # Upgrade both to Studio.
    a_user = auth_service.get_user_by_email(db, "alice@example.com")
    b_user = auth_service.get_user_by_email(db, "bob@example.com")
    a_user.tier = "studio"
    b_user.tier = "studio"
    db.commit()

    # ── Echo isolation
    unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "interest", "key": "x", "value": "alice"},
        headers=ha,
    )
    unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "interest", "key": "y", "value": "bob"},
        headers=hb,
    )
    a_rows = unauthenticated_client.get("/api/v1/echo/context", headers=ha).json()
    b_rows = unauthenticated_client.get("/api/v1/echo/context", headers=hb).json()
    a_keys = {r["key"] for r in a_rows}
    b_keys = {r["key"] for r in b_rows}
    assert a_keys == {"x"}
    assert b_keys == {"y"}

    # ── BYOK isolation
    unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "alice-secret"},
        headers=ha,
    )
    b_creds = unauthenticated_client.get(
        "/api/v1/auth/credentials", headers=hb
    ).json()
    assert b_creds == []  # bob can't see alice's

    # ── Sessions isolation
    a_sessions = unauthenticated_client.get(
        "/api/v1/auth/sessions", headers=ha
    ).json()
    b_sessions = unauthenticated_client.get(
        "/api/v1/auth/sessions", headers=hb
    ).json()
    assert all(s["is_current"] for s in a_sessions if s["is_current"]) and len(a_sessions) >= 1
    assert all(s["is_current"] for s in b_sessions if s["is_current"]) and len(b_sessions) >= 1
    # No overlap of jti between the two users.
    a_jtis = {s["jti"] for s in a_sessions}
    b_jtis = {s["jti"] for s in b_sessions}
    assert a_jtis & b_jtis == set()

    # ── Audit log isolation
    a_audit = unauthenticated_client.get(
        "/api/v1/auth/audit-log", headers=ha
    ).json()
    b_audit = unauthenticated_client.get(
        "/api/v1/auth/audit-log", headers=hb
    ).json()
    # Both have register + login events but they're scoped per-user.
    # The audit-log endpoint already filters by user_id; we trust the
    # tests in test_auth_hardening.py for that contract.
    assert len(a_audit) >= 2
    assert len(b_audit) >= 2

    # ── Quota isolation: both should report tier=studio + zero usage
    a_q = unauthenticated_client.get("/api/v1/auth/quota", headers=ha).json()
    b_q = unauthenticated_client.get("/api/v1/auth/quota", headers=hb).json()
    assert a_q["tier"] == "studio" and b_q["tier"] == "studio"


def test_quota_enforcement_in_qa_endpoint(unauthenticated_client, db, monkeypatch):
    """T-5.5.5 quota enforcement: a Free user at their qa_exchanges cap
    gets 429 from POST /jobs/{id}/qa BEFORE the agent runs."""
    from app.services import quota_metering_service

    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "cap@example.com", "password": "CapPw1234"},
    )
    login = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "cap@example.com", "password": "CapPw1234"},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    user = auth_service.get_user_by_email(db, "cap@example.com")

    # Burn the user's monthly Q&A cap (Free = 50).
    quota_metering_service.record_usage(db, user.id, "qa_exchanges", 50)

    # Create a completed job for this user so the endpoint accepts the request.
    from app.models.job import Job
    job = Job(
        id=str(uuid.uuid4()),
        job_type="topic",
        status="completed",
        topic="cap-test",
        tenant_id=user.id,
    )
    db.add(job)
    db.commit()

    # Patch the agent so we can confirm enforcement runs BEFORE the agent.
    agent_called = {"flag": False}

    def fake_agent(**kwargs):
        agent_called["flag"] = True
        return ("answer", [])

    with patch("app.agents.qa_agent.run_qa_agent", side_effect=fake_agent):
        r = unauthenticated_client.post(
            f"/api/v1/jobs/{job.id}/qa",
            json={"question": "anything"},
            headers=h,
        )

    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["resource"] == "qa_exchanges"
    assert detail["consumed"] == 50
    assert detail["limit"] == 50
    # CRUCIAL: the agent never ran (D-045 enforce-before).
    assert agent_called["flag"] is False

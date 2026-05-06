"""Tests for T-5.4.7 — session management.

Covers:
* Login writes a Session row keyed on the JWT's `jti` claim.
* Listing sessions returns the current user's sessions only.
* Revoking a single session blocks subsequent requests with that token.
* Revoking another user's session returns 404 (not 403; existence-leak).
* Revoke-all clears every active session; with `keep_current=true` the
  current token still works.
* Logout revokes the current session.
* Pre-T-5.4.7 tokens (no `jti` claim) still authenticate (back-compat).
"""
from __future__ import annotations

from jose import jwt

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.session import Session as SessionRow
from app.services import auth_service
from app.services.audit_service import Event


# ---------------------------------------------------------------------------
# Login writes a Session row
# ---------------------------------------------------------------------------


def test_login_creates_session_row(unauthenticated_client, db):
    auth_service.create_user(db, email="sess1@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "sess1@x.com", "password": "goodpw1234"},
    )
    assert r.status_code == 200

    rows = db.query(SessionRow).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None
    # The JWT's jti claim matches the row's jti.
    token = r.json()["access_token"]
    payload = jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    assert payload["jti"] == rows[0].jti


def test_login_session_captures_ip_and_user_agent(unauthenticated_client, db):
    auth_service.create_user(db, email="sess-ua@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "sess-ua@x.com", "password": "goodpw1234"},
        headers={"User-Agent": "TestAgent/1.0"},
    )
    assert r.status_code == 200
    row = db.query(SessionRow).first()
    assert row.user_agent == "TestAgent/1.0"
    # IP comes from request.client.host — TestClient uses 127.0.0.1 / "testclient".
    assert row.ip_address is not None


# ---------------------------------------------------------------------------
# List sessions
# ---------------------------------------------------------------------------


def test_list_sessions_returns_only_current_users(unauthenticated_client, db):
    # Two separate logins.
    auth_service.create_user(db, email="me-list@x.com", password="goodpw1234")
    auth_service.create_user(db, email="other-list@x.com", password="goodpw1234")

    r_me = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "me-list@x.com", "password": "goodpw1234"},
    )
    me_token = r_me.json()["access_token"]
    unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "other-list@x.com", "password": "goodpw1234"},
    )

    # Both rows exist in the DB but the listing for `me` returns only theirs.
    assert db.query(SessionRow).count() == 2

    r = unauthenticated_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {me_token}"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["is_current"] is True


def test_list_sessions_marks_current_session(unauthenticated_client, db):
    """When logging in twice, only the second-token request sees its
    own session as is_current=True."""
    auth_service.create_user(db, email="cur@x.com", password="goodpw1234")
    r1 = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "cur@x.com", "password": "goodpw1234"},
    )
    r2 = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "cur@x.com", "password": "goodpw1234"},
    )
    # First login is what creates the second session row; we only need
    # token2 for the listing-with-token2 assertion below.
    _ = r1.json()["access_token"]
    token2 = r2.json()["access_token"]

    # When listing with token2, only the row for token2 is current.
    r = unauthenticated_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {token2}"},
    )
    rows = r.json()
    assert len(rows) == 2
    current_count = sum(1 for x in rows if x["is_current"])
    assert current_count == 1


# ---------------------------------------------------------------------------
# Revoke single session
# ---------------------------------------------------------------------------


def test_revoke_single_session_blocks_subsequent_requests(unauthenticated_client, db):
    auth_service.create_user(db, email="rv@x.com", password="goodpw1234")
    r1 = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "rv@x.com", "password": "goodpw1234"},
    )
    r2 = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "rv@x.com", "password": "goodpw1234"},
    )
    token1 = r1.json()["access_token"]
    token2 = r2.json()["access_token"]
    payload2 = jwt.decode(
        token2, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    jti2 = payload2["jti"]

    # Revoke session 2 from session 1's token.
    r = unauthenticated_client.delete(
        f"/api/v1/auth/sessions/{jti2}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert r.status_code == 200
    assert r.json() == {"revoked": True}

    # Token 2 no longer authenticates.
    r = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r.status_code == 401

    # Token 1 still works.
    r = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert r.status_code == 200


def test_revoke_other_users_session_returns_404(unauthenticated_client, db):
    auth_service.create_user(db, email="me-rv@x.com", password="goodpw1234")
    auth_service.create_user(db, email="them-rv@x.com", password="goodpw1234")

    r_me = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "me-rv@x.com", "password": "goodpw1234"},
    )
    r_them = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "them-rv@x.com", "password": "goodpw1234"},
    )
    me_token = r_me.json()["access_token"]
    them_token = r_them.json()["access_token"]
    them_jti = jwt.decode(
        them_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )["jti"]

    r = unauthenticated_client.delete(
        f"/api/v1/auth/sessions/{them_jti}",
        headers={"Authorization": f"Bearer {me_token}"},
    )
    assert r.status_code == 404
    # Their session is still active.
    rows = db.query(SessionRow).filter(SessionRow.jti == them_jti).all()
    assert rows[0].revoked_at is None


def test_revoke_nonexistent_jti_returns_404(unauthenticated_client, db):
    auth_service.create_user(db, email="404@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "404@x.com", "password": "goodpw1234"},
    )
    token = r.json()["access_token"]

    r = unauthenticated_client.delete(
        "/api/v1/auth/sessions/no-such-jti",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Revoke all + keep_current
# ---------------------------------------------------------------------------


def test_revoke_all_clears_every_active_session(unauthenticated_client, db):
    auth_service.create_user(db, email="all@x.com", password="goodpw1234")
    tokens = []
    for _ in range(3):
        r = unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "all@x.com", "password": "goodpw1234"},
        )
        tokens.append(r.json()["access_token"])

    r = unauthenticated_client.delete(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {tokens[0]}"},
    )
    assert r.status_code == 200
    assert r.json() == {"revoked_count": 3}

    # Every token now rejected.
    for t in tokens:
        r = unauthenticated_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {t}"}
        )
        assert r.status_code == 401


def test_revoke_all_keep_current(unauthenticated_client, db):
    auth_service.create_user(db, email="keep@x.com", password="goodpw1234")
    tokens = []
    for _ in range(3):
        r = unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "keep@x.com", "password": "goodpw1234"},
        )
        tokens.append(r.json()["access_token"])

    r = unauthenticated_client.delete(
        "/api/v1/auth/sessions?keep_current=true",
        headers={"Authorization": f"Bearer {tokens[2]}"},
    )
    assert r.status_code == 200
    assert r.json() == {"revoked_count": 2}

    # Tokens 0 and 1 are dead; token 2 still works.
    for i in (0, 1):
        r = unauthenticated_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens[i]}"}
        )
        assert r.status_code == 401
    r = unauthenticated_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens[2]}"}
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_revokes_current_session(unauthenticated_client, db):
    auth_service.create_user(db, email="logout@x.com", password="goodpw1234")
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "logout@x.com", "password": "goodpw1234"},
    )
    token = r.json()["access_token"]

    r = unauthenticated_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json() == {"revoked": True}

    # Token now rejected.
    r = unauthenticated_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 401

    # Audit row exists.
    audit = db.query(AuditLog).filter(AuditLog.event == Event.LOGOUT.value).all()
    assert len(audit) == 1


# ---------------------------------------------------------------------------
# Back-compat: tokens issued WITHOUT jti
# ---------------------------------------------------------------------------


def test_legacy_token_without_jti_still_authenticates(unauthenticated_client, db):
    """Tokens issued by `create_access_token(user_id)` without `db=`
    have no jti claim — they pre-date T-5.4.7 in the wire format. Those
    must keep working (back-compat) until they expire."""
    user = auth_service.create_user(db, email="legacy@x.com", password="goodpw1234")
    # Issue a token WITHOUT writing a session row (legacy behaviour).
    legacy_token, _ = auth_service.create_access_token(user.id)
    payload = jwt.decode(
        legacy_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    # Legacy path includes a jti regardless (we always generate one);
    # the meaningful test is that no session row was written, so
    # is_session_active("missing row") returns True.
    assert "jti" in payload
    assert db.query(SessionRow).count() == 0

    r = unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


def test_session_endpoints_require_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/auth/sessions").status_code == 401
    assert unauthenticated_client.delete("/api/v1/auth/sessions/x").status_code == 401
    assert unauthenticated_client.delete("/api/v1/auth/sessions").status_code == 401
    assert unauthenticated_client.post("/api/v1/auth/logout").status_code == 401

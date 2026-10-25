"""T-5.2.8 / D-111 — the tier switch and the restart are operator-only.

Checked at the production callers: ``PUT /auth/me/tier``, ``POST
/admin/restart`` and ``GET /auth/me`` (which tells the Subscription page
whether to offer the switch). The rule itself is in
``test_services/test_auth_service.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.models.audit_log import AuditLog
from app.services import auth_service


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

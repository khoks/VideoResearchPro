"""Tests for E-5.6 BYOK credentials router.

Covers:
* All endpoints require auth (401 unauthenticated).
* All endpoints require the `byok_llm_keys` feature → Studio tier.
* PUT roundtrips through encrypt + persist; the secret is never
  returned in the response.
* DELETE removes the row; subsequent DELETE returns deleted=False.
* Unknown provider → 400.
* GET /providers returns the supported set without leaking server
  state.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.services import auth_service, byok_service


@pytest.fixture(autouse=True)
def _stable_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", key)
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def _studio_token(db, email: str = "studio@x.com") -> str:
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return token


def _free_token(db, email: str = "free@x.com") -> str:
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    # tier defaults to "free"
    token, _ = auth_service.create_access_token(user.id)
    return token


# ---------------------------------------------------------------------------
# Auth + tier gating
# ---------------------------------------------------------------------------


def test_credentials_endpoints_require_auth(unauthenticated_client):
    r1 = unauthenticated_client.get("/api/v1/auth/credentials")
    r2 = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai", json={"secret": "x"}
    )
    r3 = unauthenticated_client.delete("/api/v1/auth/credentials/openai")
    r4 = unauthenticated_client.get("/api/v1/auth/credentials/providers")
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 401
    assert r4.status_code == 401


def test_credentials_endpoints_require_studio_tier(unauthenticated_client, db):
    token = _free_token(db, email="free-creds@x.com")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = unauthenticated_client.get("/api/v1/auth/credentials", headers=headers)
    r2 = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "x"},
        headers=headers,
    )
    assert r1.status_code == 403
    assert r2.status_code == 403
    # The 403 messages should mention the missing feature, not leak
    # other server state.
    assert "byok_llm_keys" in r1.json()["detail"]


# ---------------------------------------------------------------------------
# CRUD happy path
# ---------------------------------------------------------------------------


def test_put_credential_persists_encrypted(unauthenticated_client, db):
    token = _studio_token(db, email="studio1@x.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "sk-real-secret-here", "label": "my OAI key"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "openai"
    assert body["label"] == "my OAI key"
    assert body["has_secret"] is True
    # Secret never echoed.
    assert "secret" not in body
    assert "encrypted_secret" not in body

    # Service-layer roundtrip works.
    user = auth_service.get_user_by_email(db, "studio1@x.com")
    assert byok_service.get_credential(db, user_id=user.id, provider="openai") == (
        "sk-real-secret-here"
    )


def test_get_credentials_lists_users_keys(unauthenticated_client, db):
    token = _studio_token(db, email="studio2@x.com")
    headers = {"Authorization": f"Bearer {token}"}

    unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "a"},
        headers=headers,
    )
    unauthenticated_client.put(
        "/api/v1/auth/credentials/anthropic",
        json={"secret": "b", "label": "claude"},
        headers=headers,
    )

    r = unauthenticated_client.get("/api/v1/auth/credentials", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    providers = {row["provider"] for row in rows}
    assert providers == {"openai", "anthropic"}


def test_delete_credential(unauthenticated_client, db):
    token = _studio_token(db, email="studio3@x.com")
    headers = {"Authorization": f"Bearer {token}"}

    unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "to-delete"},
        headers=headers,
    )
    r1 = unauthenticated_client.delete(
        "/api/v1/auth/credentials/openai", headers=headers
    )
    r2 = unauthenticated_client.delete(
        "/api/v1/auth/credentials/openai", headers=headers
    )
    assert r1.status_code == 200 and r1.json() == {"deleted": True}
    assert r2.status_code == 200 and r2.json() == {"deleted": False}


def test_unknown_provider_returns_400(unauthenticated_client, db):
    token = _studio_token(db, email="studio4@x.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.put(
        "/api/v1/auth/credentials/bogus_provider",
        json={"secret": "x"},
        headers=headers,
    )
    assert r.status_code == 400


def test_list_providers(unauthenticated_client, db):
    token = _studio_token(db, email="studio5@x.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = unauthenticated_client.get(
        "/api/v1/auth/credentials/providers", headers=headers
    )
    assert r.status_code == 200
    providers = r.json()
    assert "openai" in providers
    assert "anthropic" in providers
    assert "google" in providers
    assert "local" in providers


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


def test_user_cannot_see_other_users_credentials(unauthenticated_client, db):
    me_token = _studio_token(db, email="me-cred@x.com")
    other_token = _studio_token(db, email="other-cred@x.com")

    unauthenticated_client.put(
        "/api/v1/auth/credentials/openai",
        json={"secret": "mine"},
        headers={"Authorization": f"Bearer {me_token}"},
    )

    r = unauthenticated_client.get(
        "/api/v1/auth/credentials",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 200
    assert r.json() == []

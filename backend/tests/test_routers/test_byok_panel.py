"""The keys panel on /account/ai-models (E-5.6 BYOK), at its callers.

The panel reads ``GET /settings/llm`` for which providers take a key and
whether stored keys outlive a restart, and writes through
``/auth/credentials``. These tests pin:

* ``byok.keys_persist`` follows ``BYOK_ENCRYPTION_KEY``: true for a valid
  Fernet key, false when unset or malformed (a malformed key fails every
  save, so reporting it as persistent would be wrong).
* ``byok.providers`` is exactly the set the LLM call path reads a stored key
  for, so the panel never offers a key that would be stored and ignored.
* A refused save never quotes the submitted key back, and no request in the
  panel's flow logs it or returns it.

Every "key" here is an obviously fake placeholder; no real key material.
"""
from __future__ import annotations

import logging

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.routers.credentials import SECRET_MAX_CHARS
from app.services import auth_service, byok_service, llm_service

FAKE_KEY = "fake-placeholder-not-a-key-7f3a"


@pytest.fixture
def stable_key(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def _studio_headers(db, email: str) -> tuple[dict[str, str], str]:
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}, user.id


# ---------------------------------------------------------------------------
# GET /settings/llm → byok
# ---------------------------------------------------------------------------


def test_settings_report_keys_persist_with_a_valid_key(client, test_user, stable_key):
    body = client.get("/api/v1/settings/llm").json()
    assert body["byok"]["keys_persist"] is True


def test_settings_report_keys_do_not_persist_without_a_key(client, test_user, monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", None)
    byok_service._get_fernet.cache_clear()
    try:
        body = client.get("/api/v1/settings/llm").json()
        assert body["byok"]["keys_persist"] is False
    finally:
        byok_service._get_fernet.cache_clear()


def test_settings_report_a_malformed_key_as_not_persisting(client, test_user, monkeypatch):
    # Set, but not 32 url-safe base64 bytes: a truthiness check would say
    # "persists" while every save fails.
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", "not-a-fernet-key")
    byok_service._get_fernet.cache_clear()
    try:
        body = client.get("/api/v1/settings/llm").json()
        assert body["byok"]["keys_persist"] is False
    finally:
        byok_service._get_fernet.cache_clear()


def test_settings_byok_carries_no_key_material(client, test_user, db, stable_key):
    byok_service.set_credential(db, user_id=test_user.id, provider="openai", secret=FAKE_KEY)
    r = client.get("/api/v1/settings/llm")
    assert set(r.json()["byok"]) == {"providers", "keys_persist"}
    assert FAKE_KEY not in r.text
    assert str(settings.BYOK_ENCRYPTION_KEY) not in r.text


def test_listed_providers_are_exactly_the_ones_a_call_reads(client, test_user, db, stable_key):
    """The panel lists ``byok.providers``. Each one's stored key must reach
    the LLM call path, and every other supported provider's must not, or
    the panel would offer a key that is stored and then ignored."""
    listed = client.get("/api/v1/settings/llm").json()["byok"]["providers"]
    assert listed == sorted(listed)
    assert set(listed) <= byok_service.SUPPORTED_PROVIDERS

    test_user.tier = "studio"
    db.commit()
    for provider in sorted(byok_service.SUPPORTED_PROVIDERS):
        byok_service.set_credential(
            db, user_id=test_user.id, provider=provider, secret=f"{FAKE_KEY}-{provider}"
        )
    for provider in sorted(byok_service.SUPPORTED_PROVIDERS):
        resolved = llm_service._resolve_byok_api_key(provider, test_user.id, db)
        if provider in listed:
            assert resolved == f"{FAKE_KEY}-{provider}", provider
        else:
            assert resolved is None, provider
    assert "local" not in listed


# ---------------------------------------------------------------------------
# PUT /auth/credentials/{provider} — never echo the key
# ---------------------------------------------------------------------------


def test_over_long_key_is_refused_without_quoting_it(unauthenticated_client, db, stable_key):
    headers, user_id = _studio_headers(db, "long-key@x.com")
    too_long = FAKE_KEY + "x" * SECRET_MAX_CHARS
    r = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai", json={"secret": too_long}, headers=headers
    )
    # A pydantic length constraint would answer 422 with the key as `input`.
    assert r.status_code == 400
    assert FAKE_KEY not in r.text
    assert "too long" in r.json()["detail"]
    assert byok_service.get_credential(db, user_id=user_id, provider="openai") is None


def test_key_at_the_limit_is_accepted(unauthenticated_client, db, stable_key):
    headers, user_id = _studio_headers(db, "limit-key@x.com")
    at_limit = "k" * SECRET_MAX_CHARS
    r = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai", json={"secret": at_limit}, headers=headers
    )
    assert r.status_code == 200
    assert byok_service.get_credential(db, user_id=user_id, provider="openai") == at_limit


def test_blank_key_is_refused_without_storing(unauthenticated_client, db, stable_key):
    headers, user_id = _studio_headers(db, "blank-key@x.com")
    r = unauthenticated_client.put(
        "/api/v1/auth/credentials/openai", json={"secret": "   "}, headers=headers
    )
    assert r.status_code == 400
    assert byok_service.get_credential(db, user_id=user_id, provider="openai") is None


def test_panel_flow_never_returns_or_logs_the_key(unauthenticated_client, db, stable_key):
    """Set, list, replace and remove, as the panel does: no response body
    and no log record carries the key."""
    headers, _ = _studio_headers(db, "flow-key@x.com")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    root = logging.getLogger()
    handler = _Capture(level=logging.DEBUG)
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        responses = [
            unauthenticated_client.put(
                "/api/v1/auth/credentials/anthropic",
                json={"secret": FAKE_KEY, "label": "work"},
                headers=headers,
            ),
            unauthenticated_client.get("/api/v1/auth/credentials", headers=headers),
            unauthenticated_client.put(
                "/api/v1/auth/credentials/anthropic",
                json={"secret": FAKE_KEY + "-2"},
                headers=headers,
            ),
            unauthenticated_client.get("/api/v1/auth/credentials", headers=headers),
            unauthenticated_client.delete("/api/v1/auth/credentials/anthropic", headers=headers),
        ]
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    assert [r.status_code for r in responses] == [200, 200, 200, 200, 200]
    for r in responses:
        assert FAKE_KEY not in r.text
    listed = responses[1].json()
    assert [row["provider"] for row in listed] == ["anthropic"]
    assert listed[0]["label"] == "work"
    assert listed[0]["has_secret"] is True
    # The replace bumps the "last changed" time the panel shows.
    assert responses[3].json()[0]["updated_at"] >= listed[0]["updated_at"]
    for record in records:
        assert FAKE_KEY not in record.getMessage()
        assert FAKE_KEY not in repr(record.args)

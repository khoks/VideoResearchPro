"""Tests for T-5.6.4 — BYOK LLM resolution-path integration.

Covers:
* `byok_context(...)` sets the tenant_id + db so nested `get_llm_for`
  calls pick them up automatically.
* `get_llm_for(...)` looks up the user's BYOK credential when both
  args are available (via context or explicit), and threads it into the
  built provider client.
* Free / Pro tier users (without `byok_llm_keys` feature) do NOT have
  their stored credentials honoured — defense-in-depth: a downgrade
  shouldn't keep an old credential live.
* Encryption-key rotation tolerance: if the stored ciphertext can't be
  decrypted, fall back to the install-wide env-var key.
* Local provider IGNORES BYOK — local servers are install-wide.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.services import auth_service, byok_service, llm_service
from app.services.llm_routing import UseCaseConfig
from app.services.tier_service import Tier


@pytest.fixture(autouse=True)
def _stable_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", key)
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


# ---------------------------------------------------------------------------
# Context var get/set
# ---------------------------------------------------------------------------


def test_byok_context_sets_and_resets():
    """Inside the with block, `_byok_context.get()` returns the values;
    after exit it returns the original (None, None)."""
    assert llm_service._byok_context.get() == (None, None)

    with llm_service.byok_context("user-A", "db-handle"):
        assert llm_service._byok_context.get() == ("user-A", "db-handle")

    assert llm_service._byok_context.get() == (None, None)


def test_byok_context_nests_correctly():
    """Nested contexts restore the outer value on inner exit."""
    with llm_service.byok_context("outer", "db1"):
        with llm_service.byok_context("inner", "db2"):
            assert llm_service._byok_context.get() == ("inner", "db2")
        assert llm_service._byok_context.get() == ("outer", "db1")


def test_byok_context_resets_on_exception():
    with pytest.raises(RuntimeError):
        with llm_service.byok_context("u", "d"):
            raise RuntimeError("boom")
    # Reset happened despite the exception.
    assert llm_service._byok_context.get() == (None, None)


# ---------------------------------------------------------------------------
# _resolve_byok_api_key
# ---------------------------------------------------------------------------


def test_resolve_byok_api_key_returns_none_when_no_user_context():
    """No tenant_id → no BYOK lookup."""
    assert llm_service._resolve_byok_api_key("openai", None, None) is None


def test_resolve_byok_api_key_returns_none_for_local_provider(db):
    """Local servers are install-wide; BYOK doesn't apply."""
    user = auth_service.create_user(db, email="local@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    byok_service.set_credential(db, user_id=user.id, provider="openai", secret="sk")
    assert llm_service._resolve_byok_api_key("local", user.id, db) is None


def test_resolve_byok_api_key_returns_none_for_free_user(db):
    """Free / Pro tiers don't have the byok_llm_keys feature; even if a
    row exists in user_credentials it must NOT be honoured."""
    user = auth_service.create_user(db, email="free-byok@x.com", password="pw" * 6)
    # tier defaults to free
    byok_service.set_credential(db, user_id=user.id, provider="openai", secret="sk")
    assert llm_service._resolve_byok_api_key("openai", user.id, db) is None


def test_resolve_byok_api_key_returns_none_for_pro_user(db):
    """Pro tier doesn't grant byok_llm_keys either — Studio-only feature."""
    user = auth_service.create_user(db, email="pro-byok@x.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()
    byok_service.set_credential(db, user_id=user.id, provider="openai", secret="sk")
    assert llm_service._resolve_byok_api_key("openai", user.id, db) is None


def test_resolve_byok_api_key_returns_secret_for_studio_user(db):
    user = auth_service.create_user(db, email="studio-byok@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    byok_service.set_credential(
        db, user_id=user.id, provider="openai", secret="sk-mine"
    )
    assert (
        llm_service._resolve_byok_api_key("openai", user.id, db) == "sk-mine"
    )


def test_resolve_byok_api_key_returns_none_when_no_credential_stored(db):
    user = auth_service.create_user(db, email="nokey@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    # No set_credential call.
    assert llm_service._resolve_byok_api_key("openai", user.id, db) is None


def test_resolve_byok_api_key_returns_none_on_decrypt_failure(db, monkeypatch):
    """If ciphertext is undecryptable (key rotation), fall back to None
    so the install-wide env-var path takes over."""
    user = auth_service.create_user(db, email="rotate@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    byok_service.set_credential(db, user_id=user.id, provider="openai", secret="sk")

    # Rotate the Fernet key; existing ciphertext now undecryptable.
    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", new_key)
    byok_service._get_fernet.cache_clear()

    assert llm_service._resolve_byok_api_key("openai", user.id, db) is None


# ---------------------------------------------------------------------------
# get_llm_for end-to-end
# ---------------------------------------------------------------------------


def test_get_llm_for_uses_byok_when_context_set(db):
    """A Studio user with a stored OpenAI key gets it threaded into the
    built ChatOpenAI client when their context is set."""
    user = auth_service.create_user(db, email="e2e@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    byok_service.set_credential(
        db, user_id=user.id, provider="openai", secret="sk-byok-secret"
    )

    captured = {}

    def fake_build_openai(model, temperature, max_tokens, **kw):
        captured["api_key"] = kw.get("api_key")
        return object()  # opaque client; we only assert on the kwargs

    with patch.object(llm_service, "_build_openai", side_effect=fake_build_openai):
        with patch.object(
            llm_service, "resolve_config",
            return_value=UseCaseConfig(
                provider="openai", model="gpt-x", reasoning="off"
            ),
        ):
            with llm_service.byok_context(user.id, db):
                llm_service.get_llm_for("qa_formulate_answer")

    assert captured["api_key"] == "sk-byok-secret"


def test_get_llm_for_falls_back_to_env_when_no_byok(db):
    """A Studio user with NO credential stored — the API key passed to
    the builder is None (which signals "use env var" downstream)."""
    user = auth_service.create_user(db, email="e2e2@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()

    captured = {}

    def fake_build_openai(model, temperature, max_tokens, **kw):
        captured["api_key"] = kw.get("api_key")
        return object()

    with patch.object(llm_service, "_build_openai", side_effect=fake_build_openai):
        with patch.object(
            llm_service, "resolve_config",
            return_value=UseCaseConfig(
                provider="openai", model="gpt-x", reasoning="off"
            ),
        ):
            with llm_service.byok_context(user.id, db):
                llm_service.get_llm_for("qa_formulate_answer")

    # No stored credential → api_key=None → _build_openai falls back to env var.
    assert captured["api_key"] is None


def test_get_llm_for_does_not_apply_byok_when_no_context(db):
    """Without a byok_context, get_llm_for behaves as before — never
    consults the credential table."""
    user = auth_service.create_user(db, email="ctx@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    byok_service.set_credential(
        db, user_id=user.id, provider="openai", secret="sk-stored"
    )

    captured = {}

    def fake_build_openai(model, temperature, max_tokens, **kw):
        captured["api_key"] = kw.get("api_key")
        return object()

    with patch.object(llm_service, "_build_openai", side_effect=fake_build_openai):
        with patch.object(
            llm_service, "resolve_config",
            return_value=UseCaseConfig(
                provider="openai", model="gpt-x", reasoning="off"
            ),
        ):
            # No byok_context — explicit args also None.
            llm_service.get_llm_for("qa_formulate_answer")

    # No context → no BYOK lookup → api_key is None (env-var fallback).
    assert captured["api_key"] is None


def test_get_llm_for_explicit_args_take_precedence(db):
    """Passing tenant_id+db as explicit kwargs is equivalent to using
    the context var (used in tests + tasks where context isn't set)."""
    user = auth_service.create_user(db, email="exp@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    byok_service.set_credential(
        db, user_id=user.id, provider="anthropic", secret="sk-ant-mine"
    )

    captured = {}

    def fake_build_anthropic(model, temperature, max_tokens, **kw):
        captured["api_key"] = kw.get("api_key")
        return object()

    with patch.object(
        llm_service, "_build_anthropic", side_effect=fake_build_anthropic
    ):
        with patch.object(
            llm_service, "resolve_config",
            return_value=UseCaseConfig(
                provider="anthropic", model="claude-x", reasoning="off"
            ),
        ):
            llm_service.get_llm_for(
                "qa_formulate_answer", tenant_id=user.id, db=db
            )

    assert captured["api_key"] == "sk-ant-mine"


def test_get_llm_for_partial_args_warns_and_skips_byok(db, caplog):
    """Passing only tenant_id (no db) is a programming error; we warn
    and don't perform the lookup (api_key=None)."""
    captured = {}

    def fake_build_openai(model, temperature, max_tokens, **kw):
        captured["api_key"] = kw.get("api_key")
        return object()

    with patch.object(llm_service, "_build_openai", side_effect=fake_build_openai):
        with patch.object(
            llm_service, "resolve_config",
            return_value=UseCaseConfig(
                provider="openai", model="gpt-x", reasoning="off"
            ),
        ):
            with caplog.at_level("WARNING"):
                llm_service.get_llm_for(
                    "qa_formulate_answer",
                    tenant_id="some-user",
                    # db= intentionally omitted
                )

    assert captured["api_key"] is None
    assert any(
        "only one of (tenant_id, db) provided" in r.message
        for r in caplog.records
    )

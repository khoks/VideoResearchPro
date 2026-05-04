"""Tests for E-5.6 BYOK credentials service.

Covers:
* Encryption round-trip — encrypt → decrypt yields the original
  plaintext.
* set_credential is upsert: same (user_id, provider) replaces.
* get_credential returns None when row missing.
* get_credential returns None gracefully when ciphertext is unreadable
  (e.g. encryption key rotated mid-flight).
* delete_credential semantics.
* Provider validation rejects unknown providers.
* Empty secret rejected.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.models.user_credential import UserCredential
from app.services import auth_service, byok_service
from app.services.byok_service import (
    UnsupportedProviderError,
    decrypt_secret,
    delete_credential,
    encrypt_secret,
    get_credential,
    list_for_user,
    set_credential,
)


@pytest.fixture(autouse=True)
def _stable_fernet_key(monkeypatch):
    """Ensure tests use a deterministic Fernet key so encrypt/decrypt
    round-trips work across the per-test process state."""
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", key)
    # Reset the lru_cache so the new key is picked up.
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


# ---------------------------------------------------------------------------
# Encryption round-trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip():
    plaintext = "sk-ant-api03-some-very-long-secret-token-here"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext != plaintext
    assert len(ciphertext) > len(plaintext)
    assert decrypt_secret(ciphertext) == plaintext


def test_encryption_is_non_deterministic():
    """Fernet uses a random IV — same plaintext yields different
    ciphertext on each encrypt call."""
    p = "the-same-secret"
    a = encrypt_secret(p)
    b = encrypt_secret(p)
    assert a != b
    # But both decrypt to the same plaintext.
    assert decrypt_secret(a) == p
    assert decrypt_secret(b) == p


# ---------------------------------------------------------------------------
# Service CRUD
# ---------------------------------------------------------------------------


def test_set_and_get_credential(db):
    user = auth_service.create_user(db, email="byok@x.com", password="pw" * 6)
    set_credential(
        db, user_id=user.id, provider="openai", secret="sk-real-secret"
    )
    got = get_credential(db, user_id=user.id, provider="openai")
    assert got == "sk-real-secret"


def test_get_credential_returns_none_when_missing(db):
    user = auth_service.create_user(db, email="byok2@x.com", password="pw" * 6)
    assert get_credential(db, user_id=user.id, provider="openai") is None


def test_set_credential_is_upsert(db):
    user = auth_service.create_user(db, email="byok3@x.com", password="pw" * 6)
    set_credential(db, user_id=user.id, provider="openai", secret="sk-v1")
    set_credential(db, user_id=user.id, provider="openai", secret="sk-v2")
    assert get_credential(db, user_id=user.id, provider="openai") == "sk-v2"

    # Only one row in the DB (uniqueness enforced).
    rows = (
        db.query(UserCredential)
        .filter(
            UserCredential.user_id == user.id,
            UserCredential.provider == "openai",
        )
        .all()
    )
    assert len(rows) == 1


def test_set_credential_with_label(db):
    user = auth_service.create_user(db, email="byok4@x.com", password="pw" * 6)
    set_credential(
        db,
        user_id=user.id,
        provider="anthropic",
        secret="sk-ant-anything",
        label="my team org",
    )
    rows = list_for_user(db, user.id)
    assert len(rows) == 1
    assert rows[0].label == "my team org"


def test_delete_credential_returns_true_when_existing(db):
    user = auth_service.create_user(db, email="byok5@x.com", password="pw" * 6)
    set_credential(db, user_id=user.id, provider="openai", secret="sk")
    assert delete_credential(db, user_id=user.id, provider="openai") is True
    assert get_credential(db, user_id=user.id, provider="openai") is None


def test_delete_credential_returns_false_when_missing(db):
    user = auth_service.create_user(db, email="byok6@x.com", password="pw" * 6)
    assert delete_credential(db, user_id=user.id, provider="openai") is False


def test_list_for_user_returns_only_their_rows(db):
    me = auth_service.create_user(db, email="me-byok@x.com", password="pw" * 6)
    other = auth_service.create_user(db, email="other-byok@x.com", password="pw" * 6)
    set_credential(db, user_id=me.id, provider="openai", secret="my")
    set_credential(db, user_id=other.id, provider="openai", secret="not-mine")

    mine = list_for_user(db, me.id)
    assert len(mine) == 1
    assert mine[0].provider == "openai"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unsupported_provider_raises(db):
    user = auth_service.create_user(db, email="bad@x.com", password="pw" * 6)
    with pytest.raises(UnsupportedProviderError):
        set_credential(db, user_id=user.id, provider="bogus", secret="x")
    with pytest.raises(UnsupportedProviderError):
        get_credential(db, user_id=user.id, provider="bogus")
    with pytest.raises(UnsupportedProviderError):
        delete_credential(db, user_id=user.id, provider="bogus")


def test_empty_secret_rejected(db):
    user = auth_service.create_user(db, email="empty@x.com", password="pw" * 6)
    with pytest.raises(ValueError):
        set_credential(db, user_id=user.id, provider="openai", secret="")
    with pytest.raises(ValueError):
        set_credential(db, user_id=user.id, provider="openai", secret="   ")


# ---------------------------------------------------------------------------
# Encryption-key rotation tolerance
# ---------------------------------------------------------------------------


def test_get_credential_returns_none_on_undecryptable_ciphertext(db, monkeypatch):
    user = auth_service.create_user(db, email="rotate@x.com", password="pw" * 6)
    set_credential(db, user_id=user.id, provider="openai", secret="sk-rotate")

    # Rotate the Fernet key. Existing ciphertext is now undecryptable.
    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", new_key)
    byok_service._get_fernet.cache_clear()

    # The service does NOT raise — it returns None and logs.
    assert get_credential(db, user_id=user.id, provider="openai") is None

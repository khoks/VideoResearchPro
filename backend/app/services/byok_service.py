"""BYOK (Bring Your Own Key) credential service — E-5.6.

Per-user, per-provider API keys with encryption at rest. The plaintext
secret is **never** persisted; the database holds only the
``cryptography.fernet.Fernet`` ciphertext.

Encryption is keyed off ``BYOK_ENCRYPTION_KEY`` from settings. In
production, operators MUST set this to a stable, base64-url-safe
32-byte key; rotating it invalidates every stored credential. For
dev / self-host without explicit configuration, a process-local
random key is generated at startup — credentials persisted to the DB
won't survive a process restart in that mode, which is the intended
"don't fail loudly, but tell the operator" posture.

Threat model:
- DB-leak protection: ciphertext alone is unusable without
  ``BYOK_ENCRYPTION_KEY``.
- The key itself lives in the environment (or secrets manager on
  SaaS). Compromise of *both* the DB and the env is required to
  recover the secrets.
- Active-use leakage: secrets ARE decrypted in memory at the LLM
  call site (T-5.6.X — the consumer). Memory dumps post-decrypt are
  out of scope here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user_credential import UserCredential

logger = logging.getLogger(__name__)


# Providers that this BYOK system supports — must match the providers
# registered in `app/services/llm_routing.py::_provider_factories`.
SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {"openai", "anthropic", "google", "local"}
)


class UnsupportedProviderError(ValueError):
    pass


class EncryptionConfigurationError(RuntimeError):
    """Raised when ``BYOK_ENCRYPTION_KEY`` is set to an invalid
    Fernet key (not 32 url-safe base64-encoded bytes)."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Cached Fernet instance. Reads ``BYOK_ENCRYPTION_KEY`` from
    settings; falls back to a process-local key if unset (with a loud
    warning so operators know stored credentials won't persist across
    restarts)."""
    raw = getattr(settings, "BYOK_ENCRYPTION_KEY", None)
    if raw:
        try:
            return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
        except (ValueError, TypeError) as e:
            raise EncryptionConfigurationError(
                f"BYOK_ENCRYPTION_KEY is not a valid Fernet key: {e}"
            ) from e
    # No key configured — generate one for this process. Stored
    # credentials will be unreadable after restart. We log this so
    # operators notice and configure a stable key.
    logger.warning(
        "BYOK_ENCRYPTION_KEY is not configured. A process-local key has "
        "been generated for development convenience; any stored BYOK "
        "credentials will be unrecoverable after a process restart. "
        "Set BYOK_ENCRYPTION_KEY (32 url-safe base64-encoded bytes; "
        "use cryptography.fernet.Fernet.generate_key()) in production."
    )
    return Fernet(Fernet.generate_key())


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored secret. Raises ``InvalidToken`` if the
    ciphertext is corrupted or encrypted with a different key."""
    return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def _validate_provider(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise UnsupportedProviderError(
            f"Unsupported provider '{provider}'. "
            f"Supported: {sorted(SUPPORTED_PROVIDERS)}"
        )


def get_credential(
    db: Session, user_id: str, provider: str
) -> str | None:
    """Return the decrypted secret for ``(user_id, provider)``, or
    ``None`` if no credential is stored. Returns ``None`` rather than
    raising when the ciphertext is undecryptable (most likely cause:
    operator rotated ``BYOK_ENCRYPTION_KEY`` without re-encrypting
    existing rows) — the consumer site should fall back to the
    install-wide env var key in that case.
    """
    _validate_provider(provider)
    row = (
        db.query(UserCredential)
        .filter(
            UserCredential.user_id == user_id,
            UserCredential.provider == provider,
        )
        .first()
    )
    if row is None:
        return None
    try:
        return decrypt_secret(row.encrypted_secret)
    except InvalidToken:
        logger.warning(
            "BYOK credential for user_id=%s provider=%s is undecryptable "
            "(BYOK_ENCRYPTION_KEY rotated or ciphertext corrupted). "
            "Falling back to install-wide key at the call site.",
            user_id,
            provider,
        )
        return None


def list_for_user(db: Session, user_id: str) -> list[UserCredential]:
    """Return all credentials for the given user. The
    ``encrypted_secret`` is left as ciphertext — callers must NOT
    decrypt for listing; only the LLM-call site decrypts."""
    return (
        db.query(UserCredential)
        .filter(UserCredential.user_id == user_id)
        .order_by(UserCredential.provider)
        .all()
    )


def set_credential(
    db: Session,
    user_id: str,
    provider: str,
    secret: str,
    *,
    label: str | None = None,
) -> UserCredential:
    """Upsert: if a row exists for ``(user_id, provider)``, replace
    its encrypted_secret + label; otherwise insert a new row."""
    _validate_provider(provider)
    if not secret or not secret.strip():
        raise ValueError("Secret cannot be empty")

    existing = (
        db.query(UserCredential)
        .filter(
            UserCredential.user_id == user_id,
            UserCredential.provider == provider,
        )
        .first()
    )
    encrypted = encrypt_secret(secret)
    if existing is not None:
        existing.encrypted_secret = encrypted
        existing.label = label
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    row = UserCredential(
        user_id=user_id,
        provider=provider,
        encrypted_secret=encrypted,
        label=label,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_credential(db: Session, user_id: str, provider: str) -> bool:
    """Remove the credential for ``(user_id, provider)``. Returns
    ``True`` if a row was deleted, ``False`` if none existed."""
    _validate_provider(provider)
    row = (
        db.query(UserCredential)
        .filter(
            UserCredential.user_id == user_id,
            UserCredential.provider == provider,
        )
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True

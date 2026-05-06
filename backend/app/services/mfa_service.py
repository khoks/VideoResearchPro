"""TOTP / MFA service — T-5.4.6.

Standard RFC 6238 TOTP via ``pyotp``. Compatible with Google
Authenticator, 1Password, Authy, Bitwarden, Microsoft Authenticator,
etc.

Storage:
- Secret is encrypted at rest using the same Fernet key BYOK uses
  (``BYOK_ENCRYPTION_KEY``) — re-using the encryption infrastructure
  from T-5.6.1 rather than introducing a second key.
- Recovery codes are stored as a JSON list of SHA-256 hex digests.
  Raw codes are returned to the user once at enrollment-verification
  time and never again.

Login flow:
- User logs in with email + password as usual.
- If their MFA is enabled, the login response indicates a second step
  is required and returns a short-lived ``mfa_token`` (signed JWT
  carrying ``user_id`` + ``mfa_step=true``, 5 minute TTL).
- User submits the TOTP code (or a recovery code) plus the
  ``mfa_token`` to ``/auth/login/mfa``; on success the real access
  token is issued and a session row is written.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.mfa_secret import MfaSecret
from app.models.user import User
from app.services import byok_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------

# Per-code length: 10 hex chars = 40 bits of entropy. Codes are one-time-use
# so collision risk is negligible.
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_LENGTH = 10


def _generate_recovery_codes() -> list[str]:
    """Generate ``RECOVERY_CODE_COUNT`` cryptographically-random codes."""
    return [
        secrets.token_hex(RECOVERY_CODE_LENGTH // 2).upper()
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.upper().strip().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


class MfaError(RuntimeError):
    pass


class MfaAlreadyEnabledError(MfaError):
    pass


class MfaNotEnrolledError(MfaError):
    pass


def enroll(db: Session, user: User) -> tuple[str, str]:
    """Generate a fresh TOTP secret + recovery codes for ``user``.

    Returns ``(secret, provisioning_uri)``:
    - ``secret`` is the 32-char base32 string the user pastes into
      authenticator apps that don't support QR codes.
    - ``provisioning_uri`` is the ``otpauth://`` URI the frontend
      renders as a QR code.

    The row starts in ``enabled=False`` state. The user must call
    ``verify_enrollment`` with a working TOTP code to flip ``enabled=True``
    — until then the secret is "in flight" and not yet enforced at login.

    Calling ``enroll`` again for a user with ``enabled=True`` raises
    ``MfaAlreadyEnabledError`` to prevent accidental rotation. To
    rotate, the user must first ``disable`` then ``enroll`` fresh.
    Calling ``enroll`` on an in-flight (enabled=False) row replaces it.
    """
    existing = (
        db.query(MfaSecret).filter(MfaSecret.user_id == user.id).first()
    )
    if existing is not None and existing.enabled:
        raise MfaAlreadyEnabledError(
            "MFA is already enabled. Disable it first before re-enrolling."
        )

    secret = pyotp.random_base32()
    encrypted = byok_service.encrypt_secret(secret)

    if existing is None:
        row = MfaSecret(
            user_id=user.id,
            secret_encrypted=encrypted,
            enabled=False,
            recovery_codes_json="[]",
        )
        db.add(row)
    else:
        # Replace the in-flight row with a fresh secret.
        existing.secret_encrypted = encrypted
        existing.enabled = False
        existing.recovery_codes_json = "[]"
        existing.updated_at = datetime.now(timezone.utc)
    db.commit()

    totp = pyotp.TOTP(secret)
    issuer = getattr(settings, "MFA_ISSUER_NAME", "Pratidhvani")
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=issuer)
    return secret, provisioning_uri


def verify_enrollment(
    db: Session, user: User, code: str
) -> list[str]:
    """Validate the user's first TOTP code, flip ``enabled=True``,
    generate recovery codes, return them. The raw codes are returned
    here exactly once — the database stores only their hashes.
    """
    row = (
        db.query(MfaSecret).filter(MfaSecret.user_id == user.id).first()
    )
    if row is None:
        raise MfaNotEnrolledError(
            "No MFA enrollment in flight. Call /auth/mfa/enroll first."
        )
    if not _verify_totp_against_row(row, code):
        raise MfaError("Invalid TOTP code")

    raw_codes = _generate_recovery_codes()
    hashed = [_hash_code(c) for c in raw_codes]
    row.recovery_codes_json = json.dumps(hashed)
    row.enabled = True
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return raw_codes


def disable(db: Session, user: User) -> bool:
    """Remove the MFA enrollment for the user. Returns True if a row
    was deleted, False if no row existed."""
    row = (
        db.query(MfaSecret).filter(MfaSecret.user_id == user.id).first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def is_enabled(db: Session, user_id: str) -> bool:
    """True iff the user has an MFA secret with ``enabled=True``."""
    row = (
        db.query(MfaSecret)
        .filter(MfaSecret.user_id == user_id, MfaSecret.enabled.is_(True))
        .first()
    )
    return row is not None


# ---------------------------------------------------------------------------
# TOTP / recovery-code verification at login time
# ---------------------------------------------------------------------------


def _verify_totp_against_row(row: MfaSecret, code: str) -> bool:
    """True iff ``code`` is a valid TOTP for the row's secret. Allows
    a ±1 window (~30 seconds drift) to handle clock skew."""
    try:
        secret = byok_service.decrypt_secret(row.secret_encrypted)
    except Exception:
        logger.exception(
            "MFA decrypt failed for user_id=%s — likely BYOK key rotation",
            row.user_id,
        )
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code.strip(), valid_window=1)


def _consume_recovery_code_against_row(
    db: Session, row: MfaSecret, code: str
) -> bool:
    """If ``code`` matches one of the stored recovery hashes, remove
    that hash from the list and return True. Otherwise return False.
    """
    target = _hash_code(code)
    try:
        codes: list[str] = json.loads(row.recovery_codes_json or "[]")
    except (json.JSONDecodeError, TypeError):
        codes = []
    if target not in codes:
        return False
    codes.remove(target)
    row.recovery_codes_json = json.dumps(codes)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


def verify_at_login(db: Session, user_id: str, code: str) -> bool:
    """Validate a TOTP code OR a recovery code at login time.

    Recovery codes are one-shot — on success the matched code is
    removed from the stored list.

    Returns False (NOT raises) when:
    - no MFA row for the user
    - row is not yet enabled
    - the code matches neither a current TOTP nor a recovery code
    """
    row = (
        db.query(MfaSecret).filter(MfaSecret.user_id == user_id).first()
    )
    if row is None or not row.enabled:
        return False
    if _verify_totp_against_row(row, code):
        return True
    return _consume_recovery_code_against_row(db, row, code)


# ---------------------------------------------------------------------------
# MFA-step JWT (the ticket between /auth/login and /auth/login/mfa)
# ---------------------------------------------------------------------------


MFA_TOKEN_TTL_MIN = 5


def issue_mfa_step_token(user_id: str) -> str:
    """Short-lived signed token that proves the user successfully
    completed the password step but still owes the second factor."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=MFA_TOKEN_TTL_MIN)).timestamp()),
        "mfa_step": True,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )


def decode_mfa_step_token(token: str) -> str | None:
    """Return the user_id encoded in the MFA-step token, or None if the
    token is invalid / expired / not an MFA-step token."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None
    if not payload.get("mfa_step"):
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None

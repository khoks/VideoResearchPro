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
- T-5.4.13: one ticket takes at most ``MFA_TICKET_MAX_ATTEMPTS`` codes,
  counted on its ``jti`` (``mfa_step_tickets``), and buys one session.
  A dead ticket means signing in again from the first step.

Turning it off takes a code too, under the same count keyed on the user
(T-5.4.16, ``count_disable_attempt``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp
import jwt
from jwt import PyJWTError as JWTError  # T-5.4.9: PyJWT replaced python-jose (unfixed CVE)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.mfa_secret import MfaSecret
from app.models.mfa_step_ticket import MfaStepTicket
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
    """Remove the MFA enrollment for the user, and the count of codes tried
    to do it (T-5.4.16). Returns True if a row was deleted, False if no row
    existed."""
    row = (
        db.query(MfaSecret).filter(MfaSecret.user_id == user.id).first()
    )
    if row is None:
        return False
    db.delete(row)
    db.query(MfaStepTicket).filter(
        MfaStepTicket.jti == _turn_off_counter_id(user.id)
    ).delete(synchronize_session=False)
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
    a ±1 window (~30 seconds drift) to handle clock skew.

    Raises ``byok_service.EncryptionConfigurationError`` when
    ``BYOK_ENCRYPTION_KEY`` is malformed (T-5.6.9), and its subclass
    ``StoredSecretUnreadableError`` when a well-formed key cannot read the
    secret (T-5.6.11: the key was rotated, or the row is corrupt). Either
    way no code can be checked, and answering "invalid code" would send the
    user hunting for a clock problem instead of the operator fixing the key.
    Nothing from the failure is logged but the account: neither the secret
    nor the key can reach the log."""
    try:
        secret = byok_service.decrypt_secret(row.secret_encrypted)
    except byok_service.EncryptionConfigurationError:
        raise
    except Exception:
        logger.error(
            "A stored two-step secret cannot be read for user_id=%s: "
            "BYOK_ENCRYPTION_KEY changed since it was saved, or the row is corrupt",
            row.user_id,
        )
        raise byok_service.StoredSecretUnreadableError(
            "BYOK_ENCRYPTION_KEY cannot read the stored secret"
        ) from None
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

    Raises ``byok_service.EncryptionConfigurationError`` when
    ``BYOK_ENCRYPTION_KEY`` is malformed or cannot read the secret
    (``StoredSecretUnreadableError``) and the code is not a recovery code.
    Recovery codes are stored hashed, not encrypted, so they still work with
    a broken key: they are the way in until the operator fixes it.
    """
    row = (
        db.query(MfaSecret).filter(MfaSecret.user_id == user_id).first()
    )
    if row is None or not row.enabled:
        return False
    try:
        if _verify_totp_against_row(row, code):
            return True
    except byok_service.EncryptionConfigurationError:
        if _consume_recovery_code_against_row(db, row, code):
            return True
        raise
    return _consume_recovery_code_against_row(db, row, code)


# ---------------------------------------------------------------------------
# MFA-step JWT (the ticket between /auth/login and /auth/login/mfa)
# ---------------------------------------------------------------------------


MFA_TOKEN_TTL_MIN = 5

# The ticket's `typ` claim. It is signed with the access-token key, so it
# authenticates nothing on its own only because every bearer check decodes
# through `auth_service.decode_access_token`, which refuses it.
MFA_STEP_TOKEN_TYPE = "mfa_step"


def issue_mfa_step_token(user_id: str) -> str:
    """Short-lived signed token that proves the user successfully
    completed the password step but still owes the second factor.

    It is a ticket for ``/auth/login/mfa`` only, never a credential: see
    ``auth_service.decode_access_token``. Its ``jti`` names it for the
    attempt count (T-5.4.13, ``count_ticket_attempt``)."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=MFA_TOKEN_TTL_MIN)).timestamp()),
        "jti": str(uuid.uuid4()),
        "mfa_step": True,
        "typ": MFA_STEP_TOKEN_TYPE,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )


@dataclass(frozen=True)
class MfaTicket:
    """A decoded second-factor ticket: whose it is, its ``jti``, and its
    ``exp`` (naive UTC, as the database stores it)."""

    user_id: str
    jti: str
    expires_at: datetime


def decode_mfa_step_ticket(token: str) -> MfaTicket | None:
    """The ticket ``token`` carries, or None if it is invalid, expired, not
    a second-factor ticket, or has no ``jti``.

    A ticket without a ``jti`` was issued before T-5.4.13 and cannot be
    counted, so it is refused: tickets live five minutes, so this only asks
    someone mid-sign-in at the deploy to start over."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None
    if not payload.get("mfa_step"):
        return None
    sub, jti, exp = payload.get("sub"), payload.get("jti"), payload.get("exp")
    if not isinstance(sub, str) or not isinstance(jti, str) or not jti:
        return None
    if not isinstance(exp, (int, float)):
        return None
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
    return MfaTicket(user_id=sub, jti=jti, expires_at=expires_at)


# T-5.4.13: codes one ticket may try. The per-IP sign-in rate limit was the
# only bound before, so one five-minute ticket could be tried from many
# addresses. Five leaves room for a mistyped code and a clock that is off by
# a step; a sixth try needs the password (or the provider) again.
MFA_TICKET_MAX_ATTEMPTS = 5


class TicketClosedError(MfaError):
    """The ticket takes no more codes. ``reason`` is ``"used"`` (a code was
    accepted with it) or ``"too_many_attempts"``."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def count_ticket_attempt(db: Session, ticket: MfaTicket) -> int:
    """Count one code attempt against ``ticket`` before the code is checked.

    Returns the attempts made with it so far, this one included. Raises
    ``TicketClosedError`` when the ticket is dead: a code was already
    accepted with it, or it has had its ``MFA_TICKET_MAX_ATTEMPTS``. Keyed on
    the ticket's ``jti``, never on the caller's address. The increment is one
    conditional UPDATE, so two attempts racing on the same ticket cannot both
    take the last try. Rows of expired tickets are swept here.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(MfaStepTicket).filter(MfaStepTicket.expires_at < now).delete(
        synchronize_session=False
    )
    db.commit()
    if db.get(MfaStepTicket, ticket.jti) is None:
        db.add(
            MfaStepTicket(
                jti=ticket.jti,
                user_id=ticket.user_id,
                attempts=0,
                expires_at=ticket.expires_at,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            # A concurrent first attempt wrote it; count against that row.
            db.rollback()
    counted = (
        db.query(MfaStepTicket)
        .filter(
            MfaStepTicket.jti == ticket.jti,
            MfaStepTicket.used_at.is_(None),
            MfaStepTicket.attempts < MFA_TICKET_MAX_ATTEMPTS,
        )
        .update(
            {MfaStepTicket.attempts: MfaStepTicket.attempts + 1},
            synchronize_session=False,
        )
    )
    db.commit()
    row = db.get(MfaStepTicket, ticket.jti)
    db.refresh(row)
    if counted == 0:
        raise TicketClosedError("used" if row.used_at is not None else "too_many_attempts")
    return row.attempts


# T-5.4.16: `DELETE /auth/mfa` checks a code too, and takes no ticket, so
# until this only the per-user bucket limited it: a stolen session could guess
# at up to 6,000 a minute. The count is T-5.4.13's, one row in the same table
# under an id no ticket can have: `MFA_TICKET_MAX_ATTEMPTS` codes, then none
# until the row expires. The window starts at the first code and a later one
# does not extend it. `disable` deletes the row, which is what a right code
# does; a row that expires is swept as ticket rows are.
#
# It counts on the user, in the database, and touches nothing sign-in reads:
# the caller already holds a session, so a wrong code here locks no one out.
MFA_DISABLE_WINDOW_MIN = 15
_TURN_OFF_COUNTER_PREFIX = "turn-off:"


def _turn_off_counter_id(user_id: str) -> str:
    return f"{_TURN_OFF_COUNTER_PREFIX}{user_id}"


def count_disable_attempt(db: Session, user_id: str) -> int:
    """Count one code tried on ``DELETE /auth/mfa`` before it is checked.

    Returns the codes tried in this window, this one included. Raises
    ``TicketClosedError`` when the window has had its
    ``MFA_TICKET_MAX_ATTEMPTS``: past that no code is checked."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return count_ticket_attempt(
        db,
        MfaTicket(
            user_id=user_id,
            jti=_turn_off_counter_id(user_id),
            expires_at=now + timedelta(minutes=MFA_DISABLE_WINDOW_MIN),
        ),
    )


def use_ticket(db: Session, ticket: MfaTicket) -> bool:
    """Mark ``ticket`` used once its code was accepted, so it buys one
    session. False when another request used it first."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    used = (
        db.query(MfaStepTicket)
        .filter(MfaStepTicket.jti == ticket.jti, MfaStepTicket.used_at.is_(None))
        .update({MfaStepTicket.used_at: now}, synchronize_session=False)
    )
    db.commit()
    return used == 1

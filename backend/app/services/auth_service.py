import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# E-5.4: outcomes returned by `authenticate_user_v2` so the router can
# distinguish "wrong password" from "locked out" without leaking the
# distinction to the caller's HTTP response (the router still returns
# a generic 401 either way — but the router can choose to *audit* a
# lockout differently from a regular failure).
class AuthOutcome:
    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    LOCKED_OUT = "locked_out"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except Exception:
        logger.exception("Password verification failed")
        return False


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_id(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, email: str, password: str) -> User:
    user = User(email=email.lower(), password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Legacy authentication entry point.

    Kept for back-compat with tests / call sites that just need a
    boolean-ish "good or bad?" answer. New code should prefer
    ``authenticate_user_v2`` which returns the structured ``AuthOutcome``
    so callers can audit lockouts separately from invalid credentials.
    """
    user, outcome = authenticate_user_v2(db, email, password)
    return user if outcome == AuthOutcome.SUCCESS else None


def authenticate_user_v2(
    db: Session,
    email: str,
    password: str,
) -> tuple[User | None, str]:
    """E-5.4 hardened authentication path.

    Returns ``(user, outcome)``:
    - ``(user, AuthOutcome.SUCCESS)`` on valid credentials. Resets
      ``failed_login_attempts`` and ``locked_until`` to clean state.
    - ``(user, AuthOutcome.LOCKED_OUT)`` if the account is currently
      locked. Caller should still 401 to avoid telling the attacker
      "this email exists, just wait it out".
    - ``(user, AuthOutcome.INVALID_CREDENTIALS)`` if the password is
      wrong. Increments ``failed_login_attempts``; on threshold, sets
      ``locked_until``.
    - ``(None, AuthOutcome.INVALID_CREDENTIALS)`` if the email doesn't
      exist. We still consume timing comparable to a password verify
      so the response time doesn't leak account-existence.
    """
    user = get_user_by_email(db, email)
    if user is None:
        # Run a dummy verify to keep timing roughly constant; the
        # bcrypt cost is what dominates auth latency.
        verify_password(password, _DUMMY_PWD_HASH)
        return None, AuthOutcome.INVALID_CREDENTIALS

    now = datetime.now(timezone.utc)

    # Treat any naive datetime stored before lockout shipped as UTC.
    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)

    if locked_until is not None and locked_until > now:
        return user, AuthOutcome.LOCKED_OUT

    if not verify_password(password, user.password_hash):
        # Failed attempt → increment + maybe lock.
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        threshold = settings.LOCKOUT_FAILURE_THRESHOLD
        if threshold > 0 and user.failed_login_attempts >= threshold:
            user.locked_until = now + timedelta(
                minutes=settings.LOCKOUT_DURATION_MIN
            )
        db.commit()
        db.refresh(user)
        return user, AuthOutcome.INVALID_CREDENTIALS

    # Success — clear lockout state.
    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()
        db.refresh(user)
    return user, AuthOutcome.SUCCESS


# Used as a constant-cost decoy in `authenticate_user_v2` when an
# email doesn't exist. Generated once at import.
_DUMMY_PWD_HASH = hash_password("decoy-not-a-real-password")


# ---------------------------------------------------------------------------
# E-5.4: Password-reset flow
# ---------------------------------------------------------------------------


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def request_password_reset(db: Session, email: str) -> tuple[User, str] | None:
    """Generate a single-use reset token. Returns ``(user, secret)`` so
    the caller can email / log the secret. Returns ``None`` if no user
    matches the email — but the caller should always 200 to avoid
    leaking existence.

    The secret is the value the user will paste into the reset form;
    only its SHA-256 hash is stored server-side. Tokens expire after
    ``settings.PASSWORD_RESET_TOKEN_TTL_MIN`` minutes.
    """
    user = get_user_by_email(db, email)
    if user is None:
        return None
    secret = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_TTL_MIN
    )
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(secret),
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    return user, secret


def confirm_password_reset(
    db: Session,
    secret: str,
    new_password: str,
) -> User | None:
    """Validate the reset secret and rotate the password.

    Returns the updated User on success, or ``None`` if the token is
    unknown / already-consumed / expired. Single-use is enforced by
    setting ``consumed_at`` on the token row.
    """
    token_hash = _hash_token(secret)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )
    if row is None:
        return None
    if row.consumed_at is not None:
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None

    user = get_user_by_id(db, row.user_id)
    if user is None:
        return None

    user.password_hash = hash_password(new_password)
    # A successful reset implicitly clears any active lockout — the
    # legitimate user has just proven control of the email account.
    user.failed_login_attempts = 0
    user.locked_until = None
    row.consumed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
    *,
    db: Session | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, int]:
    """Return (jwt_token, expires_in_seconds).

    T-5.4.7: when ``db`` is provided, also writes a Session row keyed on
    the JWT's `jti` claim so the token can be revoked later. Existing
    callers that don't pass ``db`` get the legacy "stateless JWT only"
    behaviour — those tokens cannot be individually revoked. This
    preserves back-compat for tests and lets routers opt-in by passing
    their session.
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.JWT_EXPIRY_HOURS)
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    if db is not None:
        try:
            from app.models.session import Session as SessionRow

            session_row = SessionRow(
                jti=jti,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent[:512] if user_agent else None,
            )
            db.add(session_row)
            db.commit()
        except Exception:
            logger.exception(
                "create_access_token: failed to persist session row for "
                "user_id=%s jti=%s — token issued but cannot be revoked",
                user_id,
                jti,
            )
            try:
                db.rollback()
            except Exception:
                pass

    return token, int(expires_delta.total_seconds())


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token. Returns payload or None on any failure."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        logger.info("JWT decode failed")
        return None


# ---------------------------------------------------------------------------
# T-5.4.7 session management
# ---------------------------------------------------------------------------


def is_session_active(db: Session, jti: str) -> bool:
    """True iff the session row for ``jti`` exists and is not revoked.

    Used by the auth dependency to enforce revocation. Returns True
    when the row is missing — back-compat for tokens issued before
    T-5.4.7 (no session row was written). Tokens issued after this PR
    have a session row by construction; their absence implies a
    create-time persistence failure (logged at issuance) and we
    fail-open rather than fail-closed for those edge cases.
    """
    from app.models.session import Session as SessionRow

    row = db.query(SessionRow).filter(SessionRow.jti == jti).first()
    if row is None:
        # No session row → token pre-dates T-5.4.7. Allow it; the token's
        # own `exp` claim still bounds its lifetime.
        return True
    return row.revoked_at is None


def touch_session(db: Session, jti: str) -> None:
    """Update `last_used_at` on the session row. Best-effort — logs on
    failure but never propagates."""
    from app.models.session import Session as SessionRow

    try:
        row = db.query(SessionRow).filter(SessionRow.jti == jti).first()
        if row is None:
            return
        row.last_used_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        logger.exception("touch_session failed for jti=%s", jti)
        try:
            db.rollback()
        except Exception:
            pass


def revoke_session(db: Session, jti: str, user_id: str) -> bool:
    """Revoke a single session by jti. Returns True if revoked, False
    if the session doesn't exist or doesn't belong to ``user_id``.

    The user_id check is critical: a malicious user must NOT be able to
    revoke another user's sessions by passing their jti.
    """
    from app.models.session import Session as SessionRow

    row = (
        db.query(SessionRow)
        .filter(SessionRow.jti == jti, SessionRow.user_id == user_id)
        .first()
    )
    if row is None:
        return False
    if row.revoked_at is not None:
        # Already revoked — idempotent.
        return True
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


def revoke_all_sessions(
    db: Session, user_id: str, *, except_jti: str | None = None
) -> int:
    """Revoke every active session for ``user_id``. Optionally skip
    ``except_jti`` (so the current request's session can stay alive
    after a "logout other devices" call).

    Returns the number of sessions revoked.
    """
    from app.models.session import Session as SessionRow

    q = db.query(SessionRow).filter(
        SessionRow.user_id == user_id,
        SessionRow.revoked_at.is_(None),
    )
    if except_jti is not None:
        q = q.filter(SessionRow.jti != except_jti)
    rows = q.all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    db.commit()
    return len(rows)


def list_user_sessions(db: Session, user_id: str) -> list:
    """Return all sessions for ``user_id``, newest-first by created_at.
    Includes revoked sessions — UI shows them with a 'revoked' badge."""
    from app.models.session import Session as SessionRow

    return (
        db.query(SessionRow)
        .filter(SessionRow.user_id == user_id)
        .order_by(SessionRow.created_at.desc())
        .all()
    )

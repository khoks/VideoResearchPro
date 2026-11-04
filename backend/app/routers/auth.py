import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_jti, get_current_user, get_db, require_operator
from app.models.user import User
from app.schemas.auth import (
    PASSWORD_MAX_CHARS,
    PASSWORD_MIN_CHARS,
    AuditLogEntry,
    ChangeTierRequest,
    ChangeTierResponse,
    LoginRequest,
    MeResponse,
    MfaRequiredResponse,
    PasswordChangePayload,
    PasswordChangeResponse,
    PasswordResetConfirmPayload,
    PasswordResetConfirmResponse,
    PasswordResetRequestPayload,
    PasswordResetRequestResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import audit_service, auth_service, email_service, mfa_service
from app.services.audit_service import Event
from app.utils.client_ip import client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    # T-5.4.18: before anything else, so this says nothing about the address.
    if not auth_service.password_can_be_hashed(payload.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=auth_service.PASSWORD_CANNOT_BE_STORED,
        )
    existing = auth_service.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    # D-111 review: a listed address makes its holder an operator, and this
    # route verifies no email, so an unregistered listed address is not open
    # to sign-up. OAuth with a provider-verified address still creates it.
    if auth_service.is_operator_email(payload.email):
        logger.warning("Refused a password registration for an address listed in ADMIN_EMAILS")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=auth_service.REGISTER_OPERATOR_EMAIL_REFUSED,
        )
    try:
        user = auth_service.create_user(db, email=payload.email, password=payload.password)
    except IntegrityError:
        db.rollback()
        logger.exception("Failed to create user due to integrity error")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    audit_service.record(
        db,
        event=Event.USER_REGISTERED,
        user_id=user.id,
        request=request,
    )
    return UserResponse.model_validate(user)


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse | MfaRequiredResponse:
    """Returns either a `TokenResponse` (when MFA is not enabled) or
    an `MfaRequiredResponse` (when MFA is enabled — caller must POST
    `/auth/login/mfa` with the `mfa_token` + a TOTP / recovery code).
    The response_model decorator is omitted so FastAPI returns the
    discriminator-free shape that callers can branch on by checking
    `requires_mfa` (truthy) or `access_token` (present)."""
    user, outcome = auth_service.authenticate_user_v2(
        db, email=payload.email, password=payload.password
    )
    if outcome != auth_service.AuthOutcome.SUCCESS:
        # Audit the failure path with as much context as we have. Even
        # for unknown emails we log a row (user_id=None) so brute-force
        # attempts against non-existent accounts are visible.
        if outcome == auth_service.AuthOutcome.LOCKED_OUT:
            audit_service.record(
                db,
                event=Event.LOGIN_LOCKED_OUT,
                user_id=user.id if user else None,
                request=request,
                metadata={"email": payload.email.lower()},
            )
        else:
            audit_service.record(
                db,
                event=Event.LOGIN_FAILURE,
                user_id=user.id if user else None,
                request=request,
                metadata={"email": payload.email.lower()},
            )
            # If this failure pushed the account into lockout, emit the
            # ACCOUNT_LOCKED marker so audit-log readers can spot it.
            if user is not None and user.locked_until is not None:
                audit_service.record(
                    db,
                    event=Event.ACCOUNT_LOCKED,
                    user_id=user.id,
                    request=request,
                    metadata={"locked_until": user.locked_until.isoformat()},
                )
        # Generic 401 — never leak which of the three failure modes
        # produced the negative response.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # T-5.4.6: when MFA is enabled, the password-step alone is not
    # enough — return a short-lived mfa_token and require a second
    # POST to /auth/login/mfa with the TOTP / recovery code.
    if mfa_service.is_enabled(db, user.id):
        mfa_token = mfa_service.issue_mfa_step_token(user.id)
        # Audit the password-step success so audit logs show the second
        # factor was needed (vs absent).
        audit_service.record(
            db,
            event=Event.LOGIN_SUCCESS,
            user_id=user.id,
            request=request,
            metadata={"requires_mfa": True},
        )
        return MfaRequiredResponse(
            requires_mfa=True,
            mfa_token=mfa_token,
            expires_in=mfa_service.MFA_TOKEN_TTL_MIN * 60,
        )

    audit_service.record(
        db,
        event=Event.LOGIN_SUCCESS,
        user_id=user.id,
        request=request,
    )
    # T-5.4.7: write a session row so this token can be individually
    # revoked from /auth/sessions/{id}.
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    token, expires_in = auth_service.create_access_token(
        user.id, db=db, ip_address=ip, user_agent=ua
    )
    return TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in)


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
def password_reset_request(
    payload: PasswordResetRequestPayload,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetRequestResponse:
    """Generate a reset token and deliver it out of band.

    Always 200 with the same generic body, whether or not the address has
    an account, so the response never says which addresses exist. The
    secret is delivered only by email (SMTP configured) or, when SMTP is
    unset, by the email service's log fallback, which writes the email to
    the server log for the operator to hand over. It is never in the
    response: this route is unauthenticated, so a secret in the response
    let anyone who knew an address reset that account's password. Until
    2026-11-03 it was returned as ``debug_secret`` whenever SMTP was unset
    (T-5.4.8's self-host handoff), which on a multi-user install was an
    account takeover by email address.
    """
    result = auth_service.request_password_reset(db, payload.email)
    if result is None:
        # Audit the attempt (with no user_id) so brute-force scanning
        # for valid emails is visible.
        audit_service.record(
            db,
            event=Event.PASSWORD_RESET_REQUESTED,
            request=request,
            metadata={"email": payload.email.lower(), "user_existed": False},
        )
        return PasswordResetRequestResponse()

    user, secret = result
    audit_service.record(
        db,
        event=Event.PASSWORD_RESET_REQUESTED,
        user_id=user.id,
        request=request,
        metadata={"email": user.email, "user_existed": True},
    )
    # T-5.4.8: deliver via SMTP when configured, log fallback otherwise.
    subject, body = email_service.render_password_reset_email(
        recipient_email=user.email,
        secret=secret,
        ttl_minutes=settings.PASSWORD_RESET_TOKEN_TTL_MIN,
    )
    delivered = email_service.send_email(user.email, subject, body)
    if not delivered:
        logger.warning(
            "password-reset email delivery failed for user_id=%s — "
            "secret was logged via the email_service fallback path",
            user.id,
        )
    return PasswordResetRequestResponse()


@router.post("/password-reset/confirm", response_model=PasswordResetConfirmResponse)
def password_reset_confirm(
    payload: PasswordResetConfirmPayload,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetConfirmResponse:
    """Set the new password and sign the account out everywhere (T-5.4.12):
    whoever was signed in, the person the reset is meant to lock out among
    them, has to sign in again with the new password."""
    # T-5.4.18: checked first, so the code is not spent on a refused password.
    if not auth_service.password_can_be_hashed(payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=auth_service.PASSWORD_CANNOT_BE_STORED,
        )
    result = auth_service.confirm_password_reset(
        db, secret=payload.token, new_password=payload.new_password
    )
    if result is None:
        audit_service.record(
            db,
            event=Event.PASSWORD_RESET_INVALID_TOKEN,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    user, revoked = result
    audit_service.record(
        db,
        event=Event.PASSWORD_RESET_COMPLETED,
        user_id=user.id,
        request=request,
        metadata={"sessions_revoked": revoked},
    )
    audit_service.record(
        db,
        event=Event.SESSIONS_REVOKED_ALL,
        user_id=user.id,
        request=request,
        metadata={"revoked_count": revoked, "keep_current": False, "reason": "password_reset"},
    )
    return PasswordResetConfirmResponse()


# What the change route says when the account has no password to check.
PASSWORD_CHANGE_NO_PASSWORD = (
    "This account has no password yet: it was made by signing in with Google "
    "or GitHub. To set one, use \"Forgot it?\" to get a reset code."
)


@router.post("/password/change", response_model=PasswordChangeResponse)
def change_password(
    payload: PasswordChangePayload,
    request: Request,
    current_user: User = Depends(get_current_user),
    current_jti: str | None = Depends(get_current_jti),
    db: Session = Depends(get_db),
) -> PasswordChangeResponse:
    """T-5.4.14: a signed-in user sets a new password by giving the current
    one. Every other session on the account is signed out; this one stays.

    * The current password is checked under the account lockout, as at
      sign-in: a wrong one counts toward the lock (400), and while locked
      the route answers 429. The per-IP limit is the sign-in one
      (``middleware/rate_limit.py``, ``password_change``).
    * An account with no password (Google or GitHub sign-in made it) gets
      400 pointing to the reset flow, which sets a first one.
    * Refusals are 400 or 429, never 401: the web client treats a 401 as a
      signed-out session and would sign the user out for a typo. A body
      that is not two strings is a 422 before any of this runs.
    * No password, current or new, is echoed back: every 400 here is a
      fixed sentence, and the 422 handler in ``app/main.py`` drops ``input``.
    """
    if not (PASSWORD_MIN_CHARS <= len(payload.new_password) <= PASSWORD_MAX_CHARS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The new password must be {PASSWORD_MIN_CHARS} to {PASSWORD_MAX_CHARS} characters.",
        )
    if not auth_service.password_can_be_hashed(payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=auth_service.PASSWORD_CANNOT_BE_STORED,
        )
    outcome, revoked = auth_service.change_password(
        db,
        current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        keep_jti=current_jti,
    )
    if outcome == auth_service.PasswordChangeOutcome.NO_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PASSWORD_CHANGE_NO_PASSWORD,
        )
    if outcome != auth_service.PasswordChangeOutcome.CHANGED:
        locked = outcome == auth_service.PasswordChangeOutcome.LOCKED_OUT
        audit_service.record(
            db,
            event=Event.PASSWORD_CHANGE_FAILED,
            user_id=current_user.id,
            request=request,
            metadata={"reason": "locked_out" if locked else "wrong_password"},
        )
        if locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many wrong passwords: password sign-in is locked for a "
                    f"while (up to {settings.LOCKOUT_DURATION_MIN} minutes). Try "
                    "again later, or use \"Forgot it?\" to reset it."
                ),
            )
        # This failure may have just locked the account: mark it, as sign-in does.
        db.refresh(current_user)
        if auth_service.is_locked(current_user):
            audit_service.record(
                db,
                event=Event.ACCOUNT_LOCKED,
                user_id=current_user.id,
                request=request,
                metadata={"locked_until": current_user.locked_until.isoformat()},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current password is not right.",
        )
    audit_service.record(
        db,
        event=Event.PASSWORD_CHANGED,
        user_id=current_user.id,
        request=request,
        metadata={"sessions_revoked": revoked},
    )
    audit_service.record(
        db,
        event=Event.SESSIONS_REVOKED_ALL,
        user_id=current_user.id,
        request=request,
        metadata={"revoked_count": revoked, "keep_current": True, "reason": "password_change"},
    )
    return PasswordChangeResponse(sessions_revoked=revoked)


@router.get("/me", response_model=MeResponse)
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    out = MeResponse.model_validate(current_user)
    out.is_operator = auth_service.is_operator(db, current_user)
    return out


# E-5.2.X self-service tier flip with mock payment (D-050), operator-only
# since T-5.2.8 (D-111)
@router.put("/me/tier", response_model=ChangeTierResponse)
def change_tier(
    payload: ChangeTierRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChangeTierResponse:
    """Tier flip for the calling user, if they operate this install.

    T-5.2.8 / D-111: only operators (``ADMIN_EMAILS``, else the
    earliest-registered account) may switch; every other account gets 403
    before anything changes. On a shared install the paid tiers spend the
    operator's provider keys, so a sign-in alone is not enough.

    Mock-payment mode: until E-5.3 (Stripe) ships, this endpoint trusts
    the request body and flips ``users.tier`` immediately. The
    ``mock_payment`` field is accepted but ignored — it exists so the
    frontend / API contract doesn't change when E-5.3 lands and the
    implementation switches to "verify Stripe webhook payload".

    No payment is processed. Operators can use this freely to evaluate
    Pro / Studio features before the real billing wiring lands.

    Tier reads are looked up fresh from the DB on every request via
    ``get_current_user``; no JWT refresh is needed for the new tier to
    take effect.
    """
    new_tier = payload.tier.strip().lower()
    previous_tier = (current_user.tier or "free").strip().lower()

    if new_tier == previous_tier:
        # No-op flip — still surface the same response shape so the
        # frontend can render its success state uniformly.
        return ChangeTierResponse(tier=new_tier, message="No change — already on this tier.")

    current_user.tier = new_tier
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    audit_service.record(
        db,
        event=Event.TIER_CHANGED,
        user_id=current_user.id,
        request=request,
        metadata={
            "from_tier": previous_tier,
            "to_tier": new_tier,
            "mock_payment_mode": True,
        },
    )
    logger.info(
        "tier change: user=%s %s -> %s (mock payment)",
        current_user.id,
        previous_tier,
        new_tier,
    )
    return ChangeTierResponse(tier=new_tier)


@router.get("/audit-log", response_model=list[AuditLogEntry])
def audit_log(
    limit: int = 100,
    offset: int = 0,
    scope: Literal["all", "account"] = "all",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuditLogEntry]:
    """Return the current user's audit log, newest first.

    ``scope=account`` keeps only account and security events
    (``audit_service.ACCOUNT_EVENTS``), for the account security page;
    the default ``all`` also returns product analytics such as suggestion
    impressions."""
    if limit > 500:
        limit = 500
    rows = audit_service.list_for_user(
        db,
        user_id=current_user.id,
        limit=limit,
        offset=max(offset, 0),
        events=audit_service.ACCOUNT_EVENTS if scope == "account" else None,
    )
    return [AuditLogEntry.model_validate(r) for r in rows]


# T-5.5.5 / T-5.2.5: per-user quota metering.
from pydantic import BaseModel  # noqa: E402  (kept colocated for clarity)
from datetime import datetime as _dt  # noqa: E402

from app.services import quota_metering_service  # noqa: E402


class _QuotaResource(BaseModel):
    resource: str
    period_kind: str
    period_start: _dt
    period_end: _dt | None
    consumed: int
    limit: int
    over_limit: bool


class _QuotaResponse(BaseModel):
    tier: str
    resources: list[_QuotaResource]


@router.get("/quota", response_model=_QuotaResponse)
def quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> _QuotaResponse:
    """Return the user's current usage vs tier limits across every
    metered resource. ``limit=-1`` means unlimited; ``over_limit=true``
    means the user has exceeded the cap and the next quota-bearing
    request will 429."""
    snapshots = quota_metering_service.get_all_usage(db, current_user)
    from app.services.tier_service import get_user_tier

    return _QuotaResponse(
        tier=get_user_tier(current_user).value,
        resources=[
            _QuotaResource(
                resource=s.resource,
                period_kind=s.period_kind,
                period_start=s.period_start,
                period_end=s.period_end,
                consumed=s.consumed,
                limit=s.limit,
                over_limit=s.over_limit,
            )
            for s in snapshots
        ],
    )

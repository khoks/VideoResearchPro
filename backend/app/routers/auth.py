import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    AuditLogEntry,
    ChangeTierRequest,
    ChangeTierResponse,
    LoginRequest,
    MfaRequiredResponse,
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    existing = auth_service.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
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
    ip = request.client.host if request.client else None
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
    """Generate a reset token. Always returns 200 to avoid leaking
    whether the email exists; the secret is returned in `debug_secret`
    when SMTP is unconfigured so self-host operators can hand it off
    out-of-band, and is always None in production SaaS deploys."""
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
    smtp_configured = email_service._is_smtp_configured()
    delivered = email_service.send_email(user.email, subject, body)
    # Pre-T-5.4.8 self-host fallback: also return the secret in the
    # response when SMTP is unconfigured so operators can hand it off
    # immediately. On SaaS (SMTP configured) the secret is NEVER in the
    # response — email is the only delivery channel.
    response_secret = None if smtp_configured else secret
    if not delivered:
        logger.warning(
            "password-reset email delivery failed for user_id=%s — "
            "secret was logged via the email_service fallback path",
            user.id,
        )
    return PasswordResetRequestResponse(debug_secret=response_secret)


@router.post("/password-reset/confirm", response_model=PasswordResetConfirmResponse)
def password_reset_confirm(
    payload: PasswordResetConfirmPayload,
    request: Request,
    db: Session = Depends(get_db),
) -> PasswordResetConfirmResponse:
    user = auth_service.confirm_password_reset(
        db, secret=payload.token, new_password=payload.new_password
    )
    if user is None:
        audit_service.record(
            db,
            event=Event.PASSWORD_RESET_INVALID_TOKEN,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    audit_service.record(
        db,
        event=Event.PASSWORD_RESET_COMPLETED,
        user_id=user.id,
        request=request,
    )
    return PasswordResetConfirmResponse()


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


# E-5.2.X self-service tier flip with mock payment (D-050)
@router.put("/me/tier", response_model=ChangeTierResponse)
def change_tier(
    payload: ChangeTierRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangeTierResponse:
    """Self-service tier flip for the calling user.

    Mock-payment mode: until E-5.3 (Stripe) ships, this endpoint trusts
    the request body and flips ``users.tier`` immediately. The
    ``mock_payment`` field is accepted but ignored — it exists so the
    frontend / API contract doesn't change when E-5.3 lands and the
    implementation switches to "verify Stripe webhook payload".

    No payment is processed. Self-host operators can use this freely to
    evaluate Pro / Studio features before the real billing wiring lands.

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuditLogEntry]:
    """Return the current user's audit log, newest first."""
    if limit > 500:
        limit = 500
    rows = audit_service.list_for_user(
        db, user_id=current_user.id, limit=limit, offset=offset
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

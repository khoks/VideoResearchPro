import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    AuditLogEntry,
    LoginRequest,
    PasswordResetConfirmPayload,
    PasswordResetConfirmResponse,
    PasswordResetRequestPayload,
    PasswordResetRequestResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import audit_service, auth_service, email_service
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


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
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

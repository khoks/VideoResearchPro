"""MFA / TOTP endpoints — T-5.4.6.

- ``POST /auth/mfa/enroll`` — start enrollment; returns secret + QR URI.
- ``POST /auth/mfa/verify-enrollment`` — confirm with first TOTP code,
  enable MFA, return recovery codes (returned ONCE).
- ``GET /auth/mfa/status`` — is MFA enabled for the current user?
- ``DELETE /auth/mfa`` — disable MFA. Requires the current TOTP code
  to prove possession; raw password isn't required because the user
  is already authenticated for this request.
- ``POST /auth/login/mfa`` — second-step login; consumes the
  ``mfa_token`` from the first-step ``/auth/login`` response and
  validates a TOTP / recovery code. On success issues the real access
  token + writes a session row.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services import audit_service, auth_service, mfa_service
from app.services.audit_service import Event
from app.services.mfa_service import (
    MfaAlreadyEnabledError,
    MfaError,
    MfaNotEnrolledError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MfaEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaVerifyEnrollmentRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class MfaVerifyEnrollmentResponse(BaseModel):
    enabled: bool
    recovery_codes: list[str]


class MfaStatusResponse(BaseModel):
    enabled: bool


class MfaDisableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaDisableResponse(BaseModel):
    disabled: bool


class MfaLoginRequest(BaseModel):
    mfa_token: str = Field(min_length=8)
    code: str = Field(min_length=6, max_length=20)


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


@router.post("/mfa/enroll", response_model=MfaEnrollResponse)
def enroll(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaEnrollResponse:
    try:
        secret, uri = mfa_service.enroll(db, current_user)
    except MfaAlreadyEnabledError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    audit_service.record(
        db,
        event=Event.MFA_ENROLLED,
        user_id=current_user.id,
        request=request,
    )
    return MfaEnrollResponse(secret=secret, provisioning_uri=uri)


@router.post(
    "/mfa/verify-enrollment", response_model=MfaVerifyEnrollmentResponse
)
def verify_enrollment(
    payload: MfaVerifyEnrollmentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaVerifyEnrollmentResponse:
    try:
        recovery_codes = mfa_service.verify_enrollment(
            db, current_user, payload.code
        )
    except MfaNotEnrolledError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except MfaError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    audit_service.record(
        db,
        event=Event.MFA_ENABLED,
        user_id=current_user.id,
        request=request,
    )
    return MfaVerifyEnrollmentResponse(
        enabled=True, recovery_codes=recovery_codes
    )


@router.get("/mfa/status", response_model=MfaStatusResponse)
def status_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaStatusResponse:
    return MfaStatusResponse(enabled=mfa_service.is_enabled(db, current_user.id))


@router.delete("/mfa", response_model=MfaDisableResponse)
def disable(
    payload: MfaDisableRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaDisableResponse:
    """Disable MFA. Requires a valid current TOTP / recovery code to
    prove possession (the request is already authenticated, so the
    user has the password — but we still force the second factor to
    prevent a session-token thief from disabling MFA)."""
    if not mfa_service.is_enabled(db, current_user.id):
        # Already disabled — idempotent.
        return MfaDisableResponse(disabled=True)
    if not mfa_service.verify_at_login(db, current_user.id, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP / recovery code",
        )
    mfa_service.disable(db, current_user)
    audit_service.record(
        db,
        event=Event.MFA_DISABLED,
        user_id=current_user.id,
        request=request,
    )
    return MfaDisableResponse(disabled=True)


# ---------------------------------------------------------------------------
# Login second-step
# ---------------------------------------------------------------------------


@router.post("/login/mfa", response_model=TokenResponse)
def login_mfa(
    payload: MfaLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Second-step login: validate the TOTP / recovery code and issue
    the real access token. Caller must pass the ``mfa_token`` from
    the first-step ``/auth/login`` response (5 minute TTL)."""
    user_id = mfa_service.decode_mfa_step_token(payload.mfa_token)
    if user_id is None:
        # Audit the attempt with no user_id — same shape as a regular
        # bad-token failure.
        audit_service.record(
            db,
            event=Event.MFA_LOGIN_FAILURE,
            request=request,
            metadata={"reason": "invalid_mfa_token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA session",
        )

    if not mfa_service.verify_at_login(db, user_id, payload.code):
        audit_service.record(
            db,
            event=Event.MFA_LOGIN_FAILURE,
            user_id=user_id,
            request=request,
            metadata={"reason": "invalid_code"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP or recovery code",
        )

    # Success — issue the real token + session row.
    user = auth_service.get_user_by_id(db, user_id)
    if user is None:
        # Pathological — user disappeared between login and mfa-verify.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    audit_service.record(
        db,
        event=Event.MFA_LOGIN_SUCCESS,
        user_id=user.id,
        request=request,
    )
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    token, expires_in = auth_service.create_access_token(
        user.id, db=db, ip_address=ip, user_agent=ua
    )
    return TokenResponse(
        access_token=token, token_type="bearer", expires_in=expires_in
    )

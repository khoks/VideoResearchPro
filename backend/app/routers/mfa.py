"""MFA / TOTP endpoints — T-5.4.6.

- ``POST /auth/mfa/enroll`` — start enrollment; returns secret + QR URI.
- ``POST /auth/mfa/verify-enrollment`` — confirm with first TOTP code,
  enable MFA, return recovery codes (returned ONCE).
- ``GET /auth/mfa/status`` — is MFA enabled for the current user?
- ``DELETE /auth/mfa`` — disable MFA. Requires the current TOTP code
  to prove possession; raw password isn't required because the user
  is already authenticated for this request. Capped per user (T-5.4.16).
- ``POST /auth/login/mfa`` — second-step login; consumes the
  ``mfa_token`` from the first-step ``/auth/login`` response and
  validates a TOTP / recovery code. On success issues the real access
  token + writes a session row. One ticket takes at most
  ``mfa_service.MFA_TICKET_MAX_ATTEMPTS`` codes and buys one session
  (T-5.4.13).

The TOTP secret is encrypted with the install's shared key (D-043). When
``BYOK_ENCRYPTION_KEY`` is malformed (T-5.6.9), or well formed but unable to
read the secret (T-5.6.11, a rotated key), every route here that encrypts or
decrypts it answers 503 with the cause; a recovery code still works, since
those are stored hashed.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services import audit_service, auth_service, mfa_service
from app.services.audit_service import Event
from app.utils.client_ip import client_ip
from app.services.byok_service import EncryptionConfigurationError
from app.services.mfa_service import (
    MfaAlreadyEnabledError,
    MfaError,
    MfaNotEnrolledError,
    TicketClosedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# What /auth/login/mfa says when the ticket is no good, so the sign-in page
# can send the reader back to the first step. The frontend matches on these
# strings (components/auth/MfaCodeStep.tsx).
TICKET_EXPIRED_DETAIL = "Invalid or expired MFA session"
TICKET_EXHAUSTED_DETAIL = "Too many codes tried for this sign-in. Start over and sign in again."

# What DELETE /auth/mfa says past its cap (T-5.4.16). A 429, never a 401: the
# web client signs out on a 401, and this refusal leaves the session alone.
DISABLE_EXHAUSTED_DETAIL = (
    "Too many codes tried. Two-step verification stays on: try again in "
    f"up to {mfa_service.MFA_DISABLE_WINDOW_MIN} minutes."
)


def _key_unavailable(what: str, error: EncryptionConfigurationError) -> HTTPException:
    """T-5.6.9, T-5.6.11: the 503 when ``BYOK_ENCRYPTION_KEY`` is malformed or
    cannot read the stored secret. The user cannot fix it, so say so; the
    operator gets a log line. Neither carries the key."""
    logger.error("two-step verification: %s refused: %s", what, error.log_cause)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=error.detail(what),
    )


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
    except EncryptionConfigurationError as e:
        db.rollback()
        raise _key_unavailable("Two-step verification cannot be set up", e)
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
    except EncryptionConfigurationError as e:
        raise _key_unavailable("Two-step verification cannot be turned on", e)
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
    prevent a session-token thief from disabling MFA).

    T-5.4.16: every code checked counts on the user, in the database
    (``mfa_service.count_disable_attempt``), for
    ``MFA_DISABLE_WINDOW_MIN`` minutes. The attempt that uses up
    ``MFA_TICKET_MAX_ATTEMPTS`` answers 429 if it was wrong, and every one
    after it answers 429 without checking the code, even the right one, and
    writes no audit row, since a session can send these as fast as it likes.
    A wrong code touches nothing sign-in reads, and a right one clears the
    count. Counted before the check, as at sign-in, so a check that fails for
    any reason spends an attempt."""
    if not mfa_service.is_enabled(db, current_user.id):
        # Already disabled — idempotent.
        return MfaDisableResponse(disabled=True)
    try:
        attempts = mfa_service.count_disable_attempt(db, current_user.id)
    except TicketClosedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=DISABLE_EXHAUSTED_DETAIL,
        )
    try:
        ok = mfa_service.verify_at_login(db, current_user.id, payload.code)
    except EncryptionConfigurationError as e:
        raise _key_unavailable(
            "The code cannot be checked (a recovery code still works)", e
        )
    if not ok:
        exhausted = attempts >= mfa_service.MFA_TICKET_MAX_ATTEMPTS
        audit_service.record(
            db,
            event=Event.MFA_DISABLE_FAILED,
            user_id=current_user.id,
            request=request,
            metadata={
                "reason": "too_many_attempts" if exhausted else "invalid_code",
                "attempt": attempts,
            },
        )
        if exhausted:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=DISABLE_EXHAUSTED_DETAIL,
            )
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
    the first-step ``/auth/login`` response (5 minute TTL).

    T-5.4.13: every code checked counts against the ticket, keyed on its
    ``jti`` (not on the caller's address, which an attacker can change).
    The attempt that uses up ``MFA_TICKET_MAX_ATTEMPTS`` and every one after
    it answer ``TICKET_EXHAUSTED_DETAIL``: the ticket is dead, even for the
    right code, and sign-in starts over. A ticket buys one session."""
    ticket = mfa_service.decode_mfa_step_ticket(payload.mfa_token)
    if ticket is None:
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
            detail=TICKET_EXPIRED_DETAIL,
        )
    user_id = ticket.user_id

    # Counted before the code is checked, so a check that fails for any
    # reason (the 503 below among them, which still tries recovery codes)
    # spends an attempt.
    try:
        attempts = mfa_service.count_ticket_attempt(db, ticket)
    except TicketClosedError as closed:
        exhausted = closed.reason == "too_many_attempts"
        audit_service.record(
            db,
            event=Event.MFA_LOGIN_FAILURE,
            user_id=user_id,
            request=request,
            metadata={"reason": "too_many_attempts" if exhausted else "ticket_used"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=TICKET_EXHAUSTED_DETAIL if exhausted else TICKET_EXPIRED_DETAIL,
        )

    try:
        ok = mfa_service.verify_at_login(db, user_id, payload.code)
    except EncryptionConfigurationError as e:
        raise _key_unavailable(
            "The authenticator code cannot be checked (a recovery code still works)", e
        )
    if not ok:
        exhausted = attempts >= mfa_service.MFA_TICKET_MAX_ATTEMPTS
        audit_service.record(
            db,
            event=Event.MFA_LOGIN_FAILURE,
            user_id=user_id,
            request=request,
            metadata={
                "reason": "too_many_attempts" if exhausted else "invalid_code",
                "attempt": attempts,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=TICKET_EXHAUSTED_DETAIL if exhausted else "Invalid TOTP or recovery code",
        )

    # The code was right: spend the ticket, so it buys one session even if
    # it was seen in transit. Losing that race means another request with
    # this ticket just signed in.
    if not mfa_service.use_ticket(db, ticket):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=TICKET_EXPIRED_DETAIL,
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
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    token, expires_in = auth_service.create_access_token(
        user.id, db=db, ip_address=ip, user_agent=ua
    )
    return TokenResponse(
        access_token=token, token_type="bearer", expires_in=expires_in
    )

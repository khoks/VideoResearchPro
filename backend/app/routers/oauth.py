"""OAuth router — T-5.4.5.

Endpoints:

- ``GET /api/v1/auth/oauth/providers`` — return the list of providers
  whose client_id + client_secret are configured. Frontend uses this
  to know which "Sign in with X" buttons to render.
- ``GET /api/v1/auth/oauth/{provider}/start?redirect_uri=...`` —
  initiate the flow. Returns ``{authorize_url}`` for the frontend to
  redirect to. (We don't 302 ourselves so that single-page-app callers
  can decide how to navigate.)
- ``GET /api/v1/auth/oauth/{provider}/callback?code=...&state=...`` —
  consume the provider's redirect. On success, issues a Pratidhvani
  access token + writes a session row. Returns ``TokenResponse``, or
  ``MfaRequiredResponse`` when the account has two-step verification on:
  the caller finishes at ``POST /auth/login/mfa`` exactly as after a
  password sign-in.

Per [D-040](../decisions.md#d-040-...), failures return a generic 401
without leaking which step (state validation / token exchange / userinfo
fetch / linking) actually failed. One exception (T-5.4.10): a first
sign-in whose email the provider did not verify is refused with 403 and
a message saying what to do, since that is a policy refusal after the
provider authenticated the user.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.auth import MfaRequiredResponse, TokenResponse
from app.services import audit_service, auth_service, mfa_service, oauth_service
from app.services.audit_service import Event
from app.services.oauth_service import (
    OAuthError,
    OAuthProviderUnconfiguredError,
    OAuthUnverifiedEmailError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["auth"])


class OAuthProvidersResponse(BaseModel):
    providers: list[str]


class OAuthStartResponse(BaseModel):
    authorize_url: str


@router.get("/providers", response_model=OAuthProvidersResponse)
def list_providers() -> OAuthProvidersResponse:
    return OAuthProvidersResponse(providers=oauth_service.configured_providers())


@router.get("/{provider}/start", response_model=OAuthStartResponse)
def start(
    provider: str,
    redirect_uri: str = Query(..., min_length=8, max_length=512),
    db: Session = Depends(get_db),
) -> OAuthStartResponse:
    try:
        url = oauth_service.start_flow(db, provider, redirect_uri)
    except OAuthProviderUnconfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return OAuthStartResponse(authorize_url=url)


@router.get("/{provider}/callback")
def callback(
    provider: str,
    request: Request,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> TokenResponse | MfaRequiredResponse:
    try:
        user = oauth_service.complete_flow(db, provider, state, code)
    except OAuthUnverifiedEmailError as e:
        # T-5.4.10: a policy refusal, not a protocol failure. The provider
        # authenticated the user, so the step is no secret, and the user
        # needs to know what to do. The message is the same whether or not
        # an account has the address.
        audit_service.record(
            db,
            event=Event.LOGIN_FAILURE,
            request=request,
            metadata={"reason": "oauth_email_unverified", "provider": provider},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except OAuthError as e:
        # Audit but never leak the specific failure mode.
        audit_service.record(
            db,
            event=Event.LOGIN_FAILURE,
            request=request,
            metadata={"reason": "oauth_failure", "provider": provider},
        )
        logger.info(
            "OAuth callback failed for provider=%s: %s", provider, e
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth authentication failed",
        )

    # Two-step verification guards every sign-in, not just the password
    # one. The provider vouches for the email, and D-042 links an account
    # by email, so without this whoever holds the provider account would
    # skip the second factor the user turned on. Same ticket and second
    # step as /auth/login.
    if mfa_service.is_enabled(db, user.id):
        audit_service.record(
            db,
            event=Event.LOGIN_SUCCESS,
            user_id=user.id,
            request=request,
            metadata={"provider": provider, "via": "oauth", "requires_mfa": True},
        )
        return MfaRequiredResponse(
            requires_mfa=True,
            mfa_token=mfa_service.issue_mfa_step_token(user.id),
            expires_in=mfa_service.MFA_TOKEN_TTL_MIN * 60,
        )

    audit_service.record(
        db,
        event=Event.LOGIN_SUCCESS,
        user_id=user.id,
        request=request,
        metadata={"provider": provider, "via": "oauth"},
    )
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    token, expires_in = auth_service.create_access_token(
        user.id, db=db, ip_address=ip, user_agent=ua
    )
    return TokenResponse(
        access_token=token, token_type="bearer", expires_in=expires_in
    )

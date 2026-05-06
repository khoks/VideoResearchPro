"""Sessions router — T-5.4.7.

User-facing session management:

- ``GET /api/v1/auth/sessions`` — list all sessions (active + revoked) for
  the current user. Newest-first.
- ``DELETE /api/v1/auth/sessions/{jti}`` — revoke a specific session.
  Cross-user revocation is rejected (404).
- ``DELETE /api/v1/auth/sessions`` — revoke ALL active sessions for the
  current user, OPTIONALLY keeping the current request's session alive
  (``?keep_current=true``) for the "log out other devices" UX.
- ``POST /api/v1/auth/logout`` — revoke the current session.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_jti, get_current_user, get_db
from app.models.user import User
from app.services import audit_service, auth_service
from app.services.audit_service import Event

router = APIRouter(prefix="/auth", tags=["auth"])


class SessionMetadata(BaseModel):
    id: str
    jti: str
    created_at: datetime
    last_used_at: datetime
    revoked_at: datetime | None
    ip_address: str | None
    user_agent: str | None
    is_current: bool = False

    model_config = {"from_attributes": True}


class RevokeResponse(BaseModel):
    revoked: bool


class RevokeAllResponse(BaseModel):
    revoked_count: int


@router.get("/sessions", response_model=list[SessionMetadata])
def list_sessions(
    current_user: User = Depends(get_current_user),
    current_jti: str | None = Depends(get_current_jti),
    db: Session = Depends(get_db),
) -> list[SessionMetadata]:
    rows = auth_service.list_user_sessions(db, current_user.id)
    out: list[SessionMetadata] = []
    for r in rows:
        item = SessionMetadata.model_validate(r)
        item.is_current = current_jti is not None and item.jti == current_jti
        out.append(item)
    return out


@router.delete("/sessions/{jti}", response_model=RevokeResponse)
def revoke_session(
    jti: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RevokeResponse:
    """Revoke a single session by jti. 404 if not found OR if it
    doesn't belong to the current user (404 not 403 to avoid leaking
    existence — same posture as E-5.1 phase 2b cross-tenant isolation)."""
    revoked = auth_service.revoke_session(db, jti=jti, user_id=current_user.id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    audit_service.record(
        db,
        event=Event.SESSION_REVOKED,
        user_id=current_user.id,
        metadata={"jti": jti},
    )
    return RevokeResponse(revoked=True)


@router.delete("/sessions", response_model=RevokeAllResponse)
def revoke_all_sessions(
    keep_current: bool = False,
    current_user: User = Depends(get_current_user),
    current_jti: str | None = Depends(get_current_jti),
    db: Session = Depends(get_db),
) -> RevokeAllResponse:
    """Revoke ALL active sessions. Pass ``?keep_current=true`` to keep
    the current request's session alive (for "log out other devices")."""
    except_jti = current_jti if keep_current else None
    n = auth_service.revoke_all_sessions(
        db, current_user.id, except_jti=except_jti
    )
    audit_service.record(
        db,
        event=Event.SESSIONS_REVOKED_ALL,
        user_id=current_user.id,
        metadata={"revoked_count": n, "keep_current": keep_current},
    )
    return RevokeAllResponse(revoked_count=n)


@router.post("/logout", response_model=RevokeResponse)
def logout(
    current_user: User = Depends(get_current_user),
    current_jti: str | None = Depends(get_current_jti),
    db: Session = Depends(get_db),
) -> RevokeResponse:
    """Revoke the current session. The token still has its JWT
    signature, but every subsequent request is rejected because the
    session row is revoked."""
    if current_jti is None:
        # Pre-T-5.4.7 token (no jti claim) — nothing to revoke.
        # Frontend should still discard the token client-side.
        return RevokeResponse(revoked=False)
    revoked = auth_service.revoke_session(
        db, jti=current_jti, user_id=current_user.id
    )
    if revoked:
        audit_service.record(
            db,
            event=Event.LOGOUT,
            user_id=current_user.id,
        )
    return RevokeResponse(revoked=revoked)

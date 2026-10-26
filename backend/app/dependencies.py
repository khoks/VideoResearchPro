from collections.abc import Generator

import redis
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.user import User
from app.services import auth_service

# tokenUrl points at the login endpoint (used for OpenAPI docs "Authorize" button).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Module-level connection pool shared across FastAPI requests. A pooled
# client reuses TCP connections across requests instead of reconnecting
# on every dependency resolution.
_redis_pool: redis.ConnectionPool = redis.ConnectionPool.from_url(
    settings.REDIS_URL, decode_responses=True
)
_redis_client: redis.Redis = redis.Redis(connection_pool=_redis_pool)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_redis() -> redis.Redis:
    return _redis_client


def _resolve_user(token: str | None, db: Session) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc

    payload = auth_service.decode_token(token)
    if not payload:
        raise credentials_exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise credentials_exc

    # T-5.4.7: enforce session revocation. If the JWT carries a `jti`
    # claim and the session row is revoked, reject the request even
    # though the JWT signature is valid. Tokens without `jti` (issued
    # before T-5.4.7) skip this check via is_session_active's "missing
    # row → assume active" semantics for back-compat.
    jti = payload.get("jti")
    if isinstance(jti, str) and not auth_service.is_session_active(db, jti):
        raise credentials_exc

    user = auth_service.get_user_by_id(db, user_id)
    if not user:
        raise credentials_exc

    # Best-effort: bump last_used_at so the session-list UI sorts right.
    if isinstance(jti, str):
        auth_service.touch_session(db, jti)

    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    return _resolve_user(token, db)


def require_operator(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """T-5.2.8 / D-111: the caller, if they operate this install; 403
    otherwise. The rule is ``auth_service.is_operator``."""
    if not auth_service.is_operator(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only this install's operator can do this.",
        )
    return current_user


def get_current_jti(
    token: str | None = Depends(oauth2_scheme),
) -> str | None:
    """Return the `jti` claim of the current request's JWT, or None for
    legacy tokens issued before T-5.4.7. Used by the logout endpoint to
    revoke the current session row."""
    if not token:
        return None
    payload = auth_service.decode_token(token)
    if not payload:
        return None
    jti = payload.get("jti")
    return jti if isinstance(jti, str) else None


# There is deliberately no query-string variant of get_current_user. Until
# T-8.8.1.5 (2026-10-25) `get_user_from_query_or_header` let the legacy HTML
# report route and the six /exports downloads take the JWT as `?token=`, which
# leaks it into browser history, server and proxy logs and Referer headers.
# The browser now fetches those files with the Authorization header and hands
# them over as blob: URLs (D-085 addendum). The only route that still reads a
# token from the URL is the /ws/jobs WebSocket (routers/ws.py), because a
# browser cannot send headers on a WebSocket handshake.

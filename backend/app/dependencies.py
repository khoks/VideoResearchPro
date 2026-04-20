from collections.abc import Generator

import redis
from fastapi import Depends, HTTPException, Query, status
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

    user = auth_service.get_user_by_id(db, user_id)
    if not user:
        raise credentials_exc
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    return _resolve_user(token, db)


def get_user_from_query_or_header(
    header_token: str | None = Depends(oauth2_scheme),
    query_token: str | None = Query(None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    # Scoped fallback for requests that can't set an Authorization header
    # (e.g. <iframe src>, window.open). Only apply to read-only endpoints —
    # query-string tokens leak via server logs and Referer headers.
    return _resolve_user(header_token or query_token, db)

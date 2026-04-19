from collections.abc import Generator

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal

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

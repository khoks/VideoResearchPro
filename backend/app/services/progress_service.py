import json
import logging
from datetime import datetime, timezone

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level connection pool + singleton client. Reusing a single pool
# avoids the overhead of opening a fresh TCP connection on every publish
# (previously done via `redis.from_url(...)` per call).
# T-5.4.19: bounded, because a session revocation publishes from inside its
# request, and an unreachable Redis must not hold that for a TCP timeout. Every
# publisher here is fail-soft.
_PUBLISH_TIMEOUT_SECONDS = 2
_redis_pool: redis.ConnectionPool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=_PUBLISH_TIMEOUT_SECONDS,
    socket_timeout=_PUBLISH_TIMEOUT_SECONDS,
)
_redis_client: redis.Redis = redis.Redis(connection_pool=_redis_pool)


def _get_redis() -> redis.Redis:
    """Return the module-level Redis client backed by a connection pool."""
    return _redis_client


def publish_progress(
    job_id: str,
    status: str,
    progress_pct: int,
    message: str,
    data: dict | None = None,
) -> None:
    """Publish a progress event to Redis pub/sub for WebSocket forwarding."""
    payload = {
        "type": "job_progress",
        "job_id": job_id,
        "status": status,
        "progress_pct": progress_pct,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _get_redis().publish(f"job_progress:{job_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to publish progress for job {job_id}: {e}")


def publish_status_change(
    job_id: str,
    old_status: str,
    new_status: str,
    message: str,
) -> None:
    """Publish a job status change event."""
    payload = {
        "type": "job_status_change",
        "job_id": job_id,
        "old_status": old_status,
        "new_status": new_status,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _get_redis().publish(f"job_progress:{job_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to publish status change for job {job_id}: {e}")


def publish_error(job_id: str, error: str) -> None:
    """Publish a job error event."""
    payload = {
        "type": "job_error",
        "job_id": job_id,
        "status": "failed",
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _get_redis().publish(f"job_progress:{job_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to publish error for job {job_id}: {e}")


# T-8.3.3.8: one channel per user. The WebSocket manager subscribes to the
# pattern and reads the user from the CHANNEL name, never from the payload.
NOTIFICATIONS_CHANNEL_PREFIX = "notifications:"

# T-5.4.19: one channel per user, like notifications: the manager reads the
# user from the CHANNEL, so a payload cannot name another user's sockets.
SESSION_REVOKED_CHANNEL_PREFIX = "session_revoked:"


def publish_notification(tenant_id: str, payload: dict) -> bool:
    """Publish a "you have a new notification" event for ``tenant_id``'s
    open sockets. Fail-soft: a Redis outage leaves the bell to its poll.
    Returns whether the publish reached Redis."""
    if not tenant_id:
        return False
    try:
        _get_redis().publish(f"{NOTIFICATIONS_CHANNEL_PREFIX}{tenant_id}", json.dumps(payload))
        return True
    except Exception as e:
        logger.warning(f"Failed to publish a notification for tenant {tenant_id}: {e}")
        return False


def publish_sessions_revoked(tenant_id: str, jtis: list[str]) -> bool:
    """Tell every API process that ``jtis`` are revoked, so each closes the
    sockets it holds on them (T-5.4.19). A publish, as job progress is,
    because the socket may be open on another process.

    Fail-soft: the revocation is already committed, and the manager's
    periodic look at the sessions table closes the socket without this.
    Returns whether the publish reached Redis."""
    if not tenant_id or not jtis:
        return False
    try:
        _get_redis().publish(
            f"{SESSION_REVOKED_CHANNEL_PREFIX}{tenant_id}", json.dumps({"jtis": jtis})
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to publish a session revocation for tenant {tenant_id}: {e}")
        return False

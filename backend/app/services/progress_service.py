import json
import logging
from datetime import datetime, timezone

import redis

from app.config import settings

logger = logging.getLogger(__name__)


def _get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


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
        r = _get_redis()
        r.publish(f"job_progress:{job_id}", json.dumps(payload))
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
        r = _get_redis()
        r.publish(f"job_progress:{job_id}", json.dumps(payload))
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
        r = _get_redis()
        r.publish(f"job_progress:{job_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to publish error for job {job_id}: {e}")

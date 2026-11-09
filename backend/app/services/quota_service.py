"""YouTube Data API quota tracking.

Persists each billable API call to the ``api_quota_log`` table and mirrors the
daily total in Redis (``yt_quota:{YYYY-MM-DD}``) for a fast read path that the
health endpoint can use without touching SQL.
"""

import logging
from datetime import date, datetime, timezone

from app.database import SessionLocal
from app.dependencies import get_redis
from app.models.api_quota_log import ApiQuotaLog
from app.services import usage_service

logger = logging.getLogger(__name__)


# The audio-language lookup is a ``videos.list`` call, with its own name in
# ``api_quota_log`` so the log can tell it from ``get_video_details``
# (T-1.11.11.5). Same price, same feature in ``usage_service.YOUTUBE_FEATURES``.
OPERATION_VIDEOS_AUDIO_LANGUAGE = "videos_audio_language"

# Known YouTube Data API v3 costs per call. See:
# https://developers.google.com/youtube/v3/determine_quota_cost
OPERATION_COSTS: dict[str, int] = {
    "search": 100,
    "videos": 1,
    OPERATION_VIDEOS_AUDIO_LANGUAGE: 1,
    "channels": 1,
    "playlistItems": 1,
}


class QuotaExceededError(RuntimeError):
    """Raised when the YouTube Data API reports quota exhaustion."""

    def __init__(self, message: str = "YouTube API daily quota exceeded") -> None:
        super().__init__(message)
        self.message = message


def _redis_key(for_date: date | None = None) -> str:
    day = (for_date or datetime.now(timezone.utc).date()).isoformat()
    return f"yt_quota:{day}"


def record(operation: str, units: int | None = None) -> None:
    """Record a YouTube API call's quota cost.

    Writes a row to ``api_quota_log`` and increments the Redis daily counter.
    Failures are logged but never propagate — quota accounting must not break
    the caller.

    Args:
        operation: Operation name (e.g. ``search``, ``videos``).
        units: Override cost; falls back to ``OPERATION_COSTS`` then ``1``.
    """
    cost = units if units is not None else OPERATION_COSTS.get(operation, 1)

    # E-5.2: the same units, charged to the tenant whose work made the call
    # (the open metering scope, if any). The install-wide log below is
    # unchanged: /health/quota still reads it.
    usage_service.record_youtube(operation, cost)

    try:
        db = SessionLocal()
        try:
            db.add(ApiQuotaLog(operation=operation, units=cost))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("quota_service.record: DB write failed for operation=%s units=%s",
                         operation, cost)

    try:
        client = get_redis()
        key = _redis_key()
        client.incrby(key, cost)
        # Expire after 48h so yesterday's counter self-cleans.
        client.expire(key, 60 * 60 * 48)
    except Exception:
        logger.exception("quota_service.record: Redis increment failed for operation=%s units=%s",
                         operation, cost)


def get_today_usage() -> int:
    """Return units consumed today (from Redis, falling back to 0)."""
    try:
        client = get_redis()
        value = client.get(_redis_key())
        return int(value) if value is not None else 0
    except Exception:
        logger.exception("quota_service.get_today_usage: Redis read failed")
        return 0

"""S-1.18.2: which on-demand frame captures are running.

A capture downloads the video and makes about a dozen vision calls, so it
runs in the worker (``tasks/visual_tasks.py``) and the page polls. Frames
are per document and shared by every tenant who can see it (they are
derived from the public video, like its transcript), so the marker is per
document too: a second request while one is running gets a 409 instead of
paying for the same frames twice.

Redis is the store because the API and the worker both see it. Every call
is fail-soft: with Redis down, ``in_progress`` reads False and a duplicate
capture is possible but harmless (``run_visual_agent`` is idempotent).
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "visual_extract:"


def _ttl() -> int:
    # Longer than the worker's own wall-clock budget, so a crashed worker's
    # marker expires on its own instead of blocking the document forever.
    return int(settings.VISUAL_CAPTURE_TIMEOUT_SEC) + 300


def _redis():
    from app.dependencies import get_redis

    return get_redis()


def mark_started(document_id: str) -> bool:
    """Claim the document. False when a capture is already running."""
    try:
        return bool(_redis().set(_PREFIX + document_id, "1", nx=True, ex=_ttl()))
    except Exception:  # noqa: BLE001 - fail-soft by design
        logger.warning("visual_extraction: could not set marker for %s", document_id, exc_info=True)
        return True


def mark_finished(document_id: str) -> None:
    try:
        _redis().delete(_PREFIX + document_id)
    except Exception:  # noqa: BLE001
        logger.warning("visual_extraction: could not clear marker for %s", document_id, exc_info=True)


def is_in_progress(document_id: str) -> bool:
    try:
        return bool(_redis().exists(_PREFIX + document_id))
    except Exception:  # noqa: BLE001
        return False

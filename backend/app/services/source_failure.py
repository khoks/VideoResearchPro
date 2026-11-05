"""Why a source could not be searched (T-1.5.14.1).

A connector's ``search()`` raises when the service failed, because an empty
list means "nothing found", and a run reports the two differently. This turns
whatever it raised into something a reader can be told. It carries no
exception text: an exception's message can hold a request URL, and a YouTube
API key is in the query string of one.
"""
from __future__ import annotations

from dataclasses import dataclass

# "refused" is the one that says something about this install: 401 or 403
# means the service will not answer it, so asking again will not help
# (`source_refusal_service`).
REFUSED = "refused"
RATE_LIMITED = "rate_limited"
QUOTA_SPENT = "quota_spent"
FAILED = "failed"


@dataclass(frozen=True)
class SourceFailure:
    kind: str
    status: int | None = None


def _http_status(exc: BaseException) -> int | None:
    """The HTTP status behind ``exc``, looking through a wrapper such as
    ``RedditAuthError``: httpx carries it on ``.response``, the Google client
    on ``.resp``."""
    current: BaseException | None = exc
    while current is not None:
        status = getattr(getattr(current, "response", None), "status_code", None)
        if not isinstance(status, int):
            status = getattr(getattr(current, "resp", None), "status", None)
        if isinstance(status, int):
            return status
        current = current.__cause__
    return None


def classify(exc: BaseException) -> SourceFailure:
    """What a connector's exception says about the source."""
    from app.services.quota_service import QuotaExceededError

    if isinstance(exc, QuotaExceededError):
        return SourceFailure(QUOTA_SPENT, 403)
    status = _http_status(exc)
    if status in (401, 403):
        return SourceFailure(REFUSED, status)
    if status == 429:
        return SourceFailure(RATE_LIMITED, status)
    return SourceFailure(FAILED, status)

"""One retry before a source counts as failed (T-1.5.11.2).

A connector's search raises when the service fails, and the run then tells
its reader the source was unavailable (D-141). One timeout or one 503 is
often gone a second later, so every connector's HTTP client sends its
requests through ``send``, which tries a request a second time, once, after
a short wait, when the first try:

- timed out, or could not connect or lost the connection;
- was answered with a 5xx, unless its ``Retry-After`` asks for longer than
  ``RETRY_AFTER_CEILING_SECONDS``;
- was answered with a 429 whose ``Retry-After`` is at most that ceiling. A
  429 without one, or with a longer one, is the service asking us to stay
  away, and the run reports it as rate limited.

Any other 4xx is an answer, and asking again gets the same one: a 401 or
403 is the refusal that holds a source (D-141), a 404 is a missing thing.

A paid source passes ``UNANSWERED_ONLY``. X bills what it serves (D-139),
so it is retried only when nothing answered: a timeout before any response,
or a connection that never opened. A 5xx or a 429 from X is not retried.

Each try waits its turn on the client's own ``RateLimiter``, so the
``*_RATE_LIMIT_RPM`` pacing holds across a retry, and a request is one call
to ``send`` however many tries it took. None of these clients meters its
requests; YouTube, the one source that does (``quota_service``), does not
come through here.

What reaches the caller is the last try's: its response, which the client
then checks with ``raise_for_status``, or its exception. The log line names
the host and the status or the exception's type, never the address, which
can hold a key or a private feed's token (T-3.7.2.9).
"""
from __future__ import annotations

import email.utils
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.utils.rate_limiter import RateLimiter
from app.utils.shared_url_log import host_of

logger = logging.getLogger(__name__)

#: The wait before the second try, in seconds.
BACKOFF_SECONDS = 1.0

#: The longest ``Retry-After`` worth waiting for. Past it the service is
#: asking for more than a short pause, and the source counts as failed.
RETRY_AFTER_CEILING_SECONDS = 5.0


@dataclass(frozen=True)
class RetryPolicy:
    """Which first tries get a second.

    ``answered``: also retry a request the service answered with a 5xx or a
    short-``Retry-After`` 429. ``transient``: the exceptions that mean the
    request may never have been served.
    """

    answered: bool
    transient: tuple[type[BaseException], ...]


#: Every free source: a timeout, a connection error, a 5xx, a short 429.
DEFAULT = RetryPolicy(
    answered=True,
    transient=(httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError),
)

#: X: only a request nothing answered. A timeout is before any response;
#: a ``ConnectError`` is before the request was sent. A connection that broke
#: while reading (``ReadError``) may have carried a billed answer.
UNANSWERED_ONLY = RetryPolicy(
    answered=False,
    transient=(httpx.TimeoutException, httpx.ConnectError),
)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def send(
    request: Callable[[], httpx.Response],
    *,
    url: str,
    limiter: RateLimiter | None,
    policy: RetryPolicy = DEFAULT,
) -> httpx.Response:
    """Make ``request`` (one HTTP call), and once more if the first try
    failed in a way that a second can fix. ``url`` is for the log line."""
    for attempt in (1, 2):
        if limiter is not None:
            limiter.wait()
        try:
            response = request()
        except policy.transient as exc:
            if attempt == 2:
                raise
            delay, reason = BACKOFF_SECONDS, type(exc).__name__
        else:
            delay = _retry_delay(response, policy) if attempt == 1 else None
            if delay is None:
                return response
            reason = str(response.status_code)
        logger.info(
            "%s: %s; trying once more in %.1fs",
            host_of(url),
            reason,
            delay,
        )
        _sleep(delay)
    raise AssertionError("unreachable: the second try returns or raises")


def _retry_delay(response: httpx.Response, policy: RetryPolicy) -> float | None:
    """Seconds to wait before a second try, or None for no second try."""
    status = getattr(response, "status_code", None)
    if not policy.answered or not isinstance(status, int):
        return None
    if status >= 500:
        after = _retry_after_seconds(response)
        if after is None:
            return BACKOFF_SECONDS
        return max(after, BACKOFF_SECONDS) if after <= RETRY_AFTER_CEILING_SECONDS else None
    if status == 429:
        after = _retry_after_seconds(response)
        if after is not None and after <= RETRY_AFTER_CEILING_SECONDS:
            return max(after, BACKOFF_SECONDS)
    return None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """``Retry-After`` in seconds (delta or HTTP date), None when absent or
    unreadable."""
    headers = getattr(response, "headers", None)
    try:
        value = headers.get("Retry-After") if headers is not None else None
    except Exception:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        pass
    else:
        return max(0.0, seconds) if math.isfinite(seconds) else None
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())

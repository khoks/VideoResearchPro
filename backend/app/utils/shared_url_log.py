"""A shared link stays out of the logs, all but its host (T-3.7.2.9).

A link a user pasted or shared can carry something private anywhere after the
host: a token in the query string, a name in the path. So a log line about one
says the host and nothing else, and says the exception's type rather than its
text, because that text can quote the URL (``raise_for_status``, Playwright's
"navigating to ...").

httpx writes a line of its own for every request, whole URL included, at INFO,
and a Celery worker logs at INFO. ``shared_url_fetch`` silences that line
around a fetch of a shared link and leaves every other caller's alone.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

_UNREADABLE = "an unreadable address"

_fetching_shared_url: ContextVar[bool] = ContextVar("fetching_shared_url", default=False)


def host_of(url: object) -> str:
    """The host of ``url``, for a log line. Without any ``user:password@``."""
    try:
        return urlsplit(url).hostname or _UNREADABLE  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError):
        return _UNREADABLE


class _HttpxRequestLine(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _fetching_shared_url.get()


# On the logger itself: httpx logs to "httpx", not a child of it, and a logger's
# filter is the one place that sees the record in every process.
logging.getLogger("httpx").addFilter(_HttpxRequestLine())


@contextmanager
def shared_url_fetch() -> Iterator[None]:
    """httpx writes no request line inside this. Also usable as a decorator."""
    token = _fetching_shared_url.set(True)
    try:
        yield
    finally:
        _fetching_shared_url.reset(token)

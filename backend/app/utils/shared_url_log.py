"""A shared link stays out of the logs, all but its host (T-3.7.2.9), and so do
the user's words a request carries (T-4.11.4.2).

A link a user pasted or shared can carry something private anywhere after the
host: a token in the query string, a name in the path. A private podcast feed
(T-1.7.1.6) is the same, and so are the audio and transcript links in it. So a
log line about one says the host and nothing else, and says the exception's
type rather than its text, because that text can quote the URL
(``raise_for_status``, Playwright's "navigating to ...").

A search request is the same: its URL holds the user's own words, a topic or a
query a planner wrote from one, in its query string (``?q=``) or its path
(Mastodon's hashtag timeline). So does a YouTube ``HttpError``, which quotes
the request it answered, and so does a channel the user named, which can be a
pasted link. ``traceback_without_text`` keeps where such an exception was
raised and drops what it said, and ``loggable_channel_input`` says what kind of
channel input a line is about without repeating it.

httpx writes a line of its own for every request, whole URL included, at INFO,
and a Celery worker logs at INFO. ``shared_url_fetch`` silences that line
around a fetch of a shared link, or a search, and leaves every other caller's
alone.

The API's own warnings and errors follow the same rule (T-4.11.4.4): a file
name the user chose goes by ``loggable_filename``, and a failure whose text
can restate what the user wrote, a model's reply over an incoming message or
a draft for one, goes by ``exception_kind``.
"""
from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

_UNREADABLE = "an unreadable address"

_URL_IN_AN_ID = re.compile(r"[a-z][a-z0-9+.-]*://\S*", re.IGNORECASE)

_fetching_shared_url: ContextVar[bool] = ContextVar("fetching_shared_url", default=False)


def host_of(url: object) -> str:
    """The host of ``url``, for a log line. Without any ``user:password@``."""
    try:
        return urlsplit(url).hostname or _UNREADABLE  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError):
        return _UNREADABLE


def loggable_id(source_id: str) -> str:
    """``source_id`` for a log line. An id can hold a URL: a feed entry with no
    guid goes by its link or its audio file (``podcast._episode_guid``), so any
    URL in it comes down to its host."""
    return _URL_IN_AN_ID.sub(lambda url: host_of(url[0]), source_id)


# A YouTube channel id, and a handle: the channel's own public name.
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_HANDLE = re.compile(r"@[\w.-]{1,100}")
# A link pasted without its scheme: `youtube.com/@name`, `www.youtube.com/...`.
_BARE_LINK = re.compile(r"[\w-]+(\.[\w-]+)+/", re.ASCII)


def is_channel_id(value: object) -> bool:
    """Whether ``value`` is exactly a YouTube channel id: ``UC`` and 22 more
    of its alphabet. "UC Berkeley Data Science" is 24 characters starting with
    ``UC`` too, and is a name the user typed, not an id."""
    return isinstance(value, str) and _CHANNEL_ID.fullmatch(value) is not None


def loggable_channel_input(channel_input: object) -> str:
    """A channel a user named, for a log line (T-4.11.4.2).

    A channel id or an ``@handle`` is the channel's public name and stands as
    written. A link comes down to its host, since anything after it can carry
    something private, a share's tracking id for one. Anything else is the
    user's own words, the name a search falls back on, and goes by its length.
    """
    value = str(channel_input or "").strip()
    if _CHANNEL_ID.fullmatch(value) or _HANDLE.fullmatch(value):
        return value
    if "://" in value:
        return f"a link on {host_of(value)}"
    if _BARE_LINK.match(value):
        return f"a link on {host_of('https://' + value)}"
    return f"a name of {len(value)} characters"


# A file's extension, as an operator would want to read it: short, plain.
_EXTENSION = re.compile(r"\.([A-Za-z0-9]{1,8})$")


def loggable_filename(name: object) -> str:
    """A file name a user chose, for a log line (T-4.11.4.4): its extension
    and its length, never the name. An export is often named after the person
    it is with ("WhatsApp Chat with Asha.txt"), and a renamed one after
    whatever the user had in mind."""
    value = str(name or "")
    base = value.replace("\\", "/").rsplit("/", 1)[-1]
    found = _EXTENSION.search(base)
    if found is None:
        return f"a file name of {len(value)} characters with no extension"
    return f"a .{found[1].lower()} file name of {len(value)} characters"


def _http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def exception_kind(exc: BaseException) -> str:
    """``exc`` for a log line by what it is, never by what it says
    (T-4.11.4.4): its type, and the HTTP status a provider's error carries,
    as ``RateLimitError (HTTP 429)``. For a fail-soft line over a model call
    whose prompt holds the user's own words or an incoming message: the
    exception can come from reading the reply, which restates them, as well
    as from the provider. What a provider says about a model it will not
    serve is on ``/health/llm``, from the startup probe's one-word prompt."""
    status = _http_status(exc)
    name = type(exc).__name__
    return f"{name} (HTTP {status})" if status is not None else name


_CAUSE = "\nThe above exception was the direct cause of the following exception:\n\n"
_CONTEXT = "\nDuring handling of the above exception, another exception occurred:\n\n"


def _type_name(exc: BaseException) -> str:
    cls = type(exc)
    return cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"


def traceback_without_text(exc: BaseException) -> str:
    """``exc``'s traceback with what each exception said left out (T-4.11.4.2).

    The frames and the types stay, so an operator still sees where and how it
    failed; the words go, because an ``HttpError`` or an httpx error quotes the
    request URL, and a search's URL holds the user's words. A cause or a
    context is shown as Python shows it, oldest first. A log line passes this
    as an argument at ``logger.error`` in place of ``logger.exception``, whose
    traceback would repeat the words.
    """
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        try:
            frames = "".join(traceback.format_tb(current.__traceback__))
        except Exception:  # noqa: BLE001 - a log line must not raise
            frames = ""
        head = "Traceback (most recent call last), what it said left out:\n" if frames else ""
        parts.append(f"{head}{frames}{_type_name(current)}\n")
        if current.__cause__ is not None:
            parts.append(_CAUSE)
            current = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            parts.append(_CONTEXT)
            current = current.__context__
        else:
            current = None
    return "".join(reversed(parts)).rstrip("\n")


class _HttpxRequestLine(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _fetching_shared_url.get()


# On the logger itself: httpx logs to "httpx", not a child of it, and a logger's
# filter is the one place that sees the record in every process.
logging.getLogger("httpx").addFilter(_HttpxRequestLine())


@contextmanager
def shared_url_fetch() -> Iterator[None]:
    """httpx writes no request line inside this. Also usable as a decorator,
    on a fetch of a shared link and on a search, whose URL holds the user's
    words."""
    token = _fetching_shared_url.set(True)
    try:
        yield
    finally:
        _fetching_shared_url.reset(token)

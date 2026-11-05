"""Credentials stay out of the logs. Two nets, each for one way one gets in.

**A credential in a URL (T-5.4.23).** No route reads one, but a client can
still send one, an old tab's ``/ws/jobs?token=<JWT>`` for one, and uvicorn writes
the path it was asked for. ``_UrlCredentialFilter`` sits on ``uvicorn.error``
and ``uvicorn.access`` and redacts it from ``record.args``, which is where
uvicorn puts the path. On the logger itself, so it holds under either
``LOG_FORMAT`` and whichever handlers are attached. uvicorn configures logging
before it imports the app and never clears a logger's filters.

**A key in a provider's error (T-5.6.16).** OpenAI quotes part of a key it
refuses, and ``googleapiclient`` puts the YouTube key in every ``HttpError``'s
URL. Such an exception can reach a log line at dozens of call sites in the
agents alone: as an argument, in an f-string, or as the traceback of
``logger.exception``, which the formatter renders long after any filter on the
message has run. So this works on the record as it is made
(``logging.setLogRecordFactory``): every logger, every process that imports
``app``, whatever handlers Celery or uvicorn set up.

- An exception from a model SDK that means "this key may not be used", or one
  caused by it, is named by its type alone (``provider_error_text``), the rule
  the Whisper path has followed since T-5.6.13.
- Any other text has the shapes of a key taken out (``scrub_keys``).
- A traceback is rendered here, scrubbed the same way, and left on the record as
  ``exc_text``, which every formatter writes as it stands.

Not covered: anything that is not a log record (``print``, a file a library
writes), and a key in a shape ``scrub_keys`` does not know, inside an exception
that is not a refusal, or inside a dict or list passed as an argument.
"""
from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Callable, Iterator, Mapping

REDACTED = "[redacted]"

# The names a credential in a query string goes by. Also the list
# `tests/test_routers/test_url_tokens.py` holds every route to.
CREDENTIAL_QUERY_NAMES = frozenset({"token", "access_token", "jwt", "auth", "authorization"})

# An OAuth callback has to take its code from the URL, so it is not on the list
# above. It is single-use, but a line in a log is no place for it either.
_LOGGED_QUERY_NAMES = CREDENTIAL_QUERY_NAMES | {"code"}


def _spelled(name: str) -> str:
    """A pattern for ``name``, percent-encoded letters included: a server
    decodes a query name, so ``%74oken`` is ``token``."""
    return "".join(f"(?:{re.escape(letter)}|%{ord(letter):02x})" for letter in name)


_URL_CREDENTIAL = re.compile(
    r"(?i)(?<=[?&;])(" + "|".join(_spelled(name) for name in sorted(_LOGGED_QUERY_NAMES)) + r")=[^&#\s]*"
)

# `eyJ` is how every JWT starts, being `{"` in base64url. At --log-level debug
# the websockets library logs each handshake header through `uvicorn.error`, the
# subprotocol list that carries the token included.
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*")


def redact_url_credentials(text: str) -> str:
    """``text`` with the value of every credential query parameter, and any
    JWT at all, replaced. Everything else stands, so a path stays readable."""
    return _JWT.sub(REDACTED, _URL_CREDENTIAL.sub(lambda m: f"{m[1]}={REDACTED}", text))


# OpenAI's sentence goes first: a key that is not `sk-` shaped is quoted in it
# too. Then OpenAI and Anthropic keys, whole or starred out, Google's, and a
# key in a URL, which is how the YouTube client sends one.
_KEY_TEXT = re.compile(
    r"(?P<lead>(?i:incorrect api key provided:\s*)|(?<=[?&])(?i:key|api_?key)=)[^\s&\"'<>]+"
    r"|\bsk-[\w*.-]{4,}"
    r"|\bAIza[\w*-]{8,}"
)


def scrub_keys(text: str) -> str:
    """``text`` with anything shaped like a provider's key taken out."""
    return _KEY_TEXT.sub(lambda m: f"{m['lead'] or ''}{REDACTED}", text)


# What each SDK calls "this key may not be used". By name, not by import: an SDK
# takes a second to load, and this runs on every logged exception.
_REFUSAL_CLASSES = frozenset({"AuthenticationError", "PermissionDeniedError", "Unauthenticated", "PermissionDenied"})
_MODEL_SDKS = frozenset({"openai", "anthropic", "google"})


def _is_refusal(exc: BaseException) -> bool:
    return any(
        cls.__name__ in _REFUSAL_CLASSES and cls.__module__.partition(".")[0] in _MODEL_SDKS
        for cls in type(exc).__mro__
    )


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """``exc`` and what caused it, as a traceback would show them."""
    seen: BaseException | None = exc
    for _ in range(8):  # a chain is short, and can loop
        if seen is None:
            return
        yield seen
        seen = seen.__cause__ or (None if seen.__suppress_context__ else seen.__context__)


def _text_of(value: object) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - a __str__ can do anything, and this is on the way to a log line
        return type(value).__name__


def provider_error_text(exc: BaseException) -> str:
    """What a log line may say about a failed call. A key the provider refused
    comes back quoted in part, so a refusal goes by its type alone."""
    if any(_is_refusal(seen) for seen in _chain(exc)):
        return type(exc).__name__
    return scrub_keys(_text_of(exc))


def _safe(value: object) -> object:
    """``value`` as a log line may show it: itself, unless it holds a key."""
    if isinstance(value, str):
        return scrub_keys(value)
    if isinstance(value, BaseException):
        text = provider_error_text(value)
        return value if text == _text_of(value) else text
    return value


def _map_args(args: object, change: Callable[[object], object]) -> object:
    """``args`` with ``change`` applied to each, in the same shape: uvicorn's
    access formatter unpacks a five-tuple, and Celery logs with a mapping."""
    if isinstance(args, Mapping):
        return {key: change(value) for key, value in args.items()}
    if isinstance(args, tuple):
        return tuple(change(value) for value in args)
    return args


def _scrub_traceback(record: logging.LogRecord) -> None:
    """Leave a traceback that needs scrubbing on the record as text. ``exc_info``
    goes too: Python's formatter would keep ``exc_text`` anyway, and the JSON
    one reads ``exc_info`` first."""
    exc_info = record.exc_info
    if not exc_info or exc_info[1] is None:
        return
    try:
        rendered = "".join(traceback.format_exception(*exc_info)).rstrip("\n")
        safe = rendered
        for seen in _chain(exc_info[1]):
            if _is_refusal(seen) and (quoted := _text_of(seen)):
                safe = safe.replace(quoted, REDACTED)
        safe = scrub_keys(safe)
    except Exception:  # noqa: BLE001 - a log call must not raise, and what was unreadable cannot be shown
        safe, rendered = f"{exc_info[0].__name__} (traceback unreadable)", ""
    if safe != rendered:
        record.exc_text = safe
        record.exc_info = None


_make_record: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()


def _scrubbed_record(*args: object, **kwargs: object) -> logging.LogRecord:
    record = _make_record(*args, **kwargs)
    record.msg = _safe(record.msg)
    record.args = _map_args(record.args, _safe)
    _scrub_traceback(record)
    return record


class _UrlCredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value: object) -> object:
            return redact_url_credentials(value) if isinstance(value, str) else value

        record.msg = redact(record.msg)
        record.args = _map_args(record.args, redact)
        return True


_URL_CREDENTIAL_FILTER = _UrlCredentialFilter()


def install_log_redaction() -> None:
    """Both nets, once per process however often it is called."""
    global _make_record
    for name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(_URL_CREDENTIAL_FILTER)
    if logging.getLogRecordFactory() is not _scrubbed_record:
        _make_record = logging.getLogRecordFactory()
        logging.setLogRecordFactory(_scrubbed_record)

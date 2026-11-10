"""Credentials stay out of the logs. Two nets, each for one way one gets in.

**A credential in a URL (T-5.4.23).** No route reads one, but a client can
still send one, an old tab's ``/ws/jobs?token=<JWT>`` for one, and uvicorn writes
the path it was asked for. ``_UrlCredentialFilter`` sits on ``uvicorn.error``
and ``uvicorn.access`` and redacts it from ``record.args``, which is where
uvicorn puts the path. On the logger itself, so it holds under either
``LOG_FORMAT`` and whichever handlers are attached. uvicorn configures logging
before it imports the app and never clears a logger's filters.

**A user's words in a URL (T-4.11.4.5).** The access log writes each request's
query string as it was sent, and a search box sends what the user typed:
``GET /api/v1/search?q=...``. The same filter writes the value of each
parameter in ``WORDS_QUERY_NAMES`` by its length (``q=[12 characters]``) and
leaves the path, the other parameters and the status as they were. So one
filter decides what the access log may write of a URL, by what each
parameter is named.

**A user's words in a URL's path (T-4.11.4.8).** One route takes them there:
``DELETE /api/v1/echo/context/{kind}/{key:path}``, whose key is a fact's,
which the user types, and is the rest of the path, every ``/`` in it included
(S-3.1.1). The same filter matches each path against the templates in
``WORDS_PATH_PARAMS`` and writes each words segment by its length
(``/api/v1/echo/context/interest/[12 characters]``), the method, the other
segments, the query and the status as they were. A path no such template
matches is written whole: no page builds one, and an operator reading a 404
needs it as it came.

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
- Any other text has the shapes of a key taken out (``scrub_keys``). An
  argument that is not text, a dict, a list, bytes, is judged by the text the
  line will show for it, and replaced by that text scrubbed when it held one.
- A traceback is rendered here, scrubbed the same way, and left on the record as
  ``exc_text``, which every formatter writes as it stands.

Not covered: anything that is not a log record (``print``, a file a library
writes), and a key in a shape ``scrub_keys`` does not know anywhere but in a
refusal itself: a refusal's words copied into a dict or a string go by shape
alone. So a log line passes the exception, never ``e.body`` or a response.

**What is not a log record (T-5.6.17).** A failed run's ``error_message``, the
socket's error event, a saved search's ``last_error``, an API answer: none of
them passes the record factory, and a tenant reads some of them. Each such
place that keeps an exception's words takes them from ``error_summary``, the
same rule with the exception's class in front.
"""
from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType
from urllib.parse import unquote, unquote_plus

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


# The query parameters whose value is a user's own words (T-4.11.4.5): a
# search box's (`q` on /search, /notes, /echo/shares and
# /author/knowledge-sources), a filter's (`search` on /library/videos and on a
# shelf's documents), and the library map's `focus`, a node id, which for a
# topic is the topic's label. Every other parameter a route reads is an id,
# an enum, a number, a date or a flag, and stands.
# `tests/test_utils/test_access_log_words.py` holds every route's parameters
# to this list or to its own list of kept ones.
WORDS_QUERY_NAMES = frozenset({"q", "search", "focus"})

# Such a parameter wherever a name can start, as the credential pattern finds
# one, a `;` included. Its value runs to the next `&`, as the server reads it:
# Starlette splits a query string on `&` alone, so a `;`, a `#` or a `?`
# inside a value is still that value's. Whitespace ends one too, for a URL
# quoted in a sentence. Only these names match, so no other parameter's value
# is read past, and one hidden inside another's value is caught as well.
_QUERY_WORDS = re.compile(
    r"(?i)(?<=[?&;])(?P<name>" + "|".join(_spelled(name) for name in sorted(WORDS_QUERY_NAMES)) + r")"
    r"=(?P<value>[^&\s]+)"
)


def _characters(count: int) -> str:
    return f"[{count} character{'' if count == 1 else 's'}]"


def redact_query_words(text: str) -> str:
    """``text`` with the value of every parameter in ``WORDS_QUERY_NAMES``
    written as its length, counted as the route reads it: percent-decoded,
    with ``+`` a space. A name matches in any case and percent-encoded, since
    ``%71`` is ``q``. An empty value has nothing to hide and stands, as does
    everything else."""
    return _QUERY_WORDS.sub(lambda found: f"{found['name']}={_characters(len(unquote_plus(found['value'])))}", text)


# The path parameters whose value is a user's own words (T-4.11.4.8), by the
# template of the route that reads each, as the app serves it, convertor
# included: a fact's key, which the user types on the Echo page, and which is
# the rest of the path (S-3.1.1). Every other path parameter is an id, a
# digest, a session's jti or a name from a fixed set (a provider, a use case,
# a connector, a context kind), and stands.
# `tests/test_utils/test_access_log_words.py` holds every route's path
# parameters to this or to its own list of kept ones.
WORDS_PATH_PARAMS: Mapping[str, frozenset[str]] = MappingProxyType({
    "/api/v1/echo/context/{kind}/{key:path}": frozenset({"key"}),
})

_PATH_PARAM = re.compile(r"\{(?P<name>\w+)(?::(?P<convertor>\w+))?\}")


def _template_pattern(template: str, words: frozenset[str]) -> re.Pattern[str]:
    """The paths ``template`` matches, each words parameter a named group.

    uvicorn writes the path it routed, decoded and percent-encoded again, so a
    segment is matched as Starlette matches it, ``[^/]+``. A words value alone
    may run over a ``/``: the route decodes ``%2F`` before it matches, so a key
    holding one comes out as more segments than its template names, and it is
    still the user's. A words ``:path`` parameter takes the rest of the path as
    Starlette's ``.*`` does, a trailing ``/`` included, since the route reads
    that ``/`` as the key's (S-3.1.1); anywhere else a trailing ``/`` stands.
    A raw ``?`` starts the query, so no value runs past one, and a decoded
    ``?`` or ``#`` in a key is written ``%3F`` or ``%23``, inside the segment.
    The literal parts match in any case and percent-encoded, and the path may
    sit anywhere in the text: after a host, a root path or a space."""
    parts, end = [], 0
    for found in _PATH_PARAM.finditer(template):
        parts.append(_spelled(template[end:found.start()]))
        if found["name"] in words:
            lazy = "" if found["convertor"] == "path" else "?"
            parts.append(rf"""(?P<{found['name']}>[^?\s"']+{lazy})""")
        elif found["convertor"] == "path":
            parts.append(r"""[^?\s"']*?""")
        else:
            parts.append(r"""[^/?\s"']+""")
        end = found.end()
    parts.append(_spelled(template[end:]))
    return re.compile("(?i)" + "".join(parts) + r"""/?(?=[?\s"']|$)""")


_PATH_WORDS = tuple(_template_pattern(template, words) for template, words in WORDS_PATH_PARAMS.items())


def _segments_by_length(found: re.Match[str]) -> str:
    """The matched path with each words group written as its length, counted
    as the route reads it: percent-decoded, a ``+`` being a ``+`` in a path."""
    text, origin, pieces, last = found[0], found.start(), [], 0
    for name, value in found.groupdict().items():
        if value is None:
            continue
        start, stop = found.span(name)
        pieces += [text[last:start - origin], _characters(len(unquote(value)))]
        last = stop - origin
    return "".join(pieces) + text[last:]


def redact_path_words(text: str) -> str:
    """``text`` with the value of every words path parameter written as its
    length, where a path matches its route's template. Everything else
    stands, a path no template matches included."""
    for pattern in _PATH_WORDS:
        text = pattern.sub(_segments_by_length, text)
    return text


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


def error_summary(exc: BaseException, limit: int | None = None) -> str:
    """What a stored row, a published event or an API answer may say about a
    failed call (T-5.6.17): ``Class: words``, the words as
    ``provider_error_text`` leaves them, or the class alone when that left
    nothing else. Cut to ``limit`` after the scrub, since half a key is still
    a leak."""
    name = type(exc).__name__
    text = provider_error_text(exc).strip()
    summary = name if not text or text == name else f"{name}: {text}"
    return summary[:limit] if limit else summary


# What cannot hold a key, so is left alone without being rendered.
_PLAIN = (int, float, bool, type(None))


def _safe(value: object) -> object:
    """``value`` as a log line may show it: itself, unless it holds a key."""
    if isinstance(value, str):
        return scrub_keys(value)
    if isinstance(value, BaseException):
        text = provider_error_text(value)
        return value if text == _text_of(value) else text
    if isinstance(value, _PLAIN):
        return value
    # A dict, a list, bytes, a response: the line will show its text, so its
    # text is what is judged. A provider's body nested in a dict is caught here.
    text = _text_of(value)
    safe = scrub_keys(text)
    return value if safe == text else safe


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
    """What uvicorn may write of a URL it was asked for: no credential
    (T-5.4.23) and no user's words, in the query (T-4.11.4.5) or the path
    (T-4.11.4.8). The access line's path is one of its arguments, so each
    argument is redacted where it stands."""

    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value: object) -> object:
            if not isinstance(value, str):
                return value
            return redact_query_words(redact_url_credentials(redact_path_words(value)))

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

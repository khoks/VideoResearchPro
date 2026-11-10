"""T-4.11.4.5: uvicorn's access log writes no user's search words.

uvicorn writes each request's path and query string at INFO, and the
launchers send that to ``.uvicorn.out.log``. A search box sends what the user
typed (``GET /api/v1/search?q=...``), so the filter D-151 put on
``uvicorn.access`` writes the value of every parameter in
``WORDS_QUERY_NAMES`` by its length and leaves the rest of the line alone.

- Every query parameter of every route is either a words parameter, by name,
  or kept, by route and name, with the reason it is not words. A new
  parameter in neither fails ``test_every_query_parameter_is_words_or_kept``.
- Each route with a words parameter: a record built as uvicorn builds it
  (the scope's raw query string, ``get_path_with_query_string``, the access
  line's five arguments), through the real filter and uvicorn's own access
  formatter and the app's JSON one, shows the path, the other parameters, the
  status and the value's length, and not the words.
- The real server: ``app.main:app`` under the real uvicorn CLI, asked each of
  those routes, writes none of the words to its log.

Mutation checks (each failed the named tests when this shipped):

- the filter calling ``redact_url_credentials`` alone
  (``test_each_words_route_is_written_by_length``,
  ``test_the_real_server_writes_no_search_words``, and in-suite as
  ``test_the_check_sees_a_leak``);
- ``focus`` taken out of ``WORDS_QUERY_NAMES``
  (``test_each_words_route_is_written_by_length[graph]``);
- ``unquote_plus`` replaced by the raw value's length
  (``test_a_value_is_counted_as_the_route_reads_it``);
- the value stopping at a ``;`` or a ``#``
  (``test_a_value_is_counted_as_the_route_reads_it``);
- the name matched only as written, not percent-encoded or in another case
  (``test_a_value_is_counted_as_the_route_reads_it``);
- the lookbehind without ``&`` (``test_a_value_is_counted_as_the_route_reads_it``,
  on a repeated parameter).
"""
from __future__ import annotations

import io
import json
import logging
import re
from urllib.parse import quote

import httpx
import pytest
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter
from uvicorn.protocols.utils import get_path_with_query_string

from app.utils import log_redaction
from app.utils.json_logging import JsonFormatter
from app.utils.log_redaction import WORDS_QUERY_NAMES, install_log_redaction, redact_query_words
from tests.test_routers.test_url_tokens import _query_param_names, _served_routes
from tests.test_utils.test_log_redaction import _env, _log_of, _uvicorn

WORDS = "Zanzibar quokka fermentation & tariffs #2"
HINDI = "अहिंसा परमो धर्मः"
TOPIC = "topic:zanzibar quokka"
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "tariffs", "अहिंसा", "%E0%A4")
SHELF = "5f0c6a52-2b8e-4a55-8f8d-0f5e3c1d9a77"

# Every parameter that is not a user's words, by route, with why. Read from
# each router's parameters on 2026-11-10.
KEPT: dict[str, dict[str, str]] = {
    "/api/v1/auth/audit-log": {"limit": "number", "offset": "number", "scope": "enum: all, account"},
    "/api/v1/auth/sessions": {"keep_current": "flag"},
    "/api/v1/auth/oauth/{provider}/start": {
        "redirect_uri": "the app's own sign-in return, an allowed origin and a fixed path",
    },
    "/api/v1/auth/oauth/{provider}/callback": {
        "code": "single-use; D-151 redacts it",
        "state": "random, matched to the server's own record",
    },
    "/api/v1/suggestions": {"context": "library, job:<id> or document:<id>"},
    "/api/v1/notifications": {"unread_only": "flag", "limit": "number"},
    "/api/v1/echo/activity": {"connector": "a connector's name", "before": "date", "limit": "number"},
    "/api/v1/echo/signals": {"signal_type": "enum", "language": "language code"},
    "/api/v1/echo/drafts": {"limit": "number"},
    "/api/v1/echo/cards": {"context": "library, job:<id> or document:<id>"},
    "/api/v1/echo/cards/dismiss": {"key": "a card's kind and an id"},
    "/api/v1/echo/cards/shown": {"key": "a card's kind and an id"},
    "/api/v1/echo/cards/act": {"key": "a card's kind and an id"},
    "/api/v1/echo/context": {"kind": "enum", "source": "a connector's name or user", "include_expired": "flag"},
    "/api/v1/echo/shares": {
        "state": "enum",
        "limit": "number",
        "offset": "number",
        "origin": "enum: direct, import, all",
        "import_id": "id",
    },
    "/api/v1/echo/brain": {"confirm": "the fixed phrase delete-everything"},
    "/api/v1/author/knowledge-sources": {"limit": "number"},
    "/api/v1/author/outputs": {"sync": "flag", "kind": "enum", "status": "enum"},
    "/api/v1/author/outputs/{output_id}/download": {"format": "enum, [a-z0-9]{1,8}"},
    "/api/v1/author/newsletter/send-now": {"sync": "flag"},
    "/api/v1/jobs": {
        "template_id": "id",
        "template_version": "number",
        "status": "enum",
        "limit": "number",
        "offset": "number",
    },
    "/api/v1/channels/{channel_id}/intelligence": {"refresh": "flag"},
    "/api/v1/shelves/{shelf_id}/documents": {
        "language": "language code",
        "channel_id": "id",
        "transcript_status": "enum",
        "tag": "a tag's id",
        "sort": "enum",
        "limit": "number",
        "offset": "number",
    },
    "/api/v1/shelves/{shelf_id}/qa": {"limit": "number", "offset": "number"},
    "/api/v1/tags/{tag_id}": {"into": "a tag's id"},
    "/api/v1/jobs/{job_id}/qa": {"limit": "number", "offset": "number"},
    "/api/v1/library/qa": {"limit": "number", "offset": "number"},
    "/api/v1/library/graph": {
        "depth": "number",
        "shelf_id": "id",
        "channel_id": "id",
        "job_id": "id",
        "types": "enums, comma-separated",
        "limit": "number",
    },
    "/api/v1/library/video-channels": {"video_ids": "YouTube ids, comma-separated"},
    "/api/v1/library/videos": {
        "language": "language code",
        "channel_id": "id",
        "transcript_status": "enum",
        "tag": "a tag's id",
        "document_id": "id",
        "sort": "enum",
        "limit": "number",
        "offset": "number",
    },
    "/api/v1/qa-history/exchanges": {"limit": "number", "offset": "number"},
    "/api/v1/videos/{video_id}/extract-knowledge": {"force": "flag", "output_length": "enum"},
    "/api/v1/videos/{video_id}/extract-frames": {"force": "flag"},
    "/api/v1/search": {"types": "enums, comma-separated", "limit": "number"},
    "/api/v1/notes": {
        "target": "a target's kind and id",
        "target_type": "enum",
        "include_deleted": "flag",
        "limit": "number",
        "offset": "number",
    },
    "/api/v1/admin/restart": {"skip_frontend": "flag", "delay": "number"},
    "/api/v1/exports/notes.jsonl": {"include_deleted": "flag"},
    "/api/v1/exports/notes.md": {"include_deleted": "flag"},
}

# Each route a words parameter reaches, with a path a client would ask for and
# the other parameters its page sends beside it.
WORDS_ROUTES = {
    "search": ("/api/v1/search", "/api/v1/search", {"q": WORDS, "limit": "5"}),
    "notes": ("/api/v1/notes", "/api/v1/notes", {"q": WORDS, "include_deleted": "false", "limit": "500"}),
    "shares": ("/api/v1/echo/shares", "/api/v1/echo/shares", {"q": HINDI, "state": "processed", "limit": "100"}),
    "knowledge-sources": (
        "/api/v1/author/knowledge-sources", "/api/v1/author/knowledge-sources", {"q": WORDS, "limit": "200"},
    ),
    "library": ("/api/v1/library/videos", "/api/v1/library/videos", {"search": WORDS, "sort": "newest"}),
    "shelf": (
        "/api/v1/shelves/{shelf_id}/documents", f"/api/v1/shelves/{SHELF}/documents", {"search": HINDI, "limit": "100"},
    ),
    "graph": ("/api/v1/library/graph", "/api/v1/library/graph", {"focus": TOPIC, "depth": "2"}),
}


def _query_params() -> dict[str, set[str]]:
    """Every query parameter each route reads, its dependencies' included,
    by full path. Through ``test_url_tokens._served_routes``, which reads the
    route table both as FastAPI 0.135 keeps it and as 0.162 does."""
    found: dict[str, set[str]] = {}
    for path, _route, dependant in _served_routes():
        names = _query_param_names(dependant)
        if names:
            found.setdefault(path, set()).update(names)
    assert found, "no route's parameters were found, so nothing was checked"
    return found


def test_every_query_parameter_is_words_or_kept():
    """A parameter is redacted by name, or kept on its route for a reason.
    One in neither list is a decision nobody has made yet."""
    params = _query_params()
    unsorted = sorted(
        f"{path}?{name}" for path, names in params.items() for name in names
        if name not in WORDS_QUERY_NAMES and name not in KEPT.get(path, {})
    )
    assert not unsorted, (
        "Query parameters in neither list: add each to log_redaction.WORDS_QUERY_NAMES if it can carry "
        f"a user's own words, else to KEPT here with the reason: {unsorted}"
    )
    stale = sorted(
        f"{path}?{name}" for path, names in KEPT.items() for name in names if name not in params.get(path, set())
    )
    assert not stale, f"Kept parameters no route reads any more: {stale}"


def test_every_words_parameter_is_checked_on_its_route():
    """The routes below are every route that reads a words parameter."""
    reached = {(path, name) for path, names in _query_params().items() for name in names if name in WORDS_QUERY_NAMES}
    checked = {(template, name) for template, _, query in WORDS_ROUTES.values() for name in query
               if name in WORDS_QUERY_NAMES}
    assert reached == checked
    assert {name for _, name in reached} == WORDS_QUERY_NAMES, "a words name no route reads"


def axios_query(params: dict[str, str]) -> str:
    """A query string as the frontend's axios writes one: encodeURIComponent,
    then a space as ``+`` and ``:``, ``$``, ``,``, ``[``, ``]`` left as they are."""
    def encode(value: str) -> str:
        text = quote(value, safe="-_.!~*'()")
        for code, char in (("%3A", ":"), ("%24", "$"), ("%2C", ","), ("%20", "+"), ("%5B", "["), ("%5D", "]")):
            text = text.replace(code, char)
        return text

    return "&".join(f"{name}={encode(value)}" for name, value in params.items())


def _access_line(path: str, query: str, formatter: logging.Formatter, status: int = 200) -> str:
    """What uvicorn's access logger writes for a request, built as
    ``httptools_impl`` and ``h11_impl`` build it, through the real filter."""
    install_log_redaction()
    scope = {"type": "http", "path": path, "query_string": query.encode("ascii")}
    log = logging.getLogger("uvicorn.access")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    saved = log.level, log.disabled
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.disabled = False
    try:
        log.info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:50123", "GET", get_path_with_query_string(scope), "1.1", status,
        )
    finally:
        log.removeHandler(handler)
        log.setLevel(saved[0])
        log.disabled = saved[1]
    return stream.getvalue()


FORMATTERS = {
    "uvicorn": lambda: AccessFormatter(LOGGING_CONFIG["formatters"]["access"]["fmt"], use_colors=False),
    "json": JsonFormatter,
}


def _length(value: str) -> str:
    return f"[{len(value)} characters]"


def assert_no_words(text: str) -> None:
    for word in FORBIDDEN:
        assert word.lower() not in text.lower(), f"{word!r} reached the access log:\n{text}"


@pytest.mark.parametrize("formatter", sorted(FORMATTERS))
@pytest.mark.parametrize("route", sorted(WORDS_ROUTES))
def test_each_words_route_is_written_by_length(route, formatter):
    _, path, params = WORDS_ROUTES[route]
    line = _access_line(path, axios_query(params), FORMATTERS[formatter]())

    assert_no_words(line)
    message = json.loads(line)["message"] if formatter == "json" else line
    assert f"GET {path}?" in message and " 200" in message
    for name, value in params.items():
        if name in WORDS_QUERY_NAMES:
            assert f"{name}={_length(value)}" in message, message
        else:
            assert f"{name}={axios_query({name: value}).partition('=')[2]}" in message, "the other parameters stay"


def test_the_check_sees_a_leak(monkeypatch):
    """The mutation: the filter without the words step, and the same record
    writes the words. So the test above can fail."""
    monkeypatch.setattr(log_redaction, "redact_query_words", lambda text: text)
    _, path, params = WORDS_ROUTES["search"]
    line = _access_line(path, axios_query(params), FORMATTERS["uvicorn"]())
    assert "Zanzibar+quokka+fermentation" in line


@pytest.mark.parametrize(
    "path, expected",
    [
        # Counted decoded: `+` is a space, `%26` an `&`, `%23` a `#`, and a
        # Devanagari letter one character however many bytes it took.
        ("/s?q=two+words&limit=5", "/s?q=[9 characters]&limit=5"),
        ("/s?q=a%26b%23c&limit=5", "/s?q=[5 characters]&limit=5"),
        ("/s?q=%E0%A4%85", "/s?q=[1 character]"),
        # The value runs to the next `&`, as Starlette reads it, so a raw
        # `;`, `#` or `?` inside it stays hidden with it.
        ("/s?q=a;b#c&keep=1", "/s?q=[5 characters]&keep=1"),
        ("/s?limit=5&q=what?search=x", "/s?limit=5&q=[13 characters]"),
        # A repeated parameter: each value by its own length.
        ("/s?q=a&q=bb&q=ccc", "/s?q=[1 character]&q=[2 characters]&q=[3 characters]"),
        # A name percent-encoded or in another case is the same name.
        ("/s?%71=secret&%73earch=words", "/s?%71=[6 characters]&%73earch=[5 characters]"),
        ("/s?Q=secret&SEARCH=words", "/s?Q=[6 characters]&SEARCH=[5 characters]"),
        # After a `;`, or inside another parameter's value, still found.
        ("/s?a=1;q=secret", "/s?a=1;q=[6 characters]"),
        ("/s?focus=topic%3Atariffs&depth=1", "/s?focus=[13 characters]&depth=1"),
        # Nothing to hide, and names that only start alike.
        ("/s?q=", "/s?q="),
        ("/s?q", "/s?q"),
        ("/s?qq=1&searching=2&search_text=3&myq=4", "/s?qq=1&searching=2&search_text=3&myq=4"),
        ("/api/v1/jobs?status=failed&limit=5", "/api/v1/jobs?status=failed&limit=5"),
        ("/api/v1/search", "/api/v1/search"),
        # A URL in a sentence ends at a space.
        ("asked for /s?q=secret then", "asked for /s?q=[6 characters] then"),
    ],
)
def test_a_value_is_counted_as_the_route_reads_it(path, expected):
    assert redact_query_words(path) == expected


def test_a_credential_and_the_words_in_one_line():
    """Both steps, in the order the filter takes them."""
    line = _access_line("/api/v1/search", "access_token=abc.def&q=Zanzibar+quokka&limit=5", FORMATTERS["uvicorn"]())
    assert "access_token=[redacted]&q=[15 characters]&limit=5" in line
    assert_no_words(line)


def test_the_real_server_writes_no_search_words(tmp_path):
    """``app.main:app`` under the real uvicorn CLI, its own logging config and
    access format, asked each words route as the frontend asks it. No token,
    so each answers 401 or 403; the access line is written whatever the status."""
    asked = {}
    with _uvicorn(tmp_path, _env(tmp_path), "app.main:app") as port:
        for route, (_, path, params) in WORDS_ROUTES.items():
            url = f"http://127.0.0.1:{port}{path}?{axios_query(params)}"
            asked[route] = httpx.get(url, trust_env=False, timeout=60).status_code
    log = _log_of(tmp_path)

    assert all(status in (401, 403) for status in asked.values()), asked
    assert_no_words(log)
    for route, (_, path, params) in WORDS_ROUTES.items():
        words = next(name for name in params if name in WORDS_QUERY_NAMES)
        line = re.search(rf'"GET {re.escape(path)}\?[^"]*" {asked[route]}', log)
        assert line, f"no access line for {route}:\n{log[-3000:]}"
        assert f"{words}={_length(params[words])}" in line[0], line[0]

"""T-4.11.4.5 and T-4.11.4.8: uvicorn's access log writes no user's words.

uvicorn writes each request's path and query string at INFO, and the
launchers send that to ``.uvicorn.out.log``. A search box sends what the user
typed (``GET /api/v1/search?q=...``), so the filter D-151 put on
``uvicorn.access`` writes the value of every parameter in
``WORDS_QUERY_NAMES`` by its length and leaves the rest of the line alone.
One route puts the user's words in its path, ``DELETE
/api/v1/echo/context/{kind}/{key}``, a fact's key, so the same filter matches
each path against the templates in ``WORDS_PATH_PARAMS`` and writes that
segment by its length.

- Every query parameter of every route is either a words parameter, by name,
  or kept, by route and name, with the reason it is not words. A new
  parameter in neither fails ``test_every_query_parameter_is_words_or_kept``.
- Every path parameter of every route, read from the route's template, is
  either words or kept, by route and name, with the reason. A new one in
  neither fails ``test_every_path_parameter_is_words_or_kept``, which
  ``test_the_path_guard_sees_a_new_parameter`` proves on a fixture app.
- Each route with a words parameter: a record built as uvicorn builds it
  (the path percent-decoded as uvicorn's protocols decode it, the scope's raw
  query string, ``get_path_with_query_string``, the access line's five
  arguments), through the real filter and uvicorn's own access formatter and
  the app's JSON one, shows the method, the path, the other parameters, the
  status and the value's length, and not the words.
- The real server: ``app.main:app`` under the real uvicorn CLI, asked each of
  those routes, writes none of the words to its log.

Mutation checks (each failed the named tests when this shipped):

- the filter calling ``redact_url_credentials`` alone
  (``test_each_words_route_is_written_by_length``,
  ``test_the_real_server_writes_no_users_words``, and in-suite as
  ``test_the_check_sees_a_leak``);
- the filter without ``redact_path_words``
  (``test_the_context_delete_line_writes_the_key_by_length``,
  ``test_the_real_server_writes_no_users_words``, and in-suite as
  ``test_the_check_sees_a_path_leak``);
- a words path value that stops at a ``/``, as a kept one does
  (``test_the_context_delete_line_writes_the_key_by_length[slash]``,
  ``test_a_path_is_matched_against_its_template``);
- ``unquote`` replaced by the raw value's length
  (``test_the_context_delete_line_writes_the_key_by_length``,
  ``test_a_path_is_matched_against_its_template``);
- the path guard reading the handler's arguments (``dependant.path_params``)
  in place of the template (``test_the_path_guard_sees_a_new_parameter``);
- ``key`` taken out of ``WORDS_PATH_PARAMS``
  (``test_every_path_parameter_is_words_or_kept`` and every path test);
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
from urllib.parse import quote, unquote

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter
from uvicorn.protocols.utils import get_path_with_query_string

from app.utils import log_redaction
from app.utils.json_logging import JsonFormatter
from app.utils.log_redaction import (
    WORDS_PATH_PARAMS,
    WORDS_QUERY_NAMES,
    install_log_redaction,
    redact_path_words,
    redact_query_words,
)
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

# Every path parameter that is not a user's words, by name with why, and the
# route templates that carry it. Read from every route's template on
# 2026-11-10. A template is listed under each name it carries, so a new route
# fails the guard until it is listed here, whatever its parameter is called.
_KEPT_PATH_BY_NAME: dict[str, tuple[str, tuple[str, ...]]] = {
    "provider": ("a provider's name, from the BYOK or the OAuth list", (
        "/api/v1/auth/credentials/{provider}",
        "/api/v1/auth/credentials/{provider}/verify",
        "/api/v1/auth/oauth/{provider}/callback",
        "/api/v1/auth/oauth/{provider}/start",
    )),
    "jti": ("a session's id, not its token", ("/api/v1/auth/sessions/{jti}",)),
    "use_case": ("a use case's name, from the registry", ("/api/v1/settings/llm/{use_case}",)),
    "name": ("a connector's name, from the registry", (
        "/api/v1/echo/connectors/{name}",
        "/api/v1/echo/connectors/{name}/authorize",
        "/api/v1/echo/connectors/{name}/callback",
        "/api/v1/echo/connectors/{name}/sync",
    )),
    "kind": ("a context kind, from echo_service.SUPPORTED_KINDS", ("/api/v1/echo/context/{kind}/{key}",)),
    "source": ("manual, a connector's name or import:<id>, never typed", ("/api/v1/echo/sources/{source}",)),
    "digest": ("a PDF's SHA-256", ("/api/v1/library/pdf/{digest}.pdf",)),
    "channel_id": ("a YouTube channel's id", (
        "/api/v1/channels/{channel_id}",
        "/api/v1/channels/{channel_id}/intelligence",
        "/api/v1/channels/{channel_id}/subscribe",
        "/api/v1/channels/{channel_id}/sync",
        "/api/v1/channels/{channel_id}/unsubscribe",
        "/api/v1/channels/{channel_id}/weight",
    )),
    "video_id": ("a document's id or a YouTube video's", (
        "/api/v1/videos/{video_id}/extract-frames",
        "/api/v1/videos/{video_id}/extract-knowledge",
        "/api/v1/videos/{video_id}/frames",
        "/api/v1/videos/{video_id}/frames/{frame_id}/image",
        "/api/v1/videos/{video_id}/knowledge",
    )),
    "document_id": ("id", ("/api/v1/library/videos/{document_id}/tags/{tag_id}",)),
    "frame_id": ("id", ("/api/v1/videos/{video_id}/frames/{frame_id}/image",)),
    "job_id": ("id", (
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/approve",
        "/api/v1/jobs/{job_id}/cancel",
        "/api/v1/jobs/{job_id}/qa",
        "/api/v1/jobs/{job_id}/qa/clarify",
        "/api/v1/jobs/{job_id}/qa/stream",
        "/api/v1/jobs/{job_id}/report",
        "/api/v1/jobs/{job_id}/report.md",
        "/api/v1/jobs/{job_id}/report/body",
        "/api/v1/jobs/{job_id}/save-as-template",
        "/api/v1/jobs/{job_id}/videos",
        "/api/v1/shelves/{shelf_id}/jobs/{job_id}",
    )),
    "template_id": ("id", ("/api/v1/job-templates/{template_id}", "/api/v1/job-templates/{template_id}/versions")),
    "shelf_id": ("id", (
        "/api/v1/shelves/{shelf_id}",
        "/api/v1/shelves/{shelf_id}/documents",
        "/api/v1/shelves/{shelf_id}/jobs/{job_id}",
        "/api/v1/shelves/{shelf_id}/qa",
    )),
    "tag_id": ("id", ("/api/v1/tags/{tag_id}", "/api/v1/library/videos/{document_id}/tags/{tag_id}")),
    "exchange_id": ("id", ("/api/v1/library/qa/{exchange_id}",)),
    "note_id": ("id", ("/api/v1/notes/{note_id}",)),
    "notification_id": ("id", ("/api/v1/notifications/{notification_id}",)),
    "saved_search_id": ("id", (
        "/api/v1/saved-searches/{saved_search_id}",
        "/api/v1/saved-searches/{saved_search_id}/run-now",
        "/api/v1/saved-searches/{saved_search_id}/runs",
    )),
    "output_id": ("id", (
        "/api/v1/author/outputs/{output_id}",
        "/api/v1/author/outputs/{output_id}/cancel",
        "/api/v1/author/outputs/{output_id}/citations",
        "/api/v1/author/outputs/{output_id}/content",
        "/api/v1/author/outputs/{output_id}/download",
    )),
    "draft_id": ("id", ("/api/v1/echo/drafts/{draft_id}", "/api/v1/echo/drafts/{draft_id}/feedback")),
    "tombstone_id": ("id", ("/api/v1/echo/fact-tombstones/{tombstone_id}",)),
    "import_id": ("id", ("/api/v1/echo/imports/{import_id}", "/api/v1/echo/imports/{import_id}/embed")),
    "token_id": ("a share token row's id, not the token", ("/api/v1/echo/share-tokens/{token_id}",)),
    "share_id": ("id", (
        "/api/v1/echo/shares/{share_id}",
        "/api/v1/echo/shares/{share_id}/file",
        "/api/v1/echo/shares/{share_id}/library",
        "/api/v1/echo/shares/{share_id}/process",
    )),
    "signal_id": ("id", ("/api/v1/echo/signals/{signal_id}", "/api/v1/echo/signals/{signal_id}/restore")),
    "test_id": ("id", (
        "/api/v1/echo/voice-test/{test_id}",
        "/api/v1/echo/voice-test/{test_id}/picks",
        "/api/v1/echo/voice-test/{test_id}/score",
    )),
}

KEPT_PATH: dict[str, dict[str, str]] = {}
for _name, (_reason, _templates) in _KEPT_PATH_BY_NAME.items():
    for _template in _templates:
        KEPT_PATH.setdefault(_template, {})[_name] = _reason

# Each route a words path parameter reaches, with the kind its page sends.
WORDS_PATH_ROUTES = {"/api/v1/echo/context/{kind}/{key}": "interest"}

_PATH_PARAM = re.compile(r"\{(\w+)(?::\w+)?\}")


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


def _path_params(application=None) -> dict[str, set[str]]:
    """Every path parameter of every route, by full template. Read from the
    template, not the handler's arguments: a segment the handler never names
    is still in the URL, and still in the log."""
    found: dict[str, set[str]] = {}
    for path, _route, _dependant in _served_routes(application):
        names = set(_PATH_PARAM.findall(path))
        if names:
            found.setdefault(path, set()).update(names)
    return found


def _unsorted_path_params(params: dict[str, set[str]]) -> list[str]:
    return sorted(
        f"{path} {{{name}}}" for path, names in params.items() for name in names
        if name not in WORDS_PATH_PARAMS.get(path, ()) and name not in KEPT_PATH.get(path, {})
    )


def test_every_path_parameter_is_words_or_kept():
    """A path parameter is written by its length on its route, or kept on it
    for a reason. One in neither list is a decision nobody has made yet."""
    params = _path_params()
    assert len(params) > 60, "the walk found too few templates, so too little was checked"
    unsorted = _unsorted_path_params(params)
    assert not unsorted, (
        "Path parameters in neither list: add each to log_redaction.WORDS_PATH_PARAMS under its route's "
        f"template if a user can write its value, else to _KEPT_PATH_BY_NAME here with the reason: {unsorted}"
    )
    words = {(path, name) for path, names in WORDS_PATH_PARAMS.items() for name in names}
    kept = {(path, name) for path, names in KEPT_PATH.items() for name in names}
    stale = sorted(f"{path} {{{name}}}" for path, name in words | kept if name not in params.get(path, set()))
    assert not stale, f"Listed path parameters no route has any more: {stale}"
    assert not words & kept, f"Path parameters in both lists: {sorted(words & kept)}"


def test_the_path_guard_sees_a_new_parameter():
    """The guard's proof, on an app of its own: a route already listed passes,
    and a new path parameter fails it, a segment the handler never names
    included."""
    router = APIRouter()

    @router.get("/jobs/{job_id}")
    def listed(job_id: str):
        return job_id

    @router.delete("/fixture/{label}")
    def new(label: str):
        return label

    @router.get("/fixture/{unnamed}/file")
    def unnamed():
        return None

    fixture = FastAPI()
    fixture.include_router(router, prefix="/api/v1")

    assert _unsorted_path_params(_path_params(fixture)) == [
        "/api/v1/fixture/{label} {label}", "/api/v1/fixture/{unnamed}/file {unnamed}",
    ]


def test_every_words_path_parameter_is_checked_on_its_route():
    assert set(WORDS_PATH_ROUTES) == set(WORDS_PATH_PARAMS)


def axios_query(params: dict[str, str]) -> str:
    """A query string as the frontend's axios writes one: encodeURIComponent,
    then a space as ``+`` and ``:``, ``$``, ``,``, ``[``, ``]`` left as they are."""
    def encode(value: str) -> str:
        text = quote(value, safe="-_.!~*'()")
        for code, char in (("%3A", ":"), ("%24", "$"), ("%2C", ","), ("%20", "+"), ("%5B", "["), ("%5D", "]")):
            text = text.replace(code, char)
        return text

    return "&".join(f"{name}={encode(value)}" for name, value in params.items())


def _access_line(path: str, query: str, formatter: logging.Formatter, status: int = 200, method: str = "GET") -> str:
    """What uvicorn's access logger writes for a request, built as
    ``httptools_impl`` and ``h11_impl`` build it, through the real filter:
    the path as sent, percent-decoded into the scope, the query as sent."""
    install_log_redaction()
    scope = {"type": "http", "path": unquote(path), "query_string": query.encode("ascii")}
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
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:50123", method, get_path_with_query_string(scope), "1.1", status,
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


def encode_uri_component(value: str) -> str:
    """A path segment as the frontend writes one (``echoApi.deleteContext``)."""
    return quote(value, safe="-_.!~*'()")


# Fact keys as a user may write them. A `/` decodes before the route matches,
# so that key's path has a segment too many and answers 404; it is the user's
# words all the same.
KEYS = {
    "words": "Favourite Zanzibar quokka",
    "hindi": HINDI,
    "slash": "quokka/fermentation",
    "query-marks": "tariffs? quokka #2",
    "percent": "100% quokka",
    "plus": "quokka+tariffs",
}


@pytest.mark.parametrize("formatter", sorted(FORMATTERS))
@pytest.mark.parametrize("key", sorted(KEYS))
def test_the_context_delete_line_writes_the_key_by_length(key, formatter):
    [(template, kind)] = WORDS_PATH_ROUTES.items()
    path = template.replace("{kind}", kind).replace("{key}", encode_uri_component(KEYS[key]))
    status = 404 if key == "slash" else 200
    line = _access_line(path, "", FORMATTERS[formatter](), status=status, method="DELETE")

    assert_no_words(line)
    message = json.loads(line)["message"] if formatter == "json" else line
    expected = f'"DELETE /api/v1/echo/context/{kind}/{_length(KEYS[key])} HTTP/1.1" {status}'
    assert expected in message, message


def test_the_context_delete_line_keeps_its_query_rules():
    """A query on that path still goes by the query's rules: words by length,
    a credential redacted, anything else as it came."""
    line = _access_line(
        "/api/v1/echo/context/interest/Zanzibar%20quokka", "q=tariffs&access_token=abc.def&limit=5",
        FORMATTERS["uvicorn"](), method="DELETE",
    )
    assert_no_words(line)
    assert "/api/v1/echo/context/interest/[15 characters]?q=[7 characters]&access_token=[redacted]&limit=5" in line


def test_the_check_sees_a_path_leak(monkeypatch):
    """The mutation: the filter without the path step, and the same record
    writes the key. So the test above can fail."""
    monkeypatch.setattr(log_redaction, "redact_path_words", lambda text: text)
    line = _access_line(
        f"/api/v1/echo/context/interest/{encode_uri_component(KEYS['words'])}", "", FORMATTERS["uvicorn"](),
        method="DELETE",
    )
    assert "Favourite%20Zanzibar%20quokka" in line


@pytest.mark.parametrize(
    "path, expected",
    [
        # Counted decoded, where `+` is a `+` in a path; `%25` is one `%`.
        ("/api/v1/echo/context/interest/two%20words", "/api/v1/echo/context/interest/[9 characters]"),
        ("/api/v1/echo/context/interest/a+b", "/api/v1/echo/context/interest/[3 characters]"),
        ("/api/v1/echo/context/interest/100%25", "/api/v1/echo/context/interest/[4 characters]"),
        ("/api/v1/echo/context/interest/%E0%A4%85", "/api/v1/echo/context/interest/[1 character]"),
        # A decoded `/` makes another segment, which the key still owns; a
        # decoded `?` or `#` is written encoded, inside it.
        ("/api/v1/echo/context/interest/a/b/c", "/api/v1/echo/context/interest/[5 characters]"),
        ("/api/v1/echo/context/interest/a%3Fb%23c", "/api/v1/echo/context/interest/[5 characters]"),
        # The query starts at the first raw `?`; a trailing `/` stands.
        ("/api/v1/echo/context/interest/k?limit=5", "/api/v1/echo/context/interest/[1 character]?limit=5"),
        ("/api/v1/echo/context/interest/k/", "/api/v1/echo/context/interest/[1 character]/"),
        # In any case, percent-encoded, behind a host or a root path, or in a
        # sentence: a crafted URL hides more, never less.
        ("/API/V1/Echo/Context/interest/secret", "/API/V1/Echo/Context/interest/[6 characters]"),
        ("/api%2Fv1%2fecho/context/interest/secret", "/api%2Fv1%2fecho/context/interest/[6 characters]"),
        ("http://h:8000/api/v1/echo/context/interest/secret", "http://h:8000/api/v1/echo/context/interest/[6 characters]"),
        ("/root/api/v1/echo/context/interest/secret", "/root/api/v1/echo/context/interest/[6 characters]"),
        ('"DELETE /api/v1/echo/context/interest/secret HTTP/1.1" 401',
         '"DELETE /api/v1/echo/context/interest/[6 characters] HTTP/1.1" 401'),
        # Nothing to hide: no key, or another route's parameters.
        ("/api/v1/echo/context/interest/", "/api/v1/echo/context/interest/"),
        ("/api/v1/echo/context/interest", "/api/v1/echo/context/interest"),
        ("/api/v1/echo/context?kind=interest", "/api/v1/echo/context?kind=interest"),
        ("/api/v1/echo/sources/manual", "/api/v1/echo/sources/manual"),
        ("/api/v1/echo/connectors/spotify/sync", "/api/v1/echo/connectors/spotify/sync"),
        # A path no route serves is written whole.
        ("/api/v1/echo/contexts/interest/secret", "/api/v1/echo/contexts/interest/secret"),
        ("/api/v1/nowhere/secret", "/api/v1/nowhere/secret"),
    ],
)
def test_a_path_is_matched_against_its_template(path, expected):
    assert redact_path_words(path) == expected


def test_the_real_server_writes_no_users_words(tmp_path):
    """``app.main:app`` under the real uvicorn CLI, its own logging config and
    access format, asked each words route as the frontend asks it. No token,
    so each answers 401 or 403, the key holding a `/` 404; the access line is
    written whatever the status."""
    asked, deleted = {}, {}
    [(template, kind)] = WORDS_PATH_ROUTES.items()
    with _uvicorn(tmp_path, _env(tmp_path), "app.main:app") as port:
        for route, (_, path, params) in WORDS_ROUTES.items():
            url = f"http://127.0.0.1:{port}{path}?{axios_query(params)}"
            asked[route] = httpx.get(url, trust_env=False, timeout=60).status_code
        for key, value in KEYS.items():
            path = template.replace("{kind}", kind).replace("{key}", encode_uri_component(value))
            deleted[key] = httpx.delete(f"http://127.0.0.1:{port}{path}", trust_env=False, timeout=60).status_code
    log = _log_of(tmp_path)

    assert all(status in (401, 403) for status in asked.values()), asked
    assert deleted == {key: 404 if key == "slash" else 401 for key in KEYS}, deleted
    assert_no_words(log)
    for route, (_, path, params) in WORDS_ROUTES.items():
        words = next(name for name in params if name in WORDS_QUERY_NAMES)
        line = re.search(rf'"GET {re.escape(path)}\?[^"]*" {asked[route]}', log)
        assert line, f"no access line for {route}:\n{log[-3000:]}"
        assert f"{words}={_length(params[words])}" in line[0], line[0]
    for key, value in KEYS.items():
        line = f'"DELETE /api/v1/echo/context/{kind}/{_length(value)} HTTP/1.1" {deleted[key]}'
        assert line in log, f"no access line for {key}:\n{log[-3000:]}"

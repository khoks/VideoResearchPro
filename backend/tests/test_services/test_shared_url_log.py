"""T-3.7.2.9: a shared link's path and query stay out of the logs.

The extractor's own lines are checked on a patched logger, every branch. Two
lines are not the extractor's: httpx writes one per request, which a Celery
worker logs, and trafilatura writes its own at ERROR. Those are checked for
real, on a local server, with a handler on the library's logger.

Mutation checks (each failed the named test when this shipped): putting ``url``
back on the bad-status line (its branch's test, and
``test_no_log_call_on_this_path_takes_the_url_itself``); logging ``e`` instead
of its type (``test_a_failed_fetch_names_the_host_only``, and
``test_a_playwright_failure_names_the_host_only`` on the timeout line);
dropping ``@shared_url_fetch()`` from ``_get``
(``test_the_library_request_line_stays_out_of_a_workers_log``) or
``fetch_image`` (``test_a_shared_image_fetch_is_quiet_too``); dropping the
trafilatura ``setLevel`` (``test_trafilaturas_own_lines_stay_out``); a filter
that drops httpx's line for everyone
(``test_every_other_httpx_request_keeps_its_line``).
"""
from __future__ import annotations

import ast
import http.server
import logging
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.services import echo_media
from app.services.article_extraction import extractor
from app.services.article_extraction.extractor import extract_text
from app.sources.article import connector as article_connector
from app.utils.shared_url_log import host_of, shared_url_fetch

HOST = "news.example.com"
SECRET = "reset-token-abc"
PRIVATE_PATH = "patient-records"
URL = f"https://user:hunter2@{HOST}/{PRIVATE_PATH}/42?token={SECRET}#frag"

ARTICLE = "<html><body><article><h1>Title</h1>" + "<p>" + "A plain sentence of words. " * 80 + "</p></article></body></html>"
SHORT = "<html><body><article><p>" + "Word " * 50 + "</p></article></body></html>"
TINY = "<html><body><article><p>Three words here.</p></article></body></html>"


def _rendered(log: MagicMock) -> str:
    """Every call on a patched logger, as the line it would have written."""
    lines = []
    for method in ("debug", "info", "warning", "error", "exception"):
        for call in getattr(log, method).call_args_list:
            message, *args = call.args
            lines.append(message % tuple(args) if args else message)
    return "\n".join(lines)


def _assert_host_only(log: MagicMock) -> None:
    text = _rendered(log)
    assert HOST in text, f"the line should still say which site: {text!r}"
    for private in (SECRET, PRIVATE_PATH, "hunter2", "frag", "token="):
        assert private not in text, text


@pytest.fixture
def log():
    with patch.object(extractor, "logger") as patched:
        yield patched


def _page(html: str | None = None, status: int = 200):
    return patch.object(extractor.httpx, "get", return_value=httpx.Response(status, text=html or ""))


def test_a_failed_fetch_names_the_host_only(log):
    """httpx's message can quote the URL, so the type is logged, not the text."""
    failure = httpx.ConnectError(f"could not reach {URL}")
    with patch.object(extractor.httpx, "get", side_effect=failure):
        assert extract_text(URL) is None
    _assert_host_only(log)
    assert "ConnectError" in _rendered(log)


def test_a_bad_status_names_the_host_only(log):
    with _page(status=404):
        assert extract_text(URL) is None
    _assert_host_only(log)
    assert "404" in _rendered(log)


def test_trafilatura_raising_names_the_host_only(log):
    with _page(ARTICLE), patch.object(extractor.trafilatura, "extract", side_effect=RuntimeError(f"bad {URL}")):
        assert extract_text(URL) is None
    _assert_host_only(log)
    assert "RuntimeError" in _rendered(log)


def test_a_non_json_answer_from_trafilatura_names_the_host_only(log):
    with _page(ARTICLE), patch.object(extractor.trafilatura, "extract", return_value="not json"):
        assert extract_text(URL) is None
    _assert_host_only(log)


def test_a_short_page_kept_as_best_effort_names_the_host_only(log):
    with _page(SHORT):
        assert extract_text(URL) is not None
    _assert_host_only(log)


def test_a_page_under_the_floor_names_the_host_only(log):
    with _page(TINY):
        assert extract_text(URL) is None
    _assert_host_only(log)


def test_the_playwright_fallback_turned_off_names_the_host_only(log, monkeypatch):
    monkeypatch.setattr(settings, "ARTICLE_PLAYWRIGHT_ENABLED", False)
    assert extractor._playwright_fallback(URL) is None
    _assert_host_only(log)


def test_playwright_not_installed_names_the_host_only(log, monkeypatch):
    monkeypatch.setattr(settings, "ARTICLE_PLAYWRIGHT_ENABLED", True)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    assert extractor._playwright_fallback(URL) is None
    _assert_host_only(log)


class _PlaywrightError(Exception):
    pass


class _PlaywrightTimeout(_PlaywrightError):
    pass


def _playwright_raising(monkeypatch, error: Exception) -> None:
    """Playwright's messages carry a call log: ``navigating to "<url>"``."""

    def sync_playwright():
        raise error

    module = types.SimpleNamespace(
        Error=_PlaywrightError, TimeoutError=_PlaywrightTimeout, sync_playwright=sync_playwright
    )
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr(settings, "ARTICLE_PLAYWRIGHT_ENABLED", True)


@pytest.mark.parametrize(
    "error",
    [
        _PlaywrightTimeout(f'Timeout 30000ms exceeded. navigating to "{URL}"'),
        _PlaywrightError(f'net::ERR_ABORTED at {URL}'),
        OSError(f"subprocess died on {URL}"),
    ],
)
def test_a_playwright_failure_names_the_host_only(log, monkeypatch, error):
    _playwright_raising(monkeypatch, error)
    assert extractor._playwright_fallback(URL) is None
    _assert_host_only(log)
    assert type(error).__name__ in _rendered(log)


@pytest.mark.parametrize("value", ["", None, 42])
def test_no_url_at_all_logs_no_value(log, value):
    assert extract_text(value) is None
    log.warning.assert_called_once()
    assert repr(value) not in _rendered(log) or value is None


def test_a_failed_feed_fetch_names_the_host_only():
    """A feed address is often the private one, with the token in it, and
    ``raise_for_status`` quotes it whole."""
    client = MagicMock()
    client.fetch_feed.side_effect = httpx.HTTPStatusError(f"404 for url {URL}", request=MagicMock(), response=MagicMock())
    with (
        patch.object(article_connector, "logger") as log,
        patch.object(article_connector.article_client, "get_client", return_value=client),
    ):
        assert list(article_connector.ArticleConnector().list_creator_items(URL)) == []
    _assert_host_only(log)


@pytest.mark.parametrize(
    "path",
    ["app/services/article_extraction/extractor.py", "app/sources/article/connector.py"],
)
def test_no_log_call_on_this_path_takes_the_url_itself(path):
    """A line added later should have to go through ``host_of``."""
    tree = ast.parse((Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            names = {arg.id for arg in node.args if isinstance(arg, ast.Name)}
            assert not names & {"url", "creator_external_id"}, ast.unparse(node)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://news.example.com/a?b=c", "news.example.com"),
        ("https://user:pw@news.example.com:8443/a", "news.example.com"),
        ("https://[2001:db8::1]:8443/a", "2001:db8::1"),
        ("not a url", "an unreadable address"),
        ("http://[broken/a", "an unreadable address"),
        ("", "an unreadable address"),
        (None, "an unreadable address"),
        (42, "an unreadable address"),
    ],
)
def test_host_of(url, expected):
    assert host_of(url) == expected


# ---------------------------------------------------------------------------
# What the libraries log for themselves
# ---------------------------------------------------------------------------


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def httpx_lines():
    """httpx's logger at INFO, as it runs in a Celery worker."""
    log = logging.getLogger("httpx")
    handler = _Lines()
    level = log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    yield handler.lines
    log.removeHandler(handler)
    log.setLevel(level)


class _Site(http.server.BaseHTTPRequestHandler):
    body = ARTICLE.encode()
    content_type = "text/html"

    def do_GET(self):
        if self.path.startswith("/moved"):
            self.send_response(302)
            self.send_header("Location", f"/{PRIVATE_PATH}?token={SECRET}")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_every_other_httpx_request_keeps_its_line(httpx_lines, site):
    """The harness sees the line, and only a shared link's fetch loses it."""
    httpx.get(f"{site}/plain?token={SECRET}")
    assert len(httpx_lines) == 1 and SECRET in httpx_lines[0]


def test_the_library_request_line_stays_out_of_a_workers_log(httpx_lines, site):
    assert extract_text(f"{site}/{PRIVATE_PATH}?token={SECRET}") is not None
    assert httpx_lines == []


def test_a_redirect_followed_for_a_share_is_quiet_too(httpx_lines, site):
    assert extract_text(f"{site}/moved", guard=lambda url: None) is not None
    assert httpx_lines == []


def test_the_line_comes_back_after_the_fetch(httpx_lines, site):
    extract_text(f"{site}/{PRIVATE_PATH}")
    httpx.get(f"{site}/after")
    assert len(httpx_lines) == 1


def test_a_failed_fetch_still_lets_the_line_come_back(httpx_lines, site):
    with pytest.raises(RuntimeError):
        with shared_url_fetch():
            raise RuntimeError("the fetch failed")
    httpx.get(f"{site}/after")
    assert len(httpx_lines) == 1


def test_a_shared_image_fetch_is_quiet_too(httpx_lines, site, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_FETCH_ALLOW_PRIVATE", True)
    monkeypatch.setattr(_Site, "body", b"\x89PNG fake")
    monkeypatch.setattr(_Site, "content_type", "image/png")
    path, ctype = echo_media.fetch_image(f"{site}/{PRIVATE_PATH}.png?token={SECRET}", tmp_path, "share")
    assert ctype == "image/png" and path.exists()
    assert httpx_lines == []


def test_trafilaturas_own_lines_stay_out(site, monkeypatch):
    """It logs "empty HTML tree: <url>" and "discarding data: <url>" at ERROR
    and WARNING, on loggers under ``trafilatura``, which no text format or
    worker level keeps out."""
    monkeypatch.setattr(_Site, "body", b"<html></html>")
    log = logging.getLogger("trafilatura")
    handler = _Lines()
    log.addHandler(handler)
    try:
        extract_text(f"{site}/{PRIVATE_PATH}?token={SECRET}")
    finally:
        log.removeHandler(handler)
    assert handler.lines == []


def test_the_extractor_still_passes_trafilatura_the_whole_url():
    """Host-only is for logs. trafilatura reads a publication date out of the
    path, so the extraction itself keeps the address."""
    with _page(ARTICLE), patch.object(extractor.trafilatura, "extract", return_value=None) as extract:
        extract_text(URL)
    assert extract.call_args.kwargs["url"] == URL

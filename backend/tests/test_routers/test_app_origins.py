"""T-4.11.3.3 — CORS and OAuth start read one list of origins.

Both at their production callers: a preflight through the app's own
middleware, and ``GET /auth/oauth/{provider}/start``. Each origin is put to
both, and they must give the same answer.

Mutation checks (each failed the named test when this shipped): going back to
the hard-coded CORS list in ``app/main.py`` (``test_cors_and_sign_in_give_one_answer``
and ``test_localhost_3000_is_not_a_default``; the dev-install test keeps
passing, as it should); dropping the wildcard refusal
(``test_a_wildcard_is_refused_and_said_so``); dropping the cache, so a bad
entry is logged on every request (``test_a_bad_entry_is_logged_once``);
passing ``allow_origins=["*"]`` to Starlette, which then echoes any origin on
a request that is not a preflight (both of the first two).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.utils import app_origins

DEFAULT = type(settings).model_fields["APP_BASE_URL"].default
CALLBACK = "/login/oauth/google/callback"


@pytest.fixture(autouse=True)
def _google_configured(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(settings, "APP_BASE_URL", DEFAULT)
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "")


@pytest.fixture
def fresh_parse():
    """The parse is cached by value; a test that counts warnings starts and
    ends with an empty cache."""
    app_origins._parse.cache_clear()
    yield
    app_origins._parse.cache_clear()


def _cors_allows(client, origin: str) -> bool:
    """The preflight's answer, which the request that follows must agree with."""
    r = client.options(
        "/api/v1/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    allowed = r.headers.get("access-control-allow-origin") == origin
    assert allowed == (r.status_code == 200), (origin, r.status_code, r.text)
    if allowed:
        assert r.headers["access-control-allow-credentials"] == "true"
        assert "Origin" in r.headers["vary"]
    simple = client.get("/api/v1/health", headers={"Origin": origin})
    assert simple.status_code == 200
    assert simple.headers.get("access-control-allow-origin") == (origin if allowed else None), origin
    return allowed


def _sign_in_allows(client, origin: str) -> bool:
    r = client.get("/api/v1/auth/oauth/google/start", params={"redirect_uri": origin + CALLBACK})
    assert r.status_code in (200, 400), (origin, r.status_code, r.text)
    return r.status_code == 200


def test_a_dev_install_keeps_working_untouched(unauthenticated_client, db):
    """No setting at all: APP_BASE_URL's default is where Vite serves."""
    assert DEFAULT == "http://localhost:5173"
    assert _cors_allows(unauthenticated_client, DEFAULT)
    assert _sign_in_allows(unauthenticated_client, DEFAULT)


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:5173", "https://evil.example"])
def test_localhost_3000_is_not_a_default(unauthenticated_client, db, origin):
    """:3000 was in the hard-coded list, and nothing served the app there."""
    assert not _cors_allows(unauthenticated_client, origin)
    assert not _sign_in_allows(unauthenticated_client, origin)


@pytest.mark.parametrize(
    "origin, allowed",
    [
        ("https://research.example.org", True),  # APP_BASE_URL, path and all
        ("http://192.168.1.20:5173", True),
        ("http://[::1]:5173", True),
        ("http://localhost:5173", False),  # the default no longer applies
        ("http://localhost:3000", False),
        ("http://research.example.org", False),  # another scheme
        ("https://research.example.org:8443", False),  # another port
        ("https://www.example.org", False),  # the wildcard entry was refused
        ("https://evil.example", False),
        ("null", False),  # a sandboxed frame or a file: page
    ],
)
def test_cors_and_sign_in_give_one_answer(unauthenticated_client, db, monkeypatch, origin, allowed):
    """An install opened elsewhere sets the two settings and nothing else."""
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://research.example.org/app/")
    monkeypatch.setattr(
        settings,
        "OAUTH_ALLOWED_REDIRECT_ORIGINS",
        " http://192.168.1.20:5173 ,http://[::1]:5173, https://*.example.org, *, not a url,",
    )
    assert _cors_allows(unauthenticated_client, origin) is allowed
    assert _sign_in_allows(unauthenticated_client, origin) is allowed


def test_a_wildcard_is_refused_and_said_so(unauthenticated_client, db, monkeypatch, fresh_parse):
    logger = MagicMock()
    monkeypatch.setattr(app_origins, "logger", logger)
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "https://*.example.org,*")

    assert app_origins.allowed() == {("http", "localhost", 5173)}
    warned = [call.args[1] for call in logger.warning.call_args_list]
    assert warned == ["https://*.example.org", "*"]
    assert all("wildcard" in call.args[0] for call in logger.warning.call_args_list)

    # A redirect spelt with the wildcard itself matches nothing either.
    assert not _sign_in_allows(unauthenticated_client, "https://*.example.org")
    assert not _cors_allows(unauthenticated_client, "https://www.example.org")


def test_a_bad_entry_is_logged_once(unauthenticated_client, db, monkeypatch, fresh_parse):
    """CORS asks on every request that carries an Origin."""
    logger = MagicMock()
    monkeypatch.setattr(app_origins, "logger", logger)
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "localhost:5174")

    for _ in range(3):
        assert _cors_allows(unauthenticated_client, DEFAULT)
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[1] == "localhost:5174"


def test_the_startup_line_names_the_list(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://research.example.org/app/")
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_REDIRECT_ORIGINS", "http://[::1]:5173,HTTP://LAN.example:80")
    assert app_origins.describe() == "http://[::1]:5173, http://lan.example, https://research.example.org"


def test_an_empty_list_says_so(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "")
    assert app_origins.describe() == "(none)"

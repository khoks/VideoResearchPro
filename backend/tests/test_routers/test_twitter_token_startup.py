"""T-1.5.9.1: the API says at startup whether ``TWITTER_BEARER_TOKEN`` is set.

At the caller, the app's lifespan, with the logger patched (caplog depends on
global logging state and on test order). Presence only: the token, or any
part of it, never reaches the log. Nothing calls X: whether the token is
valid takes a billed request, which stays the owner's (D-009, D-139).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.sources.twitter import client as twitter_client

# Invented, shaped like a bearer token, distinctive enough to find.
FAKE_TOKEN = "AAAAAAAAAAAAAAAAAAAAAFakeForTestOnly0000zzQ9xK"


def _token_lines(log) -> list[str]:
    lines = []
    for call in log.method_calls:
        text = " ".join(str(a) for a in call.args) + " " + " ".join(str(v) for v in call.kwargs.values())
        lines.append(text)
    return [line for line in lines if "TWITTER_BEARER_TOKEN" in line]


def _never_calls_x(*args, **kwargs):
    pytest.fail("startup must not call the X API")


def test_startup_says_once_that_the_token_is_set_and_never_what_it_is(monkeypatch):
    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(twitter_client.httpx, "get", _never_calls_x)
    with patch.object(twitter_client, "logger") as log:
        with TestClient(app):
            pass

    lines = _token_lines(log)
    assert len(lines) == 1, lines
    assert "is set" in lines[0] and "search is on" in lines[0]
    assert "paid call" in lines[0], "says the token was not checked against X"
    every_line = " ".join(str(c) for c in log.method_calls)
    for fragment in (FAKE_TOKEN, FAKE_TOKEN[:8], FAKE_TOKEN[-8:], "FakeForTest"):
        assert fragment not in every_line


def test_startup_says_once_that_the_token_is_not_set(monkeypatch):
    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "")
    monkeypatch.setattr(twitter_client.httpx, "get", _never_calls_x)
    with patch.object(twitter_client, "logger") as log:
        with TestClient(app):
            pass

    lines = _token_lines(log)
    assert len(lines) == 1, lines
    assert "not set" in lines[0] and "pasted URL only" in lines[0]


def test_the_line_agrees_with_health(monkeypatch, client):
    """The same test as ``/health``'s ``twitter_search_enabled``."""
    for token, enabled in ((FAKE_TOKEN, True), ("", False)):
        monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", token)
        with patch.object(twitter_client, "logger") as log:
            twitter_client.log_token_presence()
        said_on = "is set" in log.info.call_args.args[0]
        assert said_on is enabled
        assert client.get("/api/v1/health").json()["capabilities"]["twitter_search_enabled"] is enabled

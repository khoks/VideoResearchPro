"""Exceptions that quote a key, in every shape ``provider_error_text`` knows.

T-5.6.17: the record factory of D-151 scrubs log lines, but a failed run's
``error_message``, the socket's error event, a saved search's ``last_error``
and the like are not log records. The tests that hold each of those places to
``error_summary`` raise these at the production caller and read back what was
stored or published. Each case says which secret must not appear, which class
names the failure, and which words must survive, so a fix that throws the
whole message away fails as well. Nothing here reaches a provider.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import anthropic
import httpx
import openai
import pytest
from google.api_core.exceptions import PermissionDenied
from googleapiclient.errors import HttpError
from httplib2 import Response

# A refused key as OpenAI stars it out, and one in no shape `scrub_keys` knows.
FRAGMENT = "sk-proj-abc***************wxyz"
SHAPELESS = "tenant-secret-42"
ANTHROPIC_KEY = "sk-ant-api03-abc_def-ghi"
GOOGLE_KEY = "AIzaSyD-0123456789abcdefghijklmnopqrstu"
URL_KEY = "short-secret-9"


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://provider.example/v1/chat"))


def _openai_401(key: str) -> openai.AuthenticationError:
    message = f"Error code: 401 - {{'error': {{'message': 'Incorrect API key provided: {key}. You can find'}}}}"
    return openai.AuthenticationError(message, response=_response(401), body=None)


def _youtube_403() -> HttpError:
    uri = f"https://youtube.googleapis.com/youtube/v3/search?part=snippet&key={GOOGLE_KEY}&alt=json"
    return HttpError(Response({"status": 403, "reason": "Forbidden"}), b'{"error": {"message": "quota spent"}}', uri=uri)


def _caused_by_a_refusal() -> RuntimeError:
    try:
        try:
            raise _openai_401(SHAPELESS)
        except openai.AuthenticationError as e:
            raise RuntimeError(f"the call failed: {e}") from e
    except RuntimeError as wrapped:
        return wrapped


@dataclass(frozen=True)
class KeyBearing:
    make: Callable[[], BaseException]
    secret: str
    # The class the stored text names, and words it keeps. A refusal keeps
    # none: its words can quote a key in any shape.
    name: str
    kept: str | None


# Nothing here reads as transient to a retry loop ("timed out", "503"), so a
# failure is final at once and no test waits on a backoff.
CASES = [
    pytest.param(KeyBearing(lambda: _openai_401(FRAGMENT), "sk-proj-abc", "AuthenticationError", None), id="openai-401"),
    pytest.param(
        KeyBearing(
            lambda: openai.PermissionDeniedError(f"no: {SHAPELESS}", response=_response(403), body=None),
            SHAPELESS, "PermissionDeniedError", None,
        ),
        id="openai-403",
    ),
    pytest.param(
        KeyBearing(
            lambda: anthropic.AuthenticationError(f"no: {SHAPELESS}", response=_response(401), body=None),
            SHAPELESS, "AuthenticationError", None,
        ),
        id="anthropic-401",
    ),
    pytest.param(KeyBearing(lambda: PermissionDenied(f"no: {SHAPELESS}"), SHAPELESS, "PermissionDenied", None), id="google-403"),
    pytest.param(KeyBearing(_caused_by_a_refusal, SHAPELESS, "RuntimeError", None), id="caused-by-a-refusal"),
    pytest.param(KeyBearing(_youtube_403, GOOGLE_KEY, "HttpError", "quota spent"), id="youtube-403"),
    pytest.param(
        KeyBearing(lambda: RuntimeError(f"upstream refused {ANTHROPIC_KEY} today"), ANTHROPIC_KEY, "RuntimeError", "upstream refused"),
        id="anthropic-shaped",
    ),
    pytest.param(
        KeyBearing(lambda: ValueError(f"the key {GOOGLE_KEY} is not valid"), GOOGLE_KEY, "ValueError", "is not valid"),
        id="google-shaped",
    ),
    pytest.param(
        KeyBearing(lambda: LookupError(f"GET https://api.example/v1?api_key={URL_KEY} answered 404"), URL_KEY, "LookupError", "answered 404"),
        id="key-in-a-url",
    ),
]


def assert_kept_out(case: KeyBearing, text: str | None) -> None:
    """``text`` names the failure and keeps its words, with no key in it."""
    assert text, "the failure said nothing"
    assert case.secret not in text
    assert case.name in text
    if case.kept is not None:
        assert case.kept in text

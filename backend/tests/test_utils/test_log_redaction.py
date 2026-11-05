"""T-5.4.23 and T-5.6.16: a credential does not reach a log line.

The two nets of ``app/utils/log_redaction.py``. What matters is what comes out
of a real logger through a real formatter, so every check here reads the text a
handler wrote, and the uvicorn checks read a real uvicorn's output. No SDK makes
a request: the exceptions are the SDKs' own classes, built by hand.

Mutation checks (each failed the named test when this shipped):

- no ``install_log_redaction()`` call in ``app/__init__.py``
  (``test_a_real_uvicorn_start_keeps_the_filter``);
- installing on ``uvicorn.error`` alone
  (``test_a_real_uvicorn_start_keeps_the_filter``, on the HTTP line);
- a filter that redacts ``record.msg`` and leaves ``record.args``
  (``test_a_real_uvicorn_start_keeps_the_filter``);
- no ``_JWT`` pattern (``test_a_handshake_logged_at_debug_keeps_its_token``);
- ``BEARER_SUBPROTOCOL`` left out of ``accept``
  (``test_the_real_route_over_a_real_socket``);
- no split on a comma in ``_offered_token`` (that test, under
  ``websockets-sansio``);
- no ``_scrub_traceback`` (``test_a_traceback_is_scrubbed_by_every_formatter``);
- leaving ``exc_info`` on the record (the same test, under ``json``);
- ``_chain`` that stops at ``exc``
  (``test_an_exception_caused_by_a_refusal_goes_by_its_type``);
- ignoring ``__suppress_context__``
  (``test_from_none_is_not_a_refusal``);
- ``_is_refusal`` without the package check
  (``test_our_own_class_of_the_same_name_keeps_its_words``);
- ``_map_args`` dropping the mapping branch (``test_a_task_that_raises_a_refusal``).
"""
from __future__ import annotations

import io
import json
import logging
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import openai
import pytest
from celery.app.log import TaskFormatter
from celery.utils.log import ColorFormatter
from google.api_core.exceptions import PermissionDenied
from googleapiclient.errors import HttpError
from httplib2 import Response
from uvicorn.config import WS_PROTOCOLS
from uvicorn.logging import AccessFormatter, DefaultFormatter
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from app.agents import qa_agent
from app.services import llm_service
from app.services.llm_routing import UseCaseConfig
from app.utils import log_redaction
from app.utils.json_logging import JsonFormatter
from app.utils.log_redaction import (
    CREDENTIAL_QUERY_NAMES,
    REDACTED,
    install_log_redaction,
    provider_error_text,
    redact_url_credentials,
    scrub_keys,
)

_BACKEND = Path(__file__).resolve().parents[2]
_PYTHON = sys.executable

# A refused key as OpenAI quotes it, and one in no shape `scrub_keys` knows.
FRAGMENT = "sk-proj-abc***************wxyz"
SHAPELESS = "tenant-secret-42"
YOUTUBE_KEY = "AIzaSyD-0123456789abcdefghijklmnopqrstu"
# Only the shape matters here, never a signature.
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJlLW5vdC1yZWFs"


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://provider.example/v1/chat"))


def _openai_401(key: str = FRAGMENT) -> openai.AuthenticationError:
    message = f"Error code: 401 - {{'error': {{'message': 'Incorrect API key provided: {key}. You can find'}}}}"
    return openai.AuthenticationError(message, response=_response(401), body=None)


def _youtube_403() -> HttpError:
    uri = f"https://youtube.googleapis.com/youtube/v3/search?part=snippet&key={YOUTUBE_KEY}&alt=json"
    return HttpError(Response({"status": 403, "reason": "Forbidden"}), b'{"error": {"message": "quota spent"}}', uri=uri)


FORMATTERS = {
    "text": logging.Formatter("%(levelname)s %(name)s %(message)s"),
    "json": JsonFormatter(),
    "uvicorn": DefaultFormatter("%(levelprefix)s %(message)s"),
    "celery": ColorFormatter("%(levelname)s %(message)s", use_color=False),
    "celery_task": TaskFormatter("%(levelname)s %(task_name)s %(message)s", use_color=False),
}


@contextmanager
def written(name: str = "app.redaction.probe", formatter: logging.Formatter = FORMATTERS["text"]) -> Iterator[io.StringIO]:
    """What a real handler on the logger ``name`` writes. Not ``caplog``, which
    depends on what else has happened to global logging state."""
    log = logging.getLogger(name)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    saved = log.level, log.disabled
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.disabled = False
    try:
        yield stream
    finally:
        log.removeHandler(handler)
        log.setLevel(saved[0])
        log.disabled = saved[1]


# ---------------------------------------------------------------------------
# A credential in a URL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CREDENTIAL_QUERY_NAMES))
def test_every_credential_name_is_redacted(name):
    assert redact_url_credentials(f"/ws/jobs?{name}=abc123") == f"/ws/jobs?{name}={REDACTED}"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/x?TOKEN=abc", f"/x?TOKEN={REDACTED}"),
        ("/x?%74oken=abc", f"/x?%74oken={REDACTED}"),
        ("/x?a=1&token=abc&b=2", f"/x?a=1&token={REDACTED}&b=2"),
        ("/x?a=1;jwt=abc", f"/x?a=1;jwt={REDACTED}"),
        ("/x?token=abc#fragment", f"/x?token={REDACTED}#fragment"),
        ("/x?token=", f"/x?token={REDACTED}"),
        ("/auth/oauth/google/callback?code=abc&state=s", f"/auth/oauth/google/callback?code={REDACTED}&state=s"),
        (f"Sec-WebSocket-Protocol: bearer, {FAKE_JWT}", f"Sec-WebSocket-Protocol: bearer, {REDACTED}"),
        # Nothing else changes: a path has to stay readable.
        ("/x?mytoken=1&tokens=2&q=token", "/x?mytoken=1&tokens=2&q=token"),
        ("/api/v1/jobs/abc", "/api/v1/jobs/abc"),
        ("/api/v1/search?q=hello&limit=5", "/api/v1/search?q=hello&limit=5"),
    ],
)
def test_a_logged_path(path, expected):
    assert redact_url_credentials(path) == expected


def _uvicorn_line(logger_name, args, formatter):
    """A line on uvicorn's logger, through uvicorn's formatter and its format."""
    with written(logger_name, formatter) as stream:
        logging.getLogger(logger_name).info(*args)
    return stream.getvalue()


@pytest.mark.parametrize("formatter", [DefaultFormatter("%(levelprefix)s %(message)s", use_colors=False), JsonFormatter()])
def test_uvicorns_socket_line(formatter):
    line = _uvicorn_line(
        "uvicorn.error", ('%s - "WebSocket %s" [accepted]', "127.0.0.1:50000", f"/ws/jobs?token={FAKE_JWT}"), formatter
    )
    assert FAKE_JWT not in line
    assert f"/ws/jobs?token={REDACTED}" in line


def test_uvicorns_access_line_keeps_its_shape():
    """Its formatter unpacks five arguments, the status as a number."""
    formatter = AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    args = ('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", f"/x?token={FAKE_JWT}&keep=1", "1.1", 200)
    line = _uvicorn_line("uvicorn.access", args, formatter)
    assert FAKE_JWT not in line
    assert f'"GET /x?token={REDACTED}&keep=1 HTTP/1.1" 200 OK' in line


def test_a_line_with_no_arguments_is_redacted_too():
    with written("uvicorn.error") as stream:
        logging.getLogger("uvicorn.error").info(f"asked for /ws/jobs?token={FAKE_JWT}")
    assert FAKE_JWT not in stream.getvalue()


def test_installing_twice_changes_nothing():
    before = logging.getLogRecordFactory()
    filters = list(logging.getLogger("uvicorn.access").filters)
    install_log_redaction()
    assert logging.getLogRecordFactory() is before is log_redaction._scrubbed_record
    assert logging.getLogger("uvicorn.access").filters == filters


# ---------------------------------------------------------------------------
# A key in a provider's error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        (f"Incorrect API key provided: {FRAGMENT}. You can", f"Incorrect API key provided: {REDACTED} You can"),
        (f"incorrect api key provided: {SHAPELESS}", f"incorrect api key provided: {REDACTED}"),
        ("key sk-ant-api03-abc_def-ghi refused", f"key {REDACTED} refused"),
        (f"https://x/?part=a&key={YOUTUBE_KEY}&alt=json", f"https://x/?part=a&key={REDACTED}&alt=json"),
        ("https://x/?api_key=short", f"https://x/?api_key={REDACTED}"),
        (f"key is {YOUTUBE_KEY}", f"key is {REDACTED}"),
        # Words that only look alike stay.
        ("task-12345 risk-free desk-lamp", "task-12345 risk-free desk-lamp"),
        ("the monkey=1 key=2 stayed", "the monkey=1 key=2 stayed"),
        ("", ""),
    ],
)
def test_the_shapes_of_a_key(text, expected):
    assert scrub_keys(text) == expected


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_openai_401(SHAPELESS), id="openai-401"),
        pytest.param(openai.PermissionDeniedError(f"no: {SHAPELESS}", response=_response(403), body=None), id="openai-403"),
        pytest.param(anthropic.AuthenticationError(f"no: {SHAPELESS}", response=_response(401), body=None), id="anthropic-401"),
        pytest.param(PermissionDenied(f"no: {SHAPELESS}"), id="google-403"),
    ],
)
def test_a_refusal_goes_by_its_type_whatever_it_says(exc):
    assert provider_error_text(exc) == type(exc).__name__


def test_an_exception_caused_by_a_refusal_goes_by_its_type():
    class Wrapped(Exception):
        pass

    try:
        try:
            raise _openai_401(SHAPELESS)
        except openai.AuthenticationError as e:
            raise Wrapped(f"the call failed: {e}") from e
    except Wrapped as wrapped:
        assert provider_error_text(wrapped) == "Wrapped"


def test_an_error_raised_while_handling_a_refusal_counts_too():
    try:
        try:
            raise _openai_401(SHAPELESS)
        except openai.AuthenticationError as e:
            raise RuntimeError(str(e))
    except RuntimeError as chained:
        assert provider_error_text(chained) == "RuntimeError"


def test_from_none_is_not_a_refusal():
    """``raise X from None`` is the raiser saying the cause is not X's story, and
    no traceback shows it, so its own words stand."""
    try:
        try:
            raise _openai_401(SHAPELESS)
        except openai.AuthenticationError:
            raise ValueError("a clean sentence") from None
    except ValueError as clean:
        assert provider_error_text(clean) == "a clean sentence"


def test_any_other_error_keeps_its_words():
    assert provider_error_text(ValueError("file too large")) == "file too large"


def test_our_own_class_of_the_same_name_keeps_its_words():
    """The names mean a refusal in a model SDK only. A sign-in failure of ours
    says something an operator wants to read."""

    class AuthenticationError(Exception):
        pass

    assert provider_error_text(AuthenticationError("wrong password")) == "wrong password"


def test_a_youtube_403_keeps_its_words():
    """``googleapiclient`` is not a model SDK, and ``quota spent`` is what an
    operator needs to read. Its URL holds the install's key."""
    text = provider_error_text(_youtube_403())
    assert YOUTUBE_KEY not in text
    assert "quota spent" in text and "403" in text


def test_every_way_a_log_call_can_carry_an_exception():
    """An argument, a keyword-less message, an f-string, and the key inside a
    longer string, on one real logger."""
    log = logging.getLogger("app.redaction.probe")
    error = _openai_401(SHAPELESS)
    with written() as stream:
        log.warning("failed: %s", error)
        log.warning("failed: %r", error)
        log.warning(error)
        log.warning(f"failed: {error}")
        log.error("failed: %(reason)s", {"reason": error})
    text = stream.getvalue()
    assert SHAPELESS not in text
    assert text.count("AuthenticationError") >= 3


@pytest.mark.parametrize("kind", ["exception", "exc_info_true", "exc_info_value", "chained"])
@pytest.mark.parametrize("formatter", sorted(FORMATTERS))
def test_a_traceback_is_scrubbed_by_every_formatter(formatter, kind):
    log = logging.getLogger("app.redaction.probe")
    error = _openai_401(SHAPELESS)

    def fail():
        if kind == "chained":
            try:
                raise error
            except openai.AuthenticationError as e:
                raise RuntimeError("the map batch failed") from e
        raise error

    with written(formatter=FORMATTERS[formatter]) as stream:
        try:
            fail()
        except Exception as e:
            if kind == "exc_info_true":
                log.warning("it failed", exc_info=True)
            elif kind == "exc_info_value":
                log.warning("it failed", exc_info=e)
            else:
                log.exception("it failed")
    text = stream.getvalue()
    assert SHAPELESS not in text
    assert "Traceback" in text and "in fail" in text, "the traceback itself is kept"
    assert "AuthenticationError" in text, "and which error it was"


def test_a_truncated_quote_in_a_traceback_goes_by_its_shape():
    log = logging.getLogger("app.redaction.probe")
    with written() as stream:
        try:
            raise RuntimeError(f"the call failed: {str(_openai_401())[:80]}")
        except RuntimeError:
            log.exception("it failed")
    assert FRAGMENT[:12] not in stream.getvalue()


def test_an_ordinary_record_is_left_exactly_as_it_was():
    """``exc_info`` stays, so a formatter of Celery's keeps its own rendering,
    and an argument stays the object it was."""
    log = logging.getLogger("app.redaction.probe")
    seen: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record):
            seen.append(record)

    handler = Keep()
    argument = ValueError("plain")
    with written():
        log.addHandler(handler)
        try:
            try:
                raise ValueError("boom")
            except ValueError:
                log.exception("failed %d %s", 3, argument)
        finally:
            log.removeHandler(handler)
    [record] = seen
    assert record.exc_info is not None
    assert record.args == (3, argument) and record.args[1] is argument


def test_an_exception_with_no_readable_text_cannot_break_a_log_call():
    class Unreadable(Exception):
        def __str__(self):
            raise RuntimeError("no text here")

    log = logging.getLogger("app.redaction.probe")
    with written(), patch.object(logging, "raiseExceptions", False):
        log.warning("failed: %s", Unreadable())  # Must not raise.


def test_a_real_youtube_error_in_a_traceback():
    log = logging.getLogger("app.redaction.probe")
    with written() as stream:
        try:
            raise _youtube_403()
        except HttpError:
            log.exception("broad search failed")
    assert YOUTUBE_KEY not in stream.getvalue()
    assert "HttpError" in stream.getvalue()


# ---------------------------------------------------------------------------
# At the production callers
# ---------------------------------------------------------------------------


def test_logger_exception_on_a_model_call():
    """``logger.exception`` is how most of the agents log a failed call."""
    llm = MagicMock()
    llm.invoke.side_effect = _openai_401(SHAPELESS)
    with written("app.agents.qa_agent") as stream, patch.object(qa_agent, "get_llm_for", return_value=llm):
        assert qa_agent._generate_sub_queries("why?") == []
    assert "Sub-query expansion LLM call failed" in stream.getvalue()
    assert "AuthenticationError" in stream.getvalue()
    assert SHAPELESS not in stream.getvalue()


def test_an_exception_passed_to_a_log_line():
    client = MagicMock()
    client.models.retrieve.side_effect = _openai_401(SHAPELESS)
    with written("app.services.llm_service") as stream, patch("openai.OpenAI", return_value=client):
        assert llm_service._validate_model("gpt-x") is False
    assert "AuthenticationError" in stream.getvalue()
    assert SHAPELESS not in stream.getvalue()


def test_a_failed_probe_says_nothing_of_the_key():
    """Its ``error`` goes to the ``LLM probe FAILED`` line and ``/health/llm``."""
    llm = MagicMock()
    llm.invoke.side_effect = _openai_401(SHAPELESS)
    cfg = UseCaseConfig("openai", "gpt-x", "off")
    with patch.object(llm_service, "_build_from_config", return_value=llm):
        probe = llm_service.probe_config(cfg)
    assert probe.ok is False
    assert probe.error == "AuthenticationError"
    assert probe.status_code == 401


def test_a_task_that_raises_a_refusal():
    """Celery logs a task's failure itself, with a mapping for its arguments, a
    repr of the exception, and a traceback of its own objects. It also swaps an
    exception that will not pickle for the nearest base class that will, so the
    type is gone by then and the text is all that is left to go on."""
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="tests.refused_key", bind=False)
    def refused():
        raise _openai_401(SHAPELESS)

    try:
        with written("celery.app.trace", FORMATTERS["celery"]) as stream:
            refused.apply()
    finally:
        celery_app.tasks.pop("tests.refused_key", None)
    text = stream.getvalue()
    assert "raised unexpected" in text
    assert SHAPELESS not in text


# ---------------------------------------------------------------------------
# The real uvicorn
# ---------------------------------------------------------------------------

# Imports `app` as app.main does, so uvicorn has configured logging by then.
_TARGET = """
import app


async def application(scope, receive, send):
    if scope["type"] == "websocket":
        await receive()
        offered = scope["subprotocols"]
        await send({"type": "websocket.accept", "subprotocol": "bearer" if offered else None})
        await send({"type": "websocket.close"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})
"""

_SEED = """
import app.main
from app.database import Base, SessionLocal, engine
from app.services import auth_service

Base.metadata.create_all(engine)
db = SessionLocal()
user = auth_service.create_user(db, email="socket@example.com", password="a-long-test-password")
print("TOKEN", auth_service.create_access_token(user.id, db=db)[0])
"""


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """No provider key, no Redis that answers, and a database of its own."""
    env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")}
    env.pop("LOG_FORMAT", None)
    env.update(
        DATABASE_URL=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        CHROMA_PERSIST_DIR=str(tmp_path / "chroma"),
        REDIS_URL="redis://127.0.0.1:1/0",
        CELERY_BROKER_URL="memory://",
        CELERY_RESULT_BACKEND="cache+memory://",
        JWT_SECRET="a-long-random-value-for-this-test-alone",
        PYTHONIOENCODING="utf-8",
        **extra,
    )
    return env


@contextmanager
def _uvicorn(tmp_path: Path, env: dict[str, str], target: str, *flags: str) -> Iterator[int]:
    """The real CLI on a free port, writing to ``tmp_path/server.log``. No
    lifespan: that is where the startup probes and the backfills run."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [_PYTHON, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(port)]
    command += ["--no-proxy-headers", "--lifespan", "off", "--app-dir", str(tmp_path), *flags]
    with open(tmp_path / "server.log", "wb") as sink:
        process = subprocess.Popen(command, cwd=_BACKEND, env=env, stdout=sink, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 240
            while True:
                assert process.poll() is None, (tmp_path / "server.log").read_text(encoding="utf-8")[-4000:]
                assert time.monotonic() < deadline, "uvicorn did not start"
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.2)
            yield port
        finally:
            process.terminate()
            try:
                process.wait(30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(30)


def _log_of(tmp_path: Path) -> str:
    return (tmp_path / "server.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("log_format", ["text", "json"])
def test_a_real_uvicorn_start_keeps_the_filter(tmp_path, log_format):
    """The real CLI, its own logging config, its own format strings. uvicorn
    configures logging first and imports the app second, and the socket line
    and the access line are both real."""
    (tmp_path / "target.py").write_text(_TARGET, encoding="utf-8")
    with _uvicorn(tmp_path, _env(tmp_path, LOG_FORMAT=log_format), "target:application") as port:
        with connect(f"ws://127.0.0.1:{port}/ws/jobs?token={FAKE_JWT}", proxy=None, open_timeout=30):
            pass
        httpx.get(f"http://127.0.0.1:{port}/x?access_token={FAKE_JWT}&keep=1", trust_env=False, timeout=30)
    log = _log_of(tmp_path)
    assert FAKE_JWT not in log
    assert f"/ws/jobs?token={REDACTED}" in log, log
    assert "[accepted]" in log
    assert f"/x?access_token={REDACTED}&keep=1" in log, log
    if log_format == "json":
        for line in log.splitlines():
            json.loads(line)


def test_a_handshake_logged_at_debug_keeps_its_token(tmp_path):
    """At ``--log-level debug`` the websockets library writes every handshake
    header through ``uvicorn.error``, so a token moved out of the URL would land
    there instead."""
    (tmp_path / "target.py").write_text(_TARGET, encoding="utf-8")
    env = _env(tmp_path)
    with _uvicorn(tmp_path, env, "target:application", "--log-level", "debug") as port:
        with connect(f"ws://127.0.0.1:{port}/ws/jobs", subprotocols=["bearer", FAKE_JWT], proxy=None, open_timeout=30):
            pass
    log = _log_of(tmp_path)
    assert "Sec-WebSocket-Protocol" in log, "the header is logged at this level"
    assert FAKE_JWT not in log


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    """A database with one user in it, and a live token for them."""
    folder = tmp_path_factory.mktemp("socket")
    env = _env(folder)
    done = subprocess.run(
        [_PYTHON, "-c", _SEED], cwd=_BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600
    )
    assert done.returncode == 0, done.stderr[-4000:]
    token = next(line.split()[1] for line in done.stdout.splitlines() if line.startswith("TOKEN "))
    return folder, env, token


# uvicorn's two implementations on the websockets library read the header
# differently: one splits it and the other hands it over whole. wsproto is not
# installed. "auto" is the one the launchers get.
@pytest.mark.parametrize("ws", [w for w in ("auto", "websockets-sansio") if w in WS_PROTOCOLS])
def test_the_real_route_over_a_real_socket(seeded, ws):
    """``/ws/jobs`` and the real manager over a real socket, as a browser's
    handshake goes: the answer has to name the one subprotocol."""
    folder, env, token = seeded
    url = "ws://127.0.0.1:{port}/ws/jobs"
    with _uvicorn(folder, env, "app.main:app", "--ws", ws) as port:
        with connect(url.format(port=port), subprotocols=["bearer", token], proxy=None, open_timeout=30) as opened:
            assert opened.subprotocol == "bearer"
            assert opened.response.headers["Sec-WebSocket-Protocol"] == "bearer"
            opened.send("ping")
            assert opened.recv(timeout=30) == "pong"
        with pytest.raises(InvalidStatus) as refused:
            connect(f"{url.format(port=port)}?token={token}", proxy=None, open_timeout=30)
        assert refused.value.response.status_code == 403
    log = _log_of(folder)
    assert token not in log
    assert f"/ws/jobs?token={REDACTED}" in log, log
    assert "[accepted]" in log

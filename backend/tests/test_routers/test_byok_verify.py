"""T-5.6.8: "Verify key", ``POST /auth/credentials/{provider}/verify``.

Two layers, neither of which reaches a paid provider:

* Most tests run the route with the provider SDKs real and the provider
  replaced by a loopback HTTP server (``provider``), reached through each SDK's
  own base-URL setting. So the exception classes, the chains they are raised
  in and the request on the wire are the real ones; a hand-built exception
  would only prove the classifier agrees with itself.
* A few replace the client (``_build_from_config``) where a real one would be
  slow or could not get there: the wall clock and a never-answering provider.

What is pinned: the request is on the user's stored key and is the smallest
there is; the answer is one of three words, with nothing of the provider's
in it, while the provider's text does carry the key (asserted, so the no-echo
tests cannot pass by accident); it runs on the press alone; it is tier-gated
and rate-limited. Every "key" here is a placeholder.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import update

from app.config import settings
from app.models.user_credential import UserCredential
from app.routers import credentials as credentials_router
from app.services import auth_service, byok_service, llm_service
from app.services.llm_routing import MODEL_CONTEXT_WINDOWS

KEY = "fake-placeholder-not-a-key-5e1c"
URL = "/api/v1/auth/credentials/{}/verify"

OPENAI_OK = {
    "id": "x", "object": "chat.completion", "created": 1, "model": "m",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
ANTHROPIC_OK = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "m",
    "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
GOOGLE_OK = {
    "candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
}


def _openai_error(message: str, code: str) -> dict:
    return {"error": {"message": message, "type": "invalid_request_error", "code": code}}


def _anthropic_error(kind: str, message: str) -> dict:
    return {"type": "error", "error": {"type": kind, "message": message}}


def _google_error(code: int, status: str, message: str, reason: str) -> dict:
    return {"error": {"code": code, "message": message, "status": status, "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "domain": "googleapis.com"},
    ]}}


# The provider's own words, as it quotes them, key included.
OPENAI_401 = _openai_error(f"Incorrect API key provided: {KEY}. You can find your API key at ...", "invalid_api_key")
ANTHROPIC_401 = _anthropic_error("authentication_error", f"invalid x-api-key {KEY}")
GOOGLE_BAD_KEY = _google_error(400, "INVALID_ARGUMENT", f"API key not valid: {KEY}", "API_KEY_INVALID")


class _Provider:
    """A loopback server that answers every POST with ``status`` and ``body``,
    and keeps the requests it was sent."""

    def __init__(self) -> None:
        self.status = 200
        self.body: dict = OPENAI_OK
        self.requests: list[SimpleNamespace] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server's name
                length = int(self.headers.get("content-length") or 0)
                provider.requests.append(SimpleNamespace(
                    path=self.path, headers=dict(self.headers), body=json.loads(self.rfile.read(length) or b"{}"),
                ))
                payload = json.dumps(provider.body).encode("utf-8")
                self.send_response(provider.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.send_header("x-should-retry", "false")  # the OpenAI and Anthropic SDKs honour this
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, status: int, body: dict) -> None:
        self.status, self.body = status, body

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def provider(monkeypatch):
    server = _Provider()
    monkeypatch.setenv("OPENAI_API_BASE", f"{server.url}/v1")
    monkeypatch.setenv("ANTHROPIC_API_URL", server.url)
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", server.url)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    yield server
    server.close()


@pytest.fixture(autouse=True)
def _stable_fernet(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


@pytest.fixture
def studio(db, test_user):
    test_user.tier = "studio"
    db.commit()
    return test_user


def _store(db, user, provider_name: str = "openai", secret: str = KEY) -> None:
    byok_service.set_credential(db, user_id=user.id, provider=provider_name, secret=secret)


def _no_key_in(text: str) -> None:
    assert KEY not in text
    assert "Incorrect API key" not in text and "invalid x-api-key" not in text and "not valid" not in text


# ---------------------------------------------------------------- the three answers


@pytest.mark.parametrize(
    ("name", "answer"),
    [("openai", OPENAI_OK), ("anthropic", ANTHROPIC_OK), ("google", GOOGLE_OK)],
)
def test_a_good_key_is_valid(client, db, studio, provider, name, answer):
    _store(db, studio, name)
    provider.answer(200, answer)

    r = client.post(URL.format(name))

    assert r.status_code == 200, r.text
    assert r.json() == {"provider": name, "result": "valid"}


@pytest.mark.parametrize(
    ("name", "status", "body"),
    [
        ("openai", 401, OPENAI_401),
        ("openai", 403, _openai_error("Your account may not use this", "forbidden")),
        ("openai", 403, _openai_error("Missing scopes: model.request", "insufficient_permissions")),
        ("openai", 429, _openai_error("You exceeded your current quota", "insufficient_quota")),
        ("anthropic", 401, ANTHROPIC_401),
        ("anthropic", 403, _anthropic_error("permission_error", "This key may not use the API")),
        ("anthropic", 400, _anthropic_error("invalid_request_error", "Your credit balance is too low")),
        ("google", 400, GOOGLE_BAD_KEY),
        ("google", 403, _google_error(403, "PERMISSION_DENIED", "Blocked", "API_KEY_SERVICE_BLOCKED")),
    ],
)
def test_a_provider_that_says_no_to_the_key_refuses_it(client, db, studio, provider, name, status, body):
    """Google answers a bad key with a 400, and Anthropic an empty account: the
    two that a status table alone would call a request problem."""
    _store(db, studio, name)
    provider.answer(status, body)

    r = client.post(URL.format(name))

    assert r.json() == {"provider": name, "result": "refused"}
    assert len(provider.requests) >= 1


@pytest.mark.parametrize(
    ("name", "status", "body"),
    [
        ("openai", 500, _openai_error("The server had an error", "server_error")),
        ("openai", 404, _openai_error("The model does not exist", "model_not_found")),
        (
            "openai",
            403,
            _openai_error("Project `proj_x` does not have access to model `gpt-5.6-luna`", "model_not_found"),
        ),
        ("openai", 403, _openai_error("This key does not have access to model gpt-5.6-luna", "forbidden")),
        ("anthropic", 500, _anthropic_error("api_error", "Internal server error")),
        ("anthropic", 404, _anthropic_error("not_found_error", "model: not found")),
        ("anthropic", 400, _anthropic_error("invalid_request_error", "max_tokens: too small")),
    ],
)
def test_an_answer_that_says_nothing_about_the_key_is_no_verdict(client, db, studio, provider, name, status, body):
    """A retired model, a model this key was not given, or a bad day is not a
    bad key. Calling any of them "refused" sends the user to replace a key that
    works: a project key limited to the models the app really calls is common,
    and the check model need not be one of them."""
    _store(db, studio, name)
    provider.answer(status, body)

    assert client.post(URL.format(name)).json() == {"provider": name, "result": "unreachable"}


def test_no_answer_at_all_is_unreachable(client, db, studio, monkeypatch):
    """A closed port, through the real SDK."""
    closed = _Provider()
    url = closed.url
    closed.close()
    monkeypatch.setenv("OPENAI_API_BASE", f"{url}/v1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    _store(db, studio)

    assert client.post(URL.format("openai")).json()["result"] == "unreachable"


def test_a_provider_past_the_wall_clock_is_unreachable(client, db, studio, monkeypatch):
    """The SDKs' own timeouts run to minutes. The route does not wait for them."""
    release = threading.Event()

    class _Hangs:
        def invoke(self, messages):
            release.wait(10)
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(llm_service, "_build_from_config", lambda *a, **k: _Hangs())
    monkeypatch.setattr(llm_service, "KEY_CHECK_TIMEOUT_SECONDS", 0.05)
    _store(db, studio)

    start = time.monotonic()
    r = client.post(URL.format("openai"))
    release.set()

    assert r.json()["result"] == "unreachable"
    assert time.monotonic() - start < 5


def test_an_empty_answer_is_still_an_answer(client, db, studio, monkeypatch):
    """``probe_config`` calls it a failure, and for a startup probe it is. For
    a key it is proof the provider took the request."""

    class _SaysNothing:
        def invoke(self, messages):
            return SimpleNamespace(content="")

    monkeypatch.setattr(llm_service, "_build_from_config", lambda *a, **k: _SaysNothing())
    _store(db, studio)

    assert client.post(URL.format("openai")).json()["result"] == "valid"


def test_a_client_that_cannot_be_built_is_unreachable(client, db, studio, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError(f"provider=google requires: pip install langchain-google-genai {KEY}")

    monkeypatch.setattr(llm_service, "_build_from_config", broken)
    _store(db, studio, "google")

    r = client.post(URL.format("google"))

    assert r.json()["result"] == "unreachable"
    _no_key_in(r.text)


# ---------------------------------------------------------------- the request


def test_the_request_is_on_the_stored_key(client, db, studio, provider):
    _store(db, studio)
    settings_key = settings.OPENAI_API_KEY

    client.post(URL.format("openai"))

    assert len(provider.requests) == 1
    sent = provider.requests[0].headers.get("Authorization") or provider.requests[0].headers.get("authorization")
    assert sent == f"Bearer {KEY}"
    assert KEY != settings_key


@pytest.mark.parametrize(
    ("name", "answer", "budget"),
    [
        ("openai", OPENAI_OK, lambda b: b.get("max_completion_tokens") or b.get("max_tokens")),
        ("anthropic", ANTHROPIC_OK, lambda b: b.get("max_tokens")),
        ("google", GOOGLE_OK, lambda b: b["generationConfig"]["maxOutputTokens"]),
    ],
)
def test_the_request_is_the_smallest_there_is(client, db, studio, provider, name, answer, budget):
    """One request, the provider's cheap model, 16 tokens, no thinking, on the
    stored key. Which header carries it is the SDK's business: it differs
    between the Anthropic SDK in the dev venv and the one a clean install gets."""
    _store(db, studio, name)
    provider.answer(200, answer)

    client.post(URL.format(name))

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert budget(request.body) == 16
    assert any(KEY in value for value in request.headers.values())
    assert llm_service.KEY_CHECK_MODELS[name] in json.dumps(request.body) + request.path
    assert "thinking" not in request.body
    assert "image" not in json.dumps(request.body)


def test_each_provider_with_a_key_has_a_model_the_app_lists():
    """A model the app has no record of would turn every check into "could not
    reach". Keyed like the panel's list, so a new provider cannot be missed."""
    assert set(llm_service.KEY_CHECK_MODELS) == set(byok_service.RESOLVED_PROVIDERS)
    assert set(llm_service.KEY_CHECK_MODELS.values()) <= set(MODEL_CONTEXT_WINDOWS)


def test_claudes_check_model_is_not_one_that_refuses_a_probes_temperature():
    """Claude 5 models refuse the temperature a probe sends with reasoning off
    (the Anthropic note in the LLM stack), which would read as "could not
    reach" on every Anthropic key."""
    assert not llm_service.KEY_CHECK_MODELS["anthropic"].startswith(
        llm_service._ANTHROPIC_ADAPTIVE_THINKING_PREFIXES
    )


# ---------------------------------------------------------------- what it never says


@pytest.mark.parametrize(
    ("name", "status", "body"),
    [("openai", 401, OPENAI_401), ("anthropic", 401, ANTHROPIC_401), ("google", 400, GOOGLE_BAD_KEY)],
)
def test_neither_the_key_nor_the_providers_words_reach_the_response(client, db, studio, provider, name, status, body):
    _store(db, studio, name)
    provider.answer(status, body)

    r = client.post(URL.format(name))

    assert set(r.json()) == {"provider", "result"}
    _no_key_in(r.text)
    _no_key_in(str(dict(r.headers)))


def test_the_provider_text_really_did_carry_the_key(db, studio, provider):
    """Without this the two tests around it could pass on an error with no key
    in it. The text exists in what the SDK raises. Since T-5.6.16 the probe's
    ``error`` drops it, so a route could not repeat it if it tried."""
    provider.answer(401, OPENAI_401)
    cfg = llm_service.UseCaseConfig("openai", llm_service.KEY_CHECK_MODELS["openai"], "off")

    with pytest.raises(Exception) as raised:
        llm_service._build_from_config(cfg, 0.0, 16, byok_api_key=KEY).invoke("hello")
    probe = llm_service.probe_config(cfg, byok_api_key=KEY)

    assert KEY in str(raised.value)
    assert probe.status_code == 401
    assert probe.error == "AuthenticationError"


def test_neither_reaches_the_log(client, db, studio, provider):
    """On the loggers themselves: ``caplog`` depends on global logging state."""
    _store(db, studio)
    provider.answer(401, OPENAI_401)

    with (
        patch.object(llm_service, "logger") as llm_log,
        patch.object(credentials_router, "logger") as route_log,
        patch.object(byok_service, "logger") as byok_log,
    ):
        client.post(URL.format("openai"))

    for logger in (llm_log, route_log, byok_log):
        _no_key_in(repr(logger.mock_calls))


# ---------------------------------------------------------------- only on the press


def test_nothing_else_on_the_page_calls_a_provider(client, db, studio, provider):
    """It is a paid request, so no read, and no save, may make it."""
    _store(db, studio)

    assert client.get("/api/v1/auth/credentials").status_code == 200
    assert client.get("/api/v1/auth/credentials/providers").status_code == 200
    assert client.get("/api/v1/settings/llm").status_code == 200
    assert client.put("/api/v1/auth/credentials/anthropic", json={"secret": KEY}).status_code == 200

    assert provider.requests == []


def test_the_install_key_is_never_the_one_tried(client, db, studio, provider, monkeypatch):
    """With nothing stored there is nothing to check, whatever the install has."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "fake-placeholder-install-key")

    r = client.post(URL.format("openai"))

    assert r.status_code == 404
    assert provider.requests == []


# ---------------------------------------------------------------- the gates


@pytest.mark.parametrize("tier", ["free", "pro"])
def test_the_tier_gate_is_the_keys_own(client, db, test_user, provider, tier):
    test_user.tier = tier
    db.commit()
    _store(db, test_user)

    r = client.post(URL.format("openai"))

    assert r.status_code == 403
    assert provider.requests == []


@pytest.mark.parametrize("name", ["local", "mistral"])
def test_a_provider_no_call_reads_a_key_for_is_refused(client, db, studio, provider, name):
    r = client.post(URL.format(name))

    assert r.status_code == 400
    assert provider.requests == []


def test_a_key_that_cannot_be_read_is_not_reported_as_no_key(client, db, studio, provider, monkeypatch):
    """The encryption key changed. Saying "not stored" would send the user to
    the wrong fix; it is the operator's, and the 503 says so."""
    _store(db, studio)
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()

    r = client.post(URL.format("openai"))

    assert r.status_code == 503
    assert "cannot be read" in r.json()["detail"]
    assert provider.requests == []
    assert settings.BYOK_ENCRYPTION_KEY not in r.text


def test_a_corrupt_row_is_not_reported_as_no_key(client, db, studio, provider):
    _store(db, studio)
    db.execute(update(UserCredential).values(encrypted_secret="not-a-token"))
    db.commit()

    assert client.post(URL.format("openai")).status_code == 503
    assert provider.requests == []


def test_a_malformed_encryption_key_is_a_503_that_names_the_setting(client, db, studio, provider, monkeypatch):
    _store(db, studio)
    malformed = "malformed-placeholder-3b9d"
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", malformed)
    byok_service._get_fernet.cache_clear()

    r = client.post(URL.format("openai"))

    assert r.status_code == 503
    assert "BYOK_ENCRYPTION_KEY" in r.json()["detail"]
    assert malformed not in r.text
    assert provider.requests == []


def test_get_credential_still_falls_back_on_an_unreadable_key(db, studio, monkeypatch):
    """A call has the install's key to use, so it must not start raising."""
    _store(db, studio)
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()

    assert byok_service.get_credential(db, studio.id, "openai") is None


# ---------------------------------------------------------------- the rate limit


@pytest.fixture
def limited(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_VERIFY_KEY_PER_MIN", 2)


def test_a_press_past_the_limit_never_reaches_the_provider(client, db, studio, provider, limited):
    _store(db, studio)

    assert client.post(URL.format("openai")).status_code == 200
    assert client.post(URL.format("openai")).status_code == 200
    r = client.post(URL.format("openai"))

    assert r.status_code == 429
    assert set(r.json()) == {"detail", "retry_after_sec"}, "the one 429 shape every rate limit answers with"
    assert int(r.headers["Retry-After"]) >= 1
    assert len(provider.requests) == 2


def test_the_limit_is_one_users_and_covers_every_provider(client, db, studio, provider, limited):
    """Three providers, one bucket: it bounds requests on the user's keys, not
    requests per key. Another user's presses are their own."""
    _store(db, studio, "openai")
    _store(db, studio, "anthropic")
    provider.answer(200, OPENAI_OK)

    client.post(URL.format("openai"))
    client.post(URL.format("openai"))
    assert client.post(URL.format("anthropic")).status_code == 429

    other = auth_service.create_user(db, email="other@example.com", password="pw" * 6)
    other.tier = "studio"
    db.commit()
    _store(db, other)
    token, _ = auth_service.create_access_token(other.id)
    r = client.post(URL.format("openai"), headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_a_refused_tier_spends_nothing_from_the_limit(client, db, test_user, provider, limited):
    for _ in range(3):
        assert client.post(URL.format("openai")).status_code == 403

    test_user.tier = "studio"
    db.commit()
    _store(db, test_user)
    assert client.post(URL.format("openai")).status_code == 200


def test_the_kill_switch_covers_this_limit_too(client, db, studio, provider, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_VERIFY_KEY_PER_MIN", 1)
    _store(db, studio)

    assert [client.post(URL.format("openai")).status_code for _ in range(3)] == [200, 200, 200]

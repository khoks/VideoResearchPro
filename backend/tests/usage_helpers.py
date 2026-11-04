"""Shared fakes for the E-5.2 usage-metering tests.

``metered_llms`` replaces only the provider client that
``llm_service.get_llm_for`` builds (``_build_from_config``) with a real
LangChain chat model that reports token usage. Everything above it stays
production code: ``get_llm_for`` itself, the meter it attaches, the scope the
caller opened, and the write when the scope closes. A test that patched
``get_llm_for`` instead would bypass the meter and prove nothing.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

CLARIFY_JSON = '{"interpretation": "you mean X", "clarifications": ["a?", "b?", "c?"]}'


class MeteredFakeChat(BaseChatModel):
    """Answers every call with ``reply`` and reports ``tokens_in`` / ``tokens_out``."""

    reply: str = "ok"
    tokens_in: int = 100
    tokens_out: int = 20
    report_usage: bool = True

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        usage = (
            {"input_tokens": self.tokens_in, "output_tokens": self.tokens_out,
             "total_tokens": self.tokens_in + self.tokens_out}
            if self.report_usage else None
        )
        msg = AIMessage(content=self.reply, usage_metadata=usage) if usage else AIMessage(content=self.reply)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "metered-fake"


class FakeFactory:
    """What the patched ``_build_from_config`` hands out, and a log of it."""

    def __init__(self) -> None:
        self.reply = "ok"
        self.tokens_in = 100
        self.tokens_out = 20
        self.report_usage = True
        self.built: list[Any] = []

    def __call__(self, cfg, temperature, max_tokens, *, byok_api_key=None):
        llm = MeteredFakeChat(
            reply=self.reply, tokens_in=self.tokens_in, tokens_out=self.tokens_out,
            report_usage=self.report_usage,
        )
        self.built.append(llm)
        return llm


@pytest.fixture
def metered_llms(monkeypatch) -> FakeFactory:
    from app.services import llm_service

    factory = FakeFactory()
    monkeypatch.setattr(llm_service, "_build_from_config", factory)
    return factory


def call_llm(use_case: str, prompt: str = "hello") -> str:
    """One call through the production factory, as an agent makes it."""
    from langchain_core.messages import HumanMessage

    from app.services.llm_service import get_llm_for, response_text

    return response_text(get_llm_for(use_case).invoke([HumanMessage(content=prompt)]))


def usage_rows(db, tenant_id: str) -> dict[tuple[str, str], int]:
    """``{(feature, metric): amount}`` for today's ``usage_records`` rows."""
    from app.models.usage_record import UsageRecord

    db.expire_all()
    today = datetime.now(timezone.utc).date()
    return {
        (r.feature, r.metric): r.amount
        for r in db.query(UsageRecord).filter(UsageRecord.tenant_id == tenant_id, UsageRecord.day == today)
    }


def tenants_with_usage(db) -> set[str]:
    from app.models.usage_record import UsageRecord

    db.expire_all()
    return {r.tenant_id for r in db.query(UsageRecord)}


class FakeYouTubeClient:
    """Stands in for ``googleapiclient``'s YouTube resource: every
    ``<resource>().list(**params).execute()`` returns the canned response for
    that resource. Only the network is replaced; ``_execute_youtube_request``
    and ``quota_service.record`` run for real."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, resource: str):
        if resource.startswith("_"):
            raise AttributeError(resource)
        client = self

        class _Resource:
            def list(self, **params):
                client.calls.append((resource, params))

                class _Request:
                    def execute(self_inner):
                        r = client.responses[resource]
                        return r(params) if callable(r) else r

                return _Request()

        return lambda: _Resource()


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def incrby(self, key, amount):
        self.counts[key] = self.counts.get(key, 0) + amount

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.counts.get(key)


class _WhisperSegment(SimpleNamespace):
    """A pydantic model in the SDK: read by attribute, and by ``model_dump``."""

    def model_dump(self) -> dict:
        return dict(vars(self))


class FakeWhisperApi:
    """The OpenAI client below ``_whisper_transcribe_with_retry``, so that
    function, the meter behind it and every caller above it are production
    code. ``seconds`` is what each response reports; ``sent`` counts responses.
    ``before_send`` runs first and may raise, as a dying worker does."""

    def __init__(self) -> None:
        self.seconds = 60.0
        self.sent = 0
        self.before_send = None
        self.client = MagicMock()
        self.client.with_options.return_value = self.client
        self.client.audio.transcriptions.create.side_effect = self._create

    def _create(self, **kwargs):
        if self.before_send is not None:
            self.before_send(self)
        self.sent += 1
        segment = _WhisperSegment(text=f"spoken words {self.sent}", start=0.0, end=self.seconds)
        return SimpleNamespace(language="en", duration=self.seconds, segments=[segment])


@pytest.fixture
def whisper_api(monkeypatch) -> FakeWhisperApi:
    api = FakeWhisperApi()
    monkeypatch.setattr("openai.OpenAI", lambda *a, **k: api.client)
    return api


@pytest.fixture
def flush_always_due(monkeypatch):
    """Every look at the clock is a long time after the last, so each
    checkpoint writes. Only for code that writes from one thread at a time: the
    suite's sessions share one connection (``StaticPool``)."""
    from app.services import usage_service

    ticks = itertools.count(0, 3600)
    monkeypatch.setattr(usage_service, "_clock", lambda: next(ticks))


@pytest.fixture
def youtube_network(monkeypatch, db):
    """Route the install-wide quota log to the test database and replace the
    YouTube client with ``FakeYouTubeClient``; set ``.responses`` per test."""
    from app.services import quota_service, youtube_service
    from tests import conftest as _conftest

    monkeypatch.setattr(quota_service, "SessionLocal", _conftest.TestingSessionLocal)
    redis = FakeRedis()
    monkeypatch.setattr(quota_service, "get_redis", lambda: redis)
    fake = FakeYouTubeClient({})
    monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: fake)
    fake.redis = redis
    return fake

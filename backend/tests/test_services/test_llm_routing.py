"""Tests for LLM purpose routing (primary vs fast, OpenAI vs local).

The goal of Unit 8 is to let cheap, low-stakes LLM calls route to a local
OpenAI-compatible server (e.g. LM Studio) while keeping final-answer calls
on OpenAI. These tests monkeypatch ``ChatOpenAI`` to capture constructor
kwargs and assert the routing logic matches each ``purpose``.
"""

import pytest

from app.services import llm_service


class _FakeChatOpenAI:
    """Spy stand-in for ``langchain_openai.ChatOpenAI``.

    Captures constructor kwargs so tests can assert on what the service
    passed. We don't need any runtime behavior beyond that.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def fake_chat(monkeypatch):
    """Patch ``ChatOpenAI`` inside the llm_service module and reset cached state."""
    monkeypatch.setattr(llm_service, "ChatOpenAI", _FakeChatOpenAI)
    # The module caches the validated primary model name across calls; reset
    # between tests so each case starts from a clean slate.
    monkeypatch.setattr(llm_service, "_validated_model", None)
    # Avoid the real OpenAI models.retrieve round-trip on the primary path.
    monkeypatch.setattr(llm_service, "_validate_model", lambda _model: True)
    return _FakeChatOpenAI


def test_fast_with_base_url_passes_base_url_and_fast_model(monkeypatch, fake_chat):
    """purpose='fast' + LLM_FAST_BASE_URL set → base_url + fast model + fast api_key."""
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "local-model")
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_API_KEY", "not-needed")

    llm = llm_service.get_llm(temperature=0.2, purpose="fast")

    assert isinstance(llm, fake_chat)
    assert llm.kwargs["base_url"] == "http://localhost:1234/v1"
    assert llm.kwargs["model"] == "local-model"
    assert llm.kwargs["api_key"] == "not-needed"
    assert llm.kwargs["temperature"] == 0.2


def test_fast_without_base_url_uses_openai_with_fast_model(monkeypatch, fake_chat):
    """purpose='fast' + LLM_FAST_BASE_URL unset → no base_url; model == LLM_FAST_MODEL."""
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", None)
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "gpt-4.1-mini")
    monkeypatch.setattr(llm_service.settings, "OPENAI_API_KEY", "sk-test")

    llm = llm_service.get_llm(purpose="fast")

    assert "base_url" not in llm.kwargs
    assert llm.kwargs["model"] == "gpt-4.1-mini"
    # Fast path without a base URL still uses the primary OpenAI key.
    assert llm.kwargs["api_key"] == "sk-test"


def test_primary_uses_settings_llm_model_no_base_url(monkeypatch, fake_chat):
    """purpose='primary' (default) → LLM_MODEL, no base_url override."""
    monkeypatch.setattr(llm_service.settings, "LLM_MODEL", "gpt-5")
    # Even if a fast base URL is configured, primary must not use it.
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(llm_service.settings, "OPENAI_API_KEY", "sk-test")

    llm = llm_service.get_llm()

    assert "base_url" not in llm.kwargs
    assert llm.kwargs["model"] == "gpt-5"
    assert llm.kwargs["api_key"] == "sk-test"


def test_primary_is_default_when_purpose_omitted(monkeypatch, fake_chat):
    """Calls that omit ``purpose`` must land on the primary path unchanged."""
    monkeypatch.setattr(llm_service.settings, "LLM_MODEL", "gpt-5")
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", "http://localhost:1234/v1")

    llm = llm_service.get_llm(temperature=0.0)

    assert llm.kwargs["model"] == "gpt-5"
    assert "base_url" not in llm.kwargs


def test_max_tokens_forwarded_when_provided(monkeypatch, fake_chat):
    """max_tokens must propagate to ChatOpenAI for both purposes."""
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", None)
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "gpt-4.1-mini")

    fast = llm_service.get_llm(max_tokens=500, purpose="fast")
    assert fast.kwargs["max_tokens"] == 500

    primary = llm_service.get_llm(max_tokens=1000)
    assert primary.kwargs["max_tokens"] == 1000

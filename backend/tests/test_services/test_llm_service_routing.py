"""Tests for app.services.llm_service routing dispatch.

Confirms both the legacy ``get_llm(purpose=...)`` shim and the new
``get_llm_for(use_case=...)`` path:

  * ``get_llm(purpose="fast")`` builds a ``ChatOpenAI`` pointed at
    ``LLM_FAST_BASE_URL`` when that env var is set, otherwise hits the
    default OpenAI endpoint.
  * ``get_llm(purpose="primary")`` dispatches on ``LLM_PRIMARY_PROVIDER``.
  * ``get_llm_for(use_case=...)`` resolves a ``UseCaseConfig`` from the
    registry and dispatches to the matching provider builder.
  * ``LLM_USE_CASE_CONFIG`` overrides steer a single call site to a
    different provider/model/reasoning level.
  * ``LLM_ROUTE_OVERRIDES`` legacy flips the provider to ``local``.
  * ``local`` provider routes through the OpenAI-compatible path using
    ``LLM_LOCAL_BASE_URL`` / ``LLM_LOCAL_API_KEY`` and falls back to the
    legacy ``LLM_FAST_*`` vars.
  * Caller kwargs (``temperature``, ``max_tokens``) flow through to the
    underlying builder.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import llm_service


@pytest.fixture(autouse=True)
def _reset_validated_model_cache() -> None:
    """Keep the OpenAI model-validation cache clean between tests."""
    llm_service._validated_model = None
    yield
    llm_service._validated_model = None


@pytest.fixture
def _clear_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank both override env vars so ``get_llm_for`` sees registry defaults."""
    monkeypatch.setattr(llm_service.settings, "LLM_USE_CASE_CONFIG", "")
    monkeypatch.setattr(llm_service.settings, "LLM_ROUTE_OVERRIDES", "")


def test_fast_path_uses_local_base_url_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_service.settings, "LLM_FAST_BASE_URL", "http://localhost:1234/v1"
    )
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "local-model-xyz")
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_API_KEY", "not-needed")

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm(purpose="fast")

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:1234/v1"
    assert kwargs["model"] == "local-model-xyz"
    assert kwargs["api_key"] == "not-needed"


def test_fast_path_without_base_url_hits_default_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", None)
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "gpt-4.1-mini")

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm(purpose="fast")

    kwargs = mock_openai.call_args.kwargs
    assert "base_url" not in kwargs
    assert kwargs["model"] == "gpt-4.1-mini"


def test_primary_openai_uses_primary_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_MODEL", "gpt-4o")
    monkeypatch.setattr(llm_service, "_validate_model", lambda m: True)

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm(purpose="primary")

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert "base_url" not in kwargs


def test_primary_openai_falls_back_when_model_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_MODEL", "gpt-does-not-exist")
    monkeypatch.setattr(llm_service.settings, "LLM_FALLBACK_MODEL", "gpt-4o")
    monkeypatch.setattr(llm_service, "_validate_model", lambda m: False)

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm(purpose="primary")

    assert mock_openai.call_args.kwargs["model"] == "gpt-4o"


def test_get_llm_for_uses_registry_default_config(_clear_overrides: None) -> None:
    """With no env overrides, ``get_llm_for`` builds from ``default_config``."""
    from app.services import llm_routing

    expected = llm_routing.USE_CASE_REGISTRY["qa_clarification"].default_config
    assert expected.provider == "openai"

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for("qa_clarification")

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["model"] == expected.model
    # reasoning="off" → no model_kwargs; provider=openai → no base_url.
    assert "model_kwargs" not in kwargs
    assert "base_url" not in kwargs


def test_get_llm_for_use_case_config_override_routes_to_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``LLM_USE_CASE_CONFIG`` steers one call site to a different provider."""
    monkeypatch.setattr(
        llm_service.settings,
        "LLM_USE_CASE_CONFIG",
        "qa_formulate_answer=anthropic:claude-opus-4-5:high",
    )
    monkeypatch.setattr(llm_service.settings, "LLM_ROUTE_OVERRIDES", "")
    monkeypatch.setattr(llm_service.settings, "ANTHROPIC_API_KEY", "sk-ant-test")

    mock_anthropic_cls = MagicMock()
    with patch.dict(
        "sys.modules",
        {"langchain_anthropic": MagicMock(ChatAnthropic=mock_anthropic_cls)},
    ):
        with patch.object(llm_service, "ChatOpenAI") as mock_openai:
            llm_service.get_llm_for("qa_formulate_answer")

    mock_openai.assert_not_called()
    mock_anthropic_cls.assert_called_once()
    kwargs = mock_anthropic_cls.call_args.kwargs
    assert kwargs["model"] == "claude-opus-4-5"
    assert kwargs["api_key"] == "sk-ant-test"
    # reasoning=high → thinking budget enabled.
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 16_384}


def test_get_llm_for_dispatches_google_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider=google routes through ``ChatGoogleGenerativeAI``."""
    monkeypatch.setattr(
        llm_service.settings,
        "LLM_USE_CASE_CONFIG",
        "qa_formulate_answer=google:gemini-2.5-pro:medium",
    )
    monkeypatch.setattr(llm_service.settings, "LLM_ROUTE_OVERRIDES", "")
    monkeypatch.setattr(llm_service.settings, "GOOGLE_API_KEY", "goog-test")

    mock_google_cls = MagicMock()
    with patch.dict(
        "sys.modules",
        {"langchain_google_genai": MagicMock(ChatGoogleGenerativeAI=mock_google_cls)},
    ):
        with patch.object(llm_service, "ChatOpenAI") as mock_openai:
            llm_service.get_llm_for("qa_formulate_answer", max_tokens=4_000)

    mock_openai.assert_not_called()
    mock_google_cls.assert_called_once()
    kwargs = mock_google_cls.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-pro"
    assert kwargs["google_api_key"] == "goog-test"
    # Google uses max_output_tokens, not max_tokens.
    assert kwargs["max_output_tokens"] == 4_000
    # reasoning=medium on Google → thinking_budget=8192.
    assert kwargs["thinking_budget"] == 8_192


def test_get_llm_for_local_provider_uses_local_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider=local routes through OpenAI-compatible path at LLM_LOCAL_BASE_URL."""
    monkeypatch.setattr(
        llm_service.settings,
        "LLM_USE_CASE_CONFIG",
        "qa_clarification=local:qwen3.5-9b:off",
    )
    monkeypatch.setattr(llm_service.settings, "LLM_ROUTE_OVERRIDES", "")
    monkeypatch.setattr(
        llm_service.settings, "LLM_LOCAL_BASE_URL", "http://localhost:9999/v1"
    )
    monkeypatch.setattr(llm_service.settings, "LLM_LOCAL_API_KEY", "local-key")

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for("qa_clarification")

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:9999/v1"
    assert kwargs["api_key"] == "local-key"
    assert kwargs["model"] == "qwen3.5-9b"


def test_get_llm_for_local_provider_falls_back_to_fast_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``LLM_LOCAL_*`` is unset, ``LLM_FAST_*`` acts as the fallback."""
    monkeypatch.setattr(
        llm_service.settings,
        "LLM_USE_CASE_CONFIG",
        "qa_clarification=local:qwen3.5-9b:off",
    )
    monkeypatch.setattr(llm_service.settings, "LLM_ROUTE_OVERRIDES", "")
    monkeypatch.setattr(llm_service.settings, "LLM_LOCAL_BASE_URL", "")
    monkeypatch.setattr(llm_service.settings, "LLM_LOCAL_API_KEY", "")
    monkeypatch.setattr(
        llm_service.settings, "LLM_FAST_BASE_URL", "http://localhost:1234/v1"
    )
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_API_KEY", "fast-key")

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for("qa_clarification")

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:1234/v1"
    assert kwargs["api_key"] == "fast-key"


def test_get_llm_for_passes_temperature_and_max_tokens(
    _clear_overrides: None,
) -> None:
    """Caller-provided kwargs flow through to the underlying builder."""
    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for(
            "qa_clarification", temperature=0.7, max_tokens=4_000
        )

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 4_000


def test_get_llm_for_legacy_route_override_flips_to_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy ``LLM_ROUTE_OVERRIDES=<uc>=fast`` swaps provider to ``local``."""
    monkeypatch.setattr(llm_service.settings, "LLM_USE_CASE_CONFIG", "")
    monkeypatch.setattr(
        llm_service.settings,
        "LLM_ROUTE_OVERRIDES",
        "library_qa_formulate_answer=fast",
    )
    monkeypatch.setattr(
        llm_service.settings, "LLM_LOCAL_BASE_URL", "http://localhost:1234/v1"
    )
    monkeypatch.setattr(llm_service.settings, "LLM_LOCAL_API_KEY", "not-needed")
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "fast-m")

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for("library_qa_formulate_answer")

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:1234/v1"
    assert kwargs["model"] == "fast-m"

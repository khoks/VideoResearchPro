"""Tests for app.services.llm_service routing dispatch.

Confirms:
  * ``get_llm(purpose="fast")`` builds a ``ChatOpenAI`` pointed at
    ``LLM_FAST_BASE_URL`` when that env var is set.
  * ``get_llm(purpose="fast")`` uses the default OpenAI endpoint when
    ``LLM_FAST_BASE_URL`` is unset.
  * ``get_llm(purpose="primary")`` dispatches on ``LLM_PRIMARY_PROVIDER``.
  * ``get_llm_for(use_case=...)`` resolves the route from the registry and
    honors ``LLM_ROUTE_OVERRIDES``.
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


def test_get_llm_for_resolves_registry_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_llm_for`` picks fast vs primary from the registry default."""
    from app.services import llm_routing

    # qa_clarification defaults to fast; library_qa_formulate_answer defaults to primary.
    monkeypatch.setattr(llm_service.settings, "LLM_ROUTE_OVERRIDES", "")
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", None)
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "fast-m")
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_MODEL", "primary-m")
    monkeypatch.setattr(llm_service, "_validate_model", lambda m: True)

    assert llm_routing.USE_CASE_REGISTRY["qa_clarification"].default_route == "fast"
    assert (
        llm_routing.USE_CASE_REGISTRY["library_qa_formulate_answer"].default_route
        == "primary"
    )

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for("qa_clarification")
        fast_model = mock_openai.call_args.kwargs["model"]

        llm_service.get_llm_for("library_qa_formulate_answer")
        primary_model = mock_openai.call_args.kwargs["model"]

    assert fast_model == "fast-m"
    assert primary_model == "primary-m"


def test_get_llm_for_honors_route_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LLM_ROUTE_OVERRIDES`` flips the route at runtime."""
    monkeypatch.setattr(
        llm_service.settings,
        "LLM_ROUTE_OVERRIDES",
        "library_qa_formulate_answer=fast",
    )
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_BASE_URL", None)
    monkeypatch.setattr(llm_service.settings, "LLM_FAST_MODEL", "fast-m")
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setattr(llm_service.settings, "LLM_PRIMARY_MODEL", "primary-m")
    monkeypatch.setattr(llm_service, "_validate_model", lambda m: True)

    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service.get_llm_for("library_qa_formulate_answer")

    assert mock_openai.call_args.kwargs["model"] == "fast-m"

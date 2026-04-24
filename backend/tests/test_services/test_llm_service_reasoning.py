"""Tests for reasoning-level translation in the LLM provider builders.

Each provider has its own reasoning-parameter shape:

  * OpenAI    -> ``model_kwargs={"reasoning_effort": ...}`` (omitted when
                reasoning is ``off``; ``auto`` -> ``medium``).
  * Anthropic -> ``thinking={"type": "enabled", "budget_tokens": ...}``
                (omitted when reasoning is ``off``).
  * Google    -> ``thinking_budget`` (integer; ``-1`` for adaptive/``auto``,
                ``0`` for ``off``).

These tests parametrize across every reasoning level and assert the
provider kwargs land in the expected shape -- or are omitted when the
level is ``off``.
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


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reasoning, expected_effort",
    [
        ("off", None),
        ("minimal", "minimal"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("auto", "medium"),  # OpenAI has no adaptive knob -- map to medium.
    ],
)
def test_build_openai_passes_reasoning_effort(
    reasoning: str, expected_effort: str | None
) -> None:
    with patch.object(llm_service, "ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm_service._build_openai(
            model="gpt-5.4",
            temperature=0.0,
            max_tokens=None,
            reasoning=reasoning,  # type: ignore[arg-type]
        )

    kwargs = mock_openai.call_args.kwargs
    if expected_effort is None:
        assert "model_kwargs" not in kwargs
    else:
        assert kwargs["model_kwargs"] == {"reasoning_effort": expected_effort}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reasoning, expected_budget",
    [
        ("off", None),
        ("minimal", 1_024),
        ("low", 2_048),
        ("medium", 4_096),
        ("high", 16_384),
        ("auto", 4_096),  # Claude has no adaptive knob -- map to medium budget.
    ],
)
def test_build_anthropic_passes_thinking_budget(
    reasoning: str,
    expected_budget: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service.settings, "ANTHROPIC_API_KEY", "sk-ant-test")

    fake_chat_anthropic = MagicMock()
    fake_module = MagicMock(ChatAnthropic=fake_chat_anthropic)
    with patch.dict(
        "sys.modules", {"langchain_anthropic": fake_module}
    ):
        llm_service._build_anthropic(
            model="claude-opus-4-5",
            temperature=0.0,
            max_tokens=None,
            reasoning=reasoning,  # type: ignore[arg-type]
        )

    kwargs = fake_chat_anthropic.call_args.kwargs
    if expected_budget is None:
        assert "thinking" not in kwargs
    else:
        assert kwargs["thinking"] == {
            "type": "enabled",
            "budget_tokens": expected_budget,
        }


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reasoning, expected_budget",
    [
        ("off", 0),
        ("minimal", 512),
        ("low", 2_048),
        ("medium", 8_192),
        ("high", 16_384),
        ("auto", -1),  # Gemini 2.5 adaptive thinking.
    ],
)
def test_build_google_passes_thinking_budget(
    reasoning: str,
    expected_budget: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service.settings, "GOOGLE_API_KEY", "goog-test")

    fake_chat_google = MagicMock()
    fake_module = MagicMock(ChatGoogleGenerativeAI=fake_chat_google)
    with patch.dict(
        "sys.modules", {"langchain_google_genai": fake_module}
    ):
        llm_service._build_google(
            model="gemini-2.5-pro",
            temperature=0.0,
            max_tokens=None,
            reasoning=reasoning,  # type: ignore[arg-type]
        )

    kwargs = fake_chat_google.call_args.kwargs
    assert kwargs["thinking_budget"] == expected_budget

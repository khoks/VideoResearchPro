"""Unit tests for `app.services.social_classify` — D-007/D-014/D-021/D-023.

The module exports:
- `StanceClassification` Pydantic schema (T-1.5.3.1)
- `TOPIC_RELEVANCE_THRESHOLD = 0.50` constant (D-021)
- `classify(text, query)` function that calls the
  `social_classify_stance` LLM use case inline (T-1.5.3.3, D-023)

Strategy: mock `get_llm_for("social_classify_stance", ...)` to return a
spy LLM whose `.invoke()` returns whatever JSON we want, so we lock
down (a) the prompt → output → schema round-trip, (b) the fail-soft
behaviour on errors / malformed JSON / empty inputs, and (c) the
shape of the `extra["classification"]` payload connectors propagate.
"""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

from app.services.social_classify import (
    TOPIC_RELEVANCE_THRESHOLD,
    StanceClassification,
    classify,
)


# ---------------------------------------------------------------------------
# Schema + constants
# ---------------------------------------------------------------------------
def test_topic_relevance_threshold_is_050() -> None:
    """D-021 anchor: the cut-off threshold is 0.50."""
    assert TOPIC_RELEVANCE_THRESHOLD == 0.50


def test_stance_classification_schema_round_trips() -> None:
    """The Pydantic model accepts a four-axis dict and round-trips via model_dump."""
    raw = {
        "stance": "for",
        "sentiment": "positive",
        "framing": "experiential",
        "topic_relevance": 0.87,
    }
    sc = StanceClassification(**raw)
    assert sc.model_dump() == raw


# ---------------------------------------------------------------------------
# classify() — fail-soft paths
# ---------------------------------------------------------------------------
def test_classify_returns_fallback_when_query_is_empty() -> None:
    """Empty query short-circuits before calling the LLM (orchestrator
    hasn't wired through a topic yet)."""
    with patch("app.services.llm_service.get_llm_for") as mock_llm:
        result = classify(text="A post about something", query="")
    mock_llm.assert_not_called()
    assert result.stance == "unclear"
    assert result.sentiment == "neutral"
    assert result.framing == "technical"
    assert result.topic_relevance == 0.0


def test_classify_returns_fallback_when_text_is_empty() -> None:
    """Empty text short-circuits — nothing meaningful to classify."""
    with patch("app.services.llm_service.get_llm_for") as mock_llm:
        result = classify(text="", query="tariffs")
    mock_llm.assert_not_called()
    assert result.stance == "unclear"


def test_classify_returns_fallback_when_llm_raises() -> None:
    """LLM provider error must not crash; classifier returns low-confidence default."""
    fake_llm = Mock()
    fake_llm.invoke.side_effect = RuntimeError("provider offline")
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text="Some post", query="tariffs")
    assert result.stance == "unclear"
    assert result.topic_relevance == 0.0


def test_classify_returns_fallback_when_response_is_not_json() -> None:
    """Garbage LLM output yields fallback (not a parse error)."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(content="not json at all")
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text="Some post", query="tariffs")
    assert result.stance == "unclear"


def test_classify_returns_fallback_when_response_is_a_json_array() -> None:
    """JSON that's valid but not a dict (e.g. an array) yields fallback."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(content='["not", "a", "dict"]')
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text="Some post", query="tariffs")
    assert result.stance == "unclear"


def test_classify_returns_fallback_when_response_violates_schema() -> None:
    """Pydantic validation error (e.g. `stance` outside Literal set) yields fallback."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(
        content=json.dumps(
            {
                "stance": "extremely-against",  # not in Literal
                "sentiment": "positive",
                "framing": "technical",
                "topic_relevance": 0.5,
            }
        )
    )
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text="Some post", query="tariffs")
    assert result.stance == "unclear"


# ---------------------------------------------------------------------------
# classify() — happy path + code-fence tolerance
# ---------------------------------------------------------------------------
def test_classify_parses_clean_json() -> None:
    """Happy path: the LLM returns a clean JSON object; classify() round-trips it."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(
        content=json.dumps(
            {
                "stance": "against",
                "sentiment": "negative",
                "framing": "experiential",
                "topic_relevance": 0.9,
            }
        )
    )
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text="In my industry tariffs broke us", query="tariffs")
    assert result.stance == "against"
    assert result.sentiment == "negative"
    assert result.framing == "experiential"
    assert result.topic_relevance == 0.9


def test_classify_tolerates_code_fence_wrapped_json() -> None:
    """Some models add ```json ... ``` despite the system prompt."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(
        content="```json\n"
        + json.dumps(
            {
                "stance": "for",
                "sentiment": "positive",
                "framing": "technical",
                "topic_relevance": 1.0,
            }
        )
        + "\n```"
    )
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text="The benchmark numbers support this", query="caching")
    assert result.stance == "for"
    assert result.framing == "technical"
    assert result.topic_relevance == 1.0


def test_classify_truncates_long_text_before_sending() -> None:
    """Connector might pass a very long flattened thread; classifier caps input
    so we don't blow the cheap classifier's context window."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(
        content=json.dumps(
            {
                "stance": "neutral",
                "sentiment": "neutral",
                "framing": "technical",
                "topic_relevance": 0.4,
            }
        )
    )
    long_text = "x" * 50_000  # 50K chars; classifier should cap at 8000

    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        classify(text=long_text, query="anything")

    # Inspect the prompt that went to the LLM and confirm truncation.
    call_args = fake_llm.invoke.call_args[0][0]
    user_msg = call_args[1]
    # 8000 chars + the wrapper text; user message should be well under 50K.
    assert len(user_msg.content) < 9000


def test_classify_includes_topic_in_prompt() -> None:
    """The user message must thread the topic into the prompt so the LLM
    grounds topic_relevance in the right axis."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(
        content=json.dumps(
            {
                "stance": "neutral",
                "sentiment": "neutral",
                "framing": "technical",
                "topic_relevance": 0.0,
            }
        )
    )
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        classify(text="A post body", query="quantum computing")

    call_args = fake_llm.invoke.call_args[0][0]
    user_msg = call_args[1]
    assert "quantum computing" in user_msg.content
    assert "A post body" in user_msg.content

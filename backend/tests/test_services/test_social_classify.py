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


# ---------------------------------------------------------------------------
# Golden classifier fixtures (T-1.5.3.5)
# ---------------------------------------------------------------------------
# These verify the round-trip plumbing handles each axis-value
# combination correctly — they are NOT live LLM tests. Each test wires
# the classifier to receive a synthetic JSON output that a well-behaved
# `gpt-4.1-mini`-grade model would plausibly produce for the input
# text, then asserts the classifier surfaces those values intact onto
# `StanceClassification` (preserving stance / sentiment / framing /
# topic_relevance and respecting Literal type validation).
#
# Live-LLM evaluation of prompt accuracy is a separate concern (out
# of unit-test scope; see ``backend/scripts/stress_test_llm.py`` for
# the harness pattern).
# ---------------------------------------------------------------------------


def _golden_llm_response(payload: dict) -> Mock:
    """Build a fake LLM `invoke()` result returning the given JSON dict."""
    fake_llm = Mock()
    fake_llm.invoke.return_value = Mock(content=json.dumps(payload))
    return fake_llm


def test_golden_sarcasm_renders_as_against_with_positive_tone() -> None:
    """A sarcastic in-favor-sounding post about a policy should classify
    as against (the author's actual polarity) with positive tone (the
    surface register the LLM detected). The plumbing must preserve
    that mismatch — stance != sentiment is intentional per D-007."""
    sarcasm_text = (
        "Oh wonderful, ANOTHER new mandate. Just what we all needed. "
        "I'm sure this one will solve everything our last six tries didn't."
    )
    fake_llm = _golden_llm_response({
        "stance": "against",
        "sentiment": "positive",  # surface tone; sarcasm not detected
        "framing": "emotional",
        "topic_relevance": 0.85,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=sarcasm_text, query="new policy mandates")

    assert result.stance == "against"
    assert result.sentiment == "positive"
    assert result.framing == "emotional"
    assert result.topic_relevance == 0.85


def test_golden_sincere_praise_renders_as_for_with_positive_tone() -> None:
    """Straightforward sincere praise — stance and sentiment align."""
    sincere_text = (
        "I've been using this library in production for three months. "
        "Latency dropped 40% and the API surface is genuinely well-designed. "
        "Hard to overstate how much time it has saved my team."
    )
    fake_llm = _golden_llm_response({
        "stance": "for",
        "sentiment": "positive",
        "framing": "experiential",
        "topic_relevance": 0.92,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=sincere_text, query="caching libraries")

    assert result.stance == "for"
    assert result.sentiment == "positive"
    assert result.framing == "experiential"
    assert result.topic_relevance >= 0.9


def test_golden_in_favor_technical_argument() -> None:
    """A "for" stance argued from data + mechanism — framing=technical."""
    text = (
        "The benchmark math supports this approach: at 200 rps the "
        "old implementation hit p99 of 850ms; with the new index "
        "structure the same workload measures p99 of 220ms. That's "
        "a 4x improvement at zero memory overhead."
    )
    fake_llm = _golden_llm_response({
        "stance": "for",
        "sentiment": "positive",
        "framing": "technical",
        "topic_relevance": 0.95,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=text, query="indexing strategies")

    assert result.stance == "for"
    assert result.framing == "technical"
    assert result.topic_relevance >= 0.9


def test_golden_against_political_framing() -> None:
    """An "against" stance argued from ideology / group-identity rather
    than data — framing=political."""
    text = (
        "This is exactly what the donor class has been pushing for "
        "a decade. The framework looks neutral on paper but in "
        "practice it locks in incumbent advantages and squeezes new "
        "entrants out of the market entirely."
    )
    fake_llm = _golden_llm_response({
        "stance": "against",
        "sentiment": "negative",
        "framing": "political",
        "topic_relevance": 0.88,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=text, query="regulatory framework reform")

    assert result.stance == "against"
    assert result.sentiment == "negative"
    assert result.framing == "political"


def test_golden_neutral_with_mixed_sentiment() -> None:
    """A neutral stance / mixed sentiment post — important to verify
    "neutral" + "mixed" Literals round-trip cleanly (these are the
    "didn't pick a side" defaults)."""
    text = (
        "Both approaches have real trade-offs. Approach A is faster "
        "but harder to debug; approach B is slower but more "
        "transparent. Neither is universally right; depends on the "
        "team's debugging tolerance."
    )
    fake_llm = _golden_llm_response({
        "stance": "neutral",
        "sentiment": "mixed",
        "framing": "technical",
        "topic_relevance": 0.78,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=text, query="caching strategy comparison")

    assert result.stance == "neutral"
    assert result.sentiment == "mixed"


def test_golden_unclear_stance_on_too_short_text() -> None:
    """Very short ambiguous text — classifier should default to
    `unclear` per the prompt's "safe fallback" guidance."""
    text = "Hmm, interesting."
    fake_llm = _golden_llm_response({
        "stance": "unclear",
        "sentiment": "neutral",
        "framing": "emotional",
        "topic_relevance": 0.3,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=text, query="whatever the topic is")

    assert result.stance == "unclear"
    # Below D-021 threshold — caller should hide by default.
    assert result.topic_relevance < TOPIC_RELEVANCE_THRESHOLD


def test_golden_off_topic_drift_low_relevance() -> None:
    """A post that's tangentially related but not centrally about the
    topic — classifier should drop topic_relevance below the 0.50
    threshold so the approval UI hides it by default."""
    text = (
        "Speaking of caching — my cat knocked over my coffee this "
        "morning and I had to restart my whole workflow. Anyway, "
        "the article was fine I guess."
    )
    fake_llm = _golden_llm_response({
        "stance": "neutral",
        "sentiment": "neutral",
        "framing": "experiential",
        "topic_relevance": 0.15,
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=text, query="caching strategies")

    assert result.topic_relevance < TOPIC_RELEVANCE_THRESHOLD
    assert result.framing == "experiential"


def test_golden_borderline_relevance_at_threshold() -> None:
    """A post adjacent to the topic — classifier returns ~0.5 which is
    on the boundary. The threshold is `>= 0.5`, so 0.5 exact surfaces."""
    text = "Tangentially related discussion about a sibling concern."
    fake_llm = _golden_llm_response({
        "stance": "neutral",
        "sentiment": "neutral",
        "framing": "technical",
        "topic_relevance": 0.5,  # exactly at threshold
    })
    with patch("app.services.llm_service.get_llm_for", return_value=fake_llm):
        result = classify(text=text, query="anything")

    # 0.5 is *at* the threshold — caller's `>= 0.5` filter surfaces it.
    assert result.topic_relevance == TOPIC_RELEVANCE_THRESHOLD

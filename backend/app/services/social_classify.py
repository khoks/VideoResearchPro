"""Stance / sentiment / framing / topic-relevance classification for social posts.

This module exposes the schema + threshold constants that the
`social_classify_stance` LLM use case (registered in
`app.services.llm_routing`) returns and that the social-media ingest
pipeline (S-1.5.3) consumes per fetched candidate document and per
comment. The `classify()` function is the call-site entry point —
connectors invoke it inline from their `fetch_text()` per D-023.

See:
- D-007 — Sentiment / stance classification at fetch time
- D-014 — Add `framing` axis to `social_classify_stance` schema
- D-021 — Topic relevance threshold = 0.50
- D-023 — `social_classify_stance` invoked inline inside each connector
- docs/source-types.md § Stance / sentiment classification at fetch time
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Display-list cutoff per D-021. Candidates with `topic_relevance` below
# this are hidden from the default approval list but kept in the
# database; a "Show low-relevance candidates" filter chip toggles the
# cutoff to 0.0 (S-1.5.4 T-1.5.4.3).
TOPIC_RELEVANCE_THRESHOLD: float = 0.50


# Stance toward the topic — polarity. Per D-007.
Stance = Literal["for", "against", "neutral", "unclear"]


# Tone of the post — register-of-feeling. Per D-007.
Sentiment = Literal["positive", "negative", "mixed", "neutral"]


# Register through which the author engages with the topic. Per D-014.
# - technical: data / mechanism / system-level reasoning
# - political: ideology / party-line / group-identity
# - emotional: affect-driven, tone over reasoning
# - experiential: first-person lived experience
Framing = Literal["technical", "political", "emotional", "experiential"]


class StanceClassification(BaseModel):
    """LLM output schema for `social_classify_stance`.

    Returned per candidate `Document` and per comment under
    `source_metadata.comments[]`. Persisted onto
    `Document.source_metadata` (and similarly for comments) by the
    ingestion pipeline (S-1.5.3 T-1.5.3.4).

    `topic_relevance` uses **calibrated scoring** per D-021's prompt
    guidance:
      - 1.0 — unambiguously on-topic
      - 0.5 — adjacent / partially related
      - 0.0 — unrelated

    The classifier is `gpt-4.1-mini`-grade (cheap-and-fast); operators
    routing this elsewhere should keep the schema + scoring discipline
    intact. See also: TOPIC_RELEVANCE_THRESHOLD for the
    surfacing-vs-hiding cut.
    """

    stance: Stance = Field(
        ...,
        description=(
            "Author's polarity toward the topic. 'unclear' is the safe "
            "fallback when the post is too short / ambiguous to call."
        ),
    )
    sentiment: Sentiment = Field(
        ...,
        description=(
            "Tone of the post itself. Distinct from stance — a post can "
            "be 'against' the topic with 'positive' tone (sarcasm-free)."
        ),
    )
    framing: Framing = Field(
        ...,
        description=(
            "Register through which the author engages with the topic. "
            "Pick one primary value per D-014; multi-label deferred."
        ),
    )
    topic_relevance: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "How directly this post addresses the queried topic, on a "
            "calibrated 0..1 scale (1.0 unambiguous / 0.5 adjacent / "
            "0.0 unrelated). Posts below TOPIC_RELEVANCE_THRESHOLD are "
            "hidden from the default approval list per D-021."
        ),
    )


# Maximum text length sent to the classifier. Bounded so that a long
# Reddit OP + 50 comments doesn't blow past the cheap classifier's
# context window. The classifier only needs enough text to read register
# + topic relevance; classifier-grade summarization quality is fine.
_MAX_CLASSIFIER_INPUT_CHARS: int = 8000


# System prompt — D-014 framing exemplars + D-021 calibrated scoring.
# Two exemplars per framing value spanning topical domains (tech /
# policy / generic life) so the classifier learns *register*, not topic.
# Topic-relevance is calibrated on a 1.0/0.5/0.0 anchor scale with 0.4-0.6
# borderline guidance baked in so the threshold (0.50) maps to a sensible
# cut. Prompt is intentionally short — 4-axis classification at
# `gpt-4.1-mini` grade tolerates verbosity poorly.
_SYSTEM_PROMPT: str = """You classify social-media posts on four axes:
stance, sentiment, framing, topic_relevance.

Return ONLY a single JSON object — no prose, no code fences. Schema:
{
  "stance": "for" | "against" | "neutral" | "unclear",
  "sentiment": "positive" | "negative" | "mixed" | "neutral",
  "framing": "technical" | "political" | "emotional" | "experiential",
  "topic_relevance": <float between 0.0 and 1.0>
}

DEFINITIONS

stance — author's polarity toward the topic. "unclear" is the safe
fallback when the post is too short / ambiguous to call.

sentiment — tone of the post itself. Distinct from stance — a post can
be "against" the topic with "positive" tone, or "for" with "negative".

framing — register through which the author engages with the topic.
Pick exactly one primary value:
- technical: argues from data, citations, mechanism, system-level
  reasoning. Examples:
  • "The benchmark numbers don't support that claim — at p99 latency
    the system stalls under 200 rps, well below the published spec."
  • "Adding the proposed feature requires recomputing the entire
    embedding index, which is O(n^2) in document count."
- political: argues from ideology, party-line, group-identity.
  Examples:
  • "This is exactly what the donor class wants — they've been
    pushing this regulatory framework for a decade because it locks
    in their incumbent advantage."
  • "Of course the progressive caucus is celebrating; this is their
    playbook on every issue."
- emotional: argues from affect, outrage, joy, fear; tone-driven
  without a reasoning chain. Examples:
  • "I cannot believe this passed. It's appalling. Whoever wrote
    this should be ashamed."
  • "This is honestly the most exciting development I've seen in
    years — I'm still buzzing from reading it."
- experiential: argues from first-person lived experience. Examples:
  • "I worked on a team that tried this exact approach in 2019 and
    it took us six months to migrate back. The hidden cost is the
    on-call burden."
  • "As someone who's been homeschooling for eight years, I can tell
    you the curriculum thing is way more complex than the article
    makes out."

topic_relevance — how directly the post addresses the queried topic,
on a calibrated 0..1 scale:
- 1.0 — unambiguously on-topic (post is centrally about the topic)
- 0.5 — adjacent / partially related (mentions the topic but isn't
  centrally about it; or about a sibling concern in the same domain)
- 0.0 — unrelated to the topic
Borderline cases in 0.4-0.6 are the cut-off zone; default to lower
when uncertain. Score from the post's own text — do not reward keyword
matching alone if the post merely mentions the topic in passing.

OUTPUT — JSON only, no markdown fences."""


# Fail-soft fallback when the LLM call errors or returns malformed JSON.
# Per the project's "fail-soft on LLM failure" doctrine: classification
# is a hint surface, never a hard gate. Returning low-confidence
# defaults preserves the candidate in the approval list (just without
# badge color); the user can still approve by inspection.
_FALLBACK_CLASSIFICATION: dict[str, object] = {
    "stance": "unclear",
    "sentiment": "neutral",
    "framing": "technical",
    "topic_relevance": 0.0,
}


def _strip_code_fence(raw: str) -> str:
    """Tolerate ```json ... ``` fences if the model adds them despite
    the system prompt instruction. Mirrors `knowledge_agent._parse_extraction`."""
    s = (raw or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        end = -1 if lines and lines[-1].startswith("```") else len(lines)
        s = "\n".join(lines[1:end])
    return s


def classify(text: str, query: str) -> StanceClassification:
    """Classify `text` (a social-media post body, optionally including
    flattened OP + top comments) on stance / sentiment / framing /
    topic_relevance against the topic `query`.

    Per [D-023](../../../docs/decisions.md#d-023), this is invoked
    inline from each connector's `fetch_text()`. The connector decides
    what text to classify — Reddit might pass OP + top-comment summary,
    HN might pass story + top-comment, Mastodon might pass OP-only.

    Fail-soft: if `query` is empty (orchestrator hasn't wired the
    topic through yet), or the LLM call errors, or the response is
    malformed, returns a low-confidence fallback (`stance="unclear"`,
    `topic_relevance=0.0`). The caller decides whether to surface the
    candidate; the classifier itself never raises.
    """
    if not text or not query:
        return StanceClassification(**_FALLBACK_CLASSIFICATION)  # type: ignore[arg-type]

    # Late import to break the import cycle: this module is imported by
    # connectors at module load time; llm_service imports the use-case
    # registry which itself imports nothing classifier-specific.
    from app.services.llm_service import get_llm_for

    truncated = text[:_MAX_CLASSIFIER_INPUT_CHARS]
    user_msg = (
        f"TOPIC: {query.strip()}\n\nPOST:\n{truncated}\n\n"
        "Classify this post on the four axes per the schema."
    )

    try:
        llm = get_llm_for("social_classify_stance", temperature=0.0, max_tokens=200)
        response = llm.invoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
        )
        raw = (response.content or "").strip()
    except Exception:
        logger.exception(
            "social_classify_stance LLM call failed; returning fallback classification"
        )
        return StanceClassification(**_FALLBACK_CLASSIFICATION)  # type: ignore[arg-type]

    body = _strip_code_fence(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning(
            "social_classify_stance returned non-JSON: %r; using fallback",
            body[:200],
        )
        return StanceClassification(**_FALLBACK_CLASSIFICATION)  # type: ignore[arg-type]

    if not isinstance(data, dict):
        logger.warning(
            "social_classify_stance returned non-object: %r; using fallback",
            data,
        )
        return StanceClassification(**_FALLBACK_CLASSIFICATION)  # type: ignore[arg-type]

    try:
        return StanceClassification(**data)
    except Exception:
        # Pydantic ValidationError or similar — the model returned a
        # value outside the Literal sets, or a non-numeric topic_relevance.
        logger.warning(
            "social_classify_stance schema validation failed for %r; using fallback",
            data,
        )
        return StanceClassification(**_FALLBACK_CLASSIFICATION)  # type: ignore[arg-type]


__all__ = [
    "TOPIC_RELEVANCE_THRESHOLD",
    "Stance",
    "Sentiment",
    "Framing",
    "StanceClassification",
    "classify",
]

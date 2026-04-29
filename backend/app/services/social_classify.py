"""Stance / sentiment / framing / topic-relevance classification for social posts.

This module exposes the schema + threshold constants that the
`social_classify_stance` LLM use case (registered in
`app.services.llm_routing`) returns and that the social-media ingest
pipeline (S-1.5.3) consumes per fetched candidate document and per
comment.

See:
- D-007 — Sentiment / stance classification at fetch time
- D-014 — Add `framing` axis to `social_classify_stance` schema
- D-021 — Topic relevance threshold = 0.50
- docs/source-types.md § Stance / sentiment classification at fetch time

The actual prompt (with the 8 framing exemplars per D-014 / D-021's
calibrated topic-relevance scoring guidance) lands when T-1.5.3.6
ships the classification call site itself; this module owns only the
shared types + threshold so the schema is importable from the
ingestion pipeline (T-1.5.3.3) and the approval-UI filter
(S-1.5.4 T-1.5.4.3) without circular imports.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


__all__ = [
    "TOPIC_RELEVANCE_THRESHOLD",
    "Stance",
    "Sentiment",
    "Framing",
    "StanceClassification",
]

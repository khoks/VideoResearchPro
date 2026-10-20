"""Question-suggestion payloads (S-8.4.1)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SuggestionOrigin(BaseModel):
    """Where a history suggestion was first asked."""

    source: str | None = None
    exchange_id: str | None = None
    job_id: str | None = None


class Suggestion(BaseModel):
    question: str
    rationale: str = ""
    #: ``generated`` from the context summary, ``history`` from the caller's past questions.
    source: Literal["generated", "history"]
    origin: SuggestionOrigin | None = None


class SuggestionsResponse(BaseModel):
    context: str
    suggestions: list[Suggestion]
    #: Served from ``suggestion_cache`` without a model call.
    cached: bool
    #: The generator ran and returned questions; false means history only.
    generated: bool


class SuggestionFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: str = Field(max_length=120)
    question: str = Field(min_length=1, max_length=300)
    #: ``fill`` put it in the composer; ``ask`` asked it at once (Shift-click).
    action: Literal["fill", "ask"]
    source: Literal["generated", "history"] | None = None

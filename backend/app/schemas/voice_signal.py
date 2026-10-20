"""Voice-signal payloads (S-3.3.1)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SignalType = Literal[
    "vocabulary", "cadence", "framing", "recurring_reference", "formality_register", "register_per_audience",
    "trusted_conclusion", "preferred_solution", "recommendation_lens", "apprehension", "methodology",
    "topic_emphasis", "perception_lens", "interest",
]
Language = Literal["en", "hi-Deva", "hi-Latn", "mixed"]
Register = Literal["intimate", "casual", "professional", "public"]

# `register` is the wire name; the attribute is `register_` because
# pydantic's BaseModel already has a `register`.
_ALIASED = ConfigDict(populate_by_name=True)


class SignalExample(BaseModel):
    text: str
    #: note:<id> | share:<id> | qa:<id> | library_qa:<id> | history_qa:<id> | user
    source: str
    at: str | None = None


class VoiceSignalItem(BaseModel):
    model_config = _ALIASED

    id: str
    signal_type: str
    layer: Literal["style", "personality"]
    value: str
    weight: float
    examples: list[SignalExample]
    language: str | None
    register_: str | None = Field(alias="register")
    derived_from: list[str]
    origin: str
    consent_version: str
    created_at: datetime
    updated_at: datetime


class LearningState(BaseModel):
    """What extraction has read and what is waiting (S-3.3.2)."""

    #: celery | inline | off
    mode: str
    #: The user's own texts Echo may learn from: live notes, questions,
    #: own-words shares.
    inputs: int
    by_language: dict[str, int]
    #: New, edited or deleted texts not yet read.
    pending: int
    #: A run is queued automatically once this many are waiting.
    threshold: int
    last_learned_at: datetime | None


class VoiceSignalList(BaseModel):
    items: list[VoiceSignalItem]
    consent_version: str
    learning: LearningState | None = None


class LearnResponse(BaseModel):
    #: queued | ran | waiting | off | not_entitled | queue_failed
    status: str
    pending: int


class VoiceSignalCreate(BaseModel):
    """A signal the user states about themselves."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    signal_type: SignalType
    value: str = Field(min_length=1, max_length=500)
    language: Language | None = None
    register_: Register | None = Field(default=None, alias="register")


class VoiceSignalPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    value: str | None = Field(default=None, min_length=1, max_length=500)
    language: Language | None = None
    register_: Register | None = Field(default=None, alias="register")
    weight: float | None = Field(default=None, ge=0, le=100)

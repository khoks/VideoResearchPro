from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Reference(BaseModel):
    # The agent's references are polymorphic by `source_type` (S-1.5.5:
    # permalink, thread_title, page_number, ...; S-8.5.2: note_id,
    # note_target_*, quote). Declaring only the YouTube fields with the
    # default `extra="ignore"` silently stripped all of that from every
    # response, so a Reddit or PDF citation reached the browser as a
    # YouTube link. Extra fields pass through.
    model_config = {"extra": "allow"}

    video_url: str
    video_title: str
    channel_name: str
    timestamp_seconds: float
    timestamp_display: str  # "12:34"
    youtube_link: str  # URL with &t= parameter


class ClarifyRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class ClarifyResponse(BaseModel):
    interpretation: str
    clarifications: list[str]


class QARequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    context: str | None = Field(default=None, max_length=4000)
    # S-1.15.2 / T-1.15.2.3: per-request depth override. None falls back to
    # the job's `output_length`, and NULL there lets the corpus bracket
    # decide (D-064). Never a cap — it scales the derived budget.
    output_length: Literal["auto", "brief", "standard", "deep"] | None = None


class QAResponse(BaseModel):
    id: str
    question: str
    answer: str
    references: list[Reference]
    created_at: datetime

    model_config = {"from_attributes": True}

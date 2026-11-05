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


class StoredCutOff(BaseModel):
    """T-1.15.4.8: whether a stored answer stopped at its token budget.

    Sent only when it did. A row from before the column is unknown and a checked
    row may say `false`, but neither reaches the wire: a finished answer's JSON
    is what it was, and no stored row claims "not cut" (D-145). The fresh shapes
    below replace this field, so they keep saying `false`.
    """

    answer_cut_off: bool | None = Field(default=None, exclude_if=lambda cut: cut is not True)


class QAResponse(StoredCutOff):
    id: str
    question: str
    answer: str
    references: list[Reference]
    created_at: datetime

    model_config = {"from_attributes": True}


class QAAnswerResponse(QAResponse):
    """An answer that has just been written (`POST /qa`, and the stream's
    `complete` event).

    T-1.15.4.5: `answer_cut_off` says whether it stopped at its token budget.
    This reply is checked by name, so it says `false` too; the history routes
    return `QAResponse`, which carries the stored flag only when it is true.
    """

    answer_cut_off: bool = False

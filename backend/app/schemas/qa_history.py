"""Pydantic schemas for the Q&A history chat API (Unit 2 — Personal Wiki)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.qa import StoredCutOff


class QAHistoryReference(BaseModel):
    """A citation surfaced by the Q&A history agent.

    Points back to the original exchange so the UI can link to the source
    page: ``/jobs/{job_id}`` for job exchanges, ``/library/qa`` for
    library-wide exchanges, ``/qa-history`` for prior history exchanges.
    """

    source_type: Literal["job", "library", "history"]
    exchange_id: str
    question_preview: str
    job_id: str | None = None
    original_created_at: str


class QAHistoryChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    answer_language: str = Field(default="en", min_length=2, max_length=10)


class QAHistoryChatResponse(BaseModel):
    """One history chat exchange, fresh or stored. `answer_cut_off` is present
    only on an answer that stopped at its token budget (T-1.15.4.9)."""

    id: str
    question: str
    answer: str
    references: list[QAHistoryReference]
    answer_language: str
    created_at: datetime
    answer_cut_off: StoredCutOff = None

    model_config = {"from_attributes": True}

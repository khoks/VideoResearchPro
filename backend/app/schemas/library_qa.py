from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class LibraryReference(BaseModel):
    """A citation surfaced from the global library RAG.

    Extra fields pass through: references are polymorphic by
    `source_type` (see `schemas.qa.Reference`).
    """

    model_config = {"extra": "allow"}

    video_id: str
    video_url: str
    video_title: str
    channel_name: str
    timestamp_seconds: float
    timestamp_display: str  # "12:34"
    youtube_link: str  # URL with &t= parameter


class LibraryClarifyRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class LibraryClarifyResponse(BaseModel):
    interpretation: str
    clarifications: list[str]


class LibraryQARequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    answer_language: str = Field(default="en", min_length=2, max_length=10)
    # S-1.15.2 / T-1.15.2.3: per-request depth override; None lets the
    # visible corpus's size bracket decide (D-064). Never a cap.
    output_length: Literal["auto", "brief", "standard", "deep"] | None = None


class LibraryQAResponse(BaseModel):
    id: str
    question: str
    answer: str
    references: list[LibraryReference]
    answer_language: str
    created_at: datetime

    model_config = {"from_attributes": True}

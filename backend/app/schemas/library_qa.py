from datetime import datetime

from pydantic import BaseModel, Field


class LibraryReference(BaseModel):
    """A citation surfaced from the global library RAG."""

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


class LibraryQAResponse(BaseModel):
    id: str
    question: str
    answer: str
    references: list[LibraryReference]
    answer_language: str
    created_at: datetime

    model_config = {"from_attributes": True}

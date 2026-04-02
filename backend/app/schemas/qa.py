from datetime import datetime

from pydantic import BaseModel, Field


class Reference(BaseModel):
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


class QAResponse(BaseModel):
    id: str
    question: str
    answer: str
    references: list[Reference]
    created_at: datetime

    model_config = {"from_attributes": True}

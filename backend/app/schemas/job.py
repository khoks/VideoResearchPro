from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class JobCreate(BaseModel):
    job_type: Literal["topic", "channel"]

    # Topic fields
    topic: str | None = None
    search_instructions: str | None = None
    num_videos: int = Field(default=10, ge=1, le=100)
    min_duration_minutes: int | None = Field(default=None, ge=1)
    max_duration_minutes: int | None = Field(default=None, ge=1)
    channel_type_filters: list[str] | None = None

    # Channel fields
    channel_list: list[str] | None = None
    videos_per_channel: int | None = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def validate_job_type_fields(self) -> Self:
        if self.job_type == "topic" and not self.topic:
            raise ValueError("topic is required for topic-based jobs")
        if self.job_type == "channel" and not self.channel_list:
            raise ValueError("channel_list is required for channel-based jobs")
        if self.min_duration_minutes and self.max_duration_minutes:
            if self.min_duration_minutes > self.max_duration_minutes:
                raise ValueError("min_duration_minutes must be <= max_duration_minutes")
        return self


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    topic: str | None = None
    search_instructions: str | None = None
    num_videos: int
    min_duration_minutes: int | None = None
    max_duration_minutes: int | None = None
    channel_type_filters: list[str] | None = None
    channel_list: list[str] | None = None
    videos_per_channel: int | None = None
    progress_pct: int
    progress_message: str | None = None
    error_message: str | None = None
    video_count: int = 0
    transcript_count: int = 0
    has_report: bool = False

    model_config = {"from_attributes": True}


class VideoApproval(BaseModel):
    approved_video_ids: list[str]

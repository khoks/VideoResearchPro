from datetime import datetime

from pydantic import BaseModel


class VideoResponse(BaseModel):
    id: str
    video_id: str
    title: str
    channel_name: str
    channel_id: str
    url: str
    duration_seconds: int
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    approved: bool
    transcript_status: str
    transcript_word_count: int | None = None
    transcript_language: str | None = None

    model_config = {"from_attributes": True}

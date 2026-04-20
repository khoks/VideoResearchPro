from datetime import datetime

from pydantic import BaseModel


class VideoResponse(BaseModel):
    """API response for a video.

    `id` mirrors `video_id` for backward compatibility with the pre-refactor
    shape (which carried an internal UUID). `approved` comes from the
    `JobVideo` join when the response is constructed per-job.
    """

    id: str
    video_id: str

    title: str
    channel_name: str = ""
    channel_id: str | None = None
    url: str
    duration_seconds: int
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    description: str | None = None

    approved: bool = True

    transcript_status: str
    transcript_word_count: int | None = None
    transcript_language: str | None = None
    transcript_source: str | None = None

    embedded_in_chroma: bool = False

    model_config = {"from_attributes": True}

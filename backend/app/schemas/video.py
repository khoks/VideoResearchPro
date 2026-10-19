from datetime import datetime

from pydantic import BaseModel


class VideoResponse(BaseModel):
    """API response for a video.

    `id` mirrors `video_id` for backward compatibility with the pre-refactor
    shape (which carried an internal UUID). `approved` comes from the
    `JobVideo` join when the response is constructed per-job.
    """

    id: str
    # NULL for every non-video document (PDFs, pasted pages, posts): the
    # legacy YouTube id column is only populated for ``source_type='video'``.
    video_id: str | None = None

    # Polymorphic fields (S-1.5.4). ``job_service.job_videos_response`` has
    # always built them, but the schema did not declare them, so FastAPI
    # stripped them and every approval card and citation card fell back to
    # the YouTube shape (found by S-8.8.2, 2026-10-19). Defaults keep the
    # channel route, which serialises ORM rows, unchanged.
    document_id: str | None = None
    source_type: str = "video"
    source_id: str | None = None
    source_url: str | None = None
    source_metadata: dict = {}
    classification: dict | None = None

    title: str
    channel_name: str | None = ""
    channel_id: str | None = None
    url: str | None = None
    duration_seconds: int | None = None
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

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


LibrarySort = Literal["newest", "oldest", "longest", "shortest"]


class LibraryVideoResponse(BaseModel):
    """Browse-the-global-library response.

    Mirrors `frontend/src/services/libraryApi.ts::LibraryVideoResponse`. The
    `id` field duplicates `video_id` for shape parity with other video
    endpoints. `job_count` and `job_titles` are aggregated from the `JobVideo`
    join so the UI can show "appears in N research runs" without a follow-up
    request.
    """

    id: str
    video_id: str
    title: str
    channel_id: str | None = None
    channel_name: str = ""
    url: str
    thumbnail_url: str | None = None
    duration_seconds: int
    published_at: datetime | None = None

    transcript_status: str
    transcript_language: str | None = None
    transcript_word_count: int | None = None

    job_count: int = 0
    job_titles: list[str] = []

    model_config = {"from_attributes": True}

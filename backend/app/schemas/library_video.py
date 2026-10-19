from datetime import datetime
from typing import Literal

from pydantic import BaseModel


LibrarySort = Literal["newest", "oldest", "longest", "shortest"]


class LibraryVideoResponse(BaseModel):
    """Browse-the-global-library response.

    Mirrors `frontend/src/services/libraryApi.ts::LibraryVideoResponse`.

    D-070: `id` is the document's primary key (`documents.document_id`), the
    one identifier every source type has. `video_id` is the legacy YouTube
    id and is null for PDFs, pasted pages and every other non-video source;
    `duration_seconds` is null for sources that have no duration. The
    frontend row already tolerates both (D-069) and reads `source_type` to
    pick its glyph instead of sniffing `url`.

    `job_count` and `job_titles` are aggregated from the `JobVideo` join so
    the UI can show "appears in N research runs" without a follow-up
    request.
    """

    id: str
    video_id: str | None = None
    source_type: str = "video"
    title: str
    channel_id: str | None = None
    channel_name: str = ""
    url: str
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None

    transcript_status: str
    transcript_language: str | None = None
    transcript_word_count: int | None = None

    job_count: int = 0
    job_titles: list[str] = []

    model_config = {"from_attributes": True}

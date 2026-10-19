"""Report body payload for the native reader (S-8.8.1 / E-8.8).

The legacy ``GET /jobs/{id}/report`` route keeps serving the self-contained
HTML document for "Open in new tab". The reader fetches this JSON shape
instead, under header auth only, so no token ever appears in a URL.
"""

from pydantic import BaseModel


class ChannelBreakdownRow(BaseModel):
    channel_name: str
    video_count: int | None = None
    word_count: int | None = None
    minutes: int | None = None


class ReportStatistics(BaseModel):
    video_count: int | None = None
    transcript_count: int | None = None
    total_words: int | None = None
    total_minutes: int | None = None
    channel_breakdown: list[ChannelBreakdownRow] = []


class ReportBodyResponse(BaseModel):
    job_id: str
    job_type: str
    title: str
    #: LLM-written section markup with the template chrome removed. NOT
    #: sanitised server-side — the reader runs it through DOMPurify.
    html: str
    statistics: ReportStatistics | None = None
    generated_at: str | None = None

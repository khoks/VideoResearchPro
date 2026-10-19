"""Pydantic v2 schemas for the per-video knowledge extraction API (Unit 4)."""
from datetime import datetime

from pydantic import BaseModel


class KnowledgeExtractResponse(BaseModel):
    """Response shape for POST/GET knowledge endpoints.

    Returns the four extraction lists plus the synthesized Markdown document
    and metadata about when the extraction was performed.
    """

    # NULL for non-video documents; the route also resolves by document_id.
    video_id: str | None = None
    topics: list[str]
    concepts: list[str]
    events: list[str]
    facts: list[str]
    knowledge_report_md: str
    knowledge_extracted_at: datetime | None = None

    # S-8.8.3: what the artifact is about, so the reader at
    # /knowledge/:videoId can name its source without a second request.
    document_id: str | None = None
    source_type: str = "video"
    title: str | None = None
    channel_name: str | None = None
    url: str | None = None
    published_at: datetime | None = None

    model_config = {"from_attributes": True}

"""Pydantic v2 schemas for the per-video knowledge extraction API (Unit 4)."""
from datetime import datetime

from pydantic import BaseModel


class KnowledgeExtractResponse(BaseModel):
    """Response shape for POST/GET knowledge endpoints.

    Returns the four extraction lists plus the synthesized Markdown document
    and metadata about when the extraction was performed.
    """

    video_id: str
    topics: list[str]
    concepts: list[str]
    events: list[str]
    facts: list[str]
    knowledge_report_md: str
    knowledge_extracted_at: datetime | None = None

    model_config = {"from_attributes": True}

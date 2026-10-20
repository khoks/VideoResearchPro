"""S-1.18.2: frames surfaced to the user (R1, D-067)."""
from __future__ import annotations

from pydantic import BaseModel


class FrameOut(BaseModel):
    frame_id: str
    timestamp_seconds: float
    timestamp_display: str
    description: str | None = None
    informative: bool | None = None
    status: str
    width: int | None = None
    height: int | None = None
    has_image: bool


class FramesResponse(BaseModel):
    document_id: str
    video_id: str | None = None
    # The install-wide switch (VISUAL_ENABLED). False means no new frames can
    # be captured here; stored ones are still listed and served.
    visual_enabled: bool
    # A capture this tenant (or another) started for this document is still
    # running; poll until it clears.
    in_progress: bool
    frames: list[FrameOut]


class FramesExtractResponse(BaseModel):
    status: str  # "queued"
    document_id: str

from datetime import datetime

from pydantic import BaseModel


class ChannelResponse(BaseModel):
    """Channel summary for the library/subscription UI."""

    channel_id: str
    name: str
    subscribed: bool = False
    subscriber_count: int | None = None
    uploads_playlist_id: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    video_count: int = 0

    model_config = {"from_attributes": True}


class SubscribeResponse(BaseModel):
    """Returned when a channel is subscribed or a fresh sync is dispatched."""

    channel_id: str
    job_id: str | None = None

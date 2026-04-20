from datetime import datetime

from pydantic import BaseModel


class ChannelResponse(BaseModel):
    """Skeleton response schema for a Channel.

    Unit 5 will flesh this out (subscription management endpoints). Kept
    minimal here so imports resolve and existing tests keep running.
    """

    channel_id: str
    name: str
    subscriber_count: int | None = None
    uploads_playlist_id: str | None = None
    subscribed: bool = False
    last_synced_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

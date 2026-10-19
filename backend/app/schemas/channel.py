from datetime import datetime

from pydantic import BaseModel


class ChannelResponse(BaseModel):
    """Channel summary for the library / subscription UI and the channel page.

    Shared facts (`name`, `subscriber_count`, `uploads_playlist_id`, `url`)
    come from the global `channels` row; `subscribed`, `source_weight` and
    `last_synced_at` are THIS tenant's state from `channel_subscriptions`
    (D-065). `video_count` counts only documents the tenant can see (D-063).

    `id` mirrors `channel_id` for shape parity with the other list endpoints
    (the frontend keys rows on `id`). `source_weight` is read-only here: the
    control that writes it is S-7.1.1 (`PUT /channels/{id}/weight`, D-068).
    """

    id: str
    channel_id: str
    name: str
    url: str | None = None
    subscribed: bool = False
    source_weight: float = 1.0
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

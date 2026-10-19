from datetime import datetime

from pydantic import BaseModel, Field


class ChannelResponse(BaseModel):
    """Channel summary for the library / subscription UI and the channel page.

    Shared facts (`name`, `subscriber_count`, `uploads_playlist_id`, `url`)
    come from the global `channels` row; `subscribed`, `source_weight` and
    `last_synced_at` are THIS tenant's state from `channel_subscriptions`
    (D-065). `video_count` counts only documents the tenant can see (D-063).

    `id` mirrors `channel_id` for shape parity with the other list endpoints
    (the frontend keys rows on `id`). `source_weight` is written by
    `PUT /channels/{id}/weight` (S-7.1.1) and re-ranks this tenant's job and
    library Q&A retrieval as `distance / weight` after the relevance
    threshold (D-068).
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


class ChannelWeightRequest(BaseModel):
    """Body of `PUT /channels/{id}/weight` (D-068). 1.0 is neutral; 0.0 sinks
    the channel to the bottom of retrieval without excluding it."""

    weight: float = Field(ge=0.0, le=2.0)


class SubscribeResponse(BaseModel):
    """Returned when a channel is subscribed or a fresh sync is dispatched."""

    channel_id: str
    job_id: str | None = None

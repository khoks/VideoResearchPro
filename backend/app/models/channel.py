from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Channel(Base):
    """Global (single-tenant) source-creator record.

    Today the table holds YouTube channels exclusively. The L1 multi-source
    columns (`source_type`, `creator_external_id`, `source_weight`,
    `creator_metadata_json`) are populated for every row so future creators
    (podcast shows, blog domains, X authors, …) can land here without
    another migration. See `docs/source-types.md`.
    """

    __tablename__ = "channels"

    channel_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subscribed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # L1 multi-source: the discriminator + per-source-type external id.
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="video", server_default="video"
    )
    creator_external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # User-set trust score that drives retrieval re-ranking (L4). 1.0 is
    # neutral; higher values promote, lower values demote.
    source_weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    creator_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("source_type", "video")
        if "creator_external_id" not in kwargs and "channel_id" in kwargs:
            kwargs["creator_external_id"] = kwargs["channel_id"]
        super().__init__(**kwargs)

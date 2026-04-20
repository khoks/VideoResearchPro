from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


from app.database import Base


class Channel(Base):
    """Global (single-tenant) YouTube channel record.

    Shared across jobs; the `subscribed` flag supports the subscription ingest mode
    introduced in the global-library refactor. `last_synced_at` records the most
    recent time the channel's uploads playlist was polled.
    """

    __tablename__ = "channels"

    channel_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subscribed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

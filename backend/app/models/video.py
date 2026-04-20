from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Video(Base):
    """Global (single-tenant) YouTube video record.

    The primary key is the YouTube `video_id` so the video library is
    deduplicated across jobs. Channel metadata lives on the `Channel` model
    reachable through `channel_id`. The per-job association lives in
    `JobVideo`.
    """

    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_channel_id", "channel_id"),
    )

    video_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("channels.channel_id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(200))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Transcript state
    transcript_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    transcript_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    transcript_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transcripted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # RAG state
    embedded_in_chroma: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    channel: Mapped["Channel | None"] = relationship("Channel", lazy="joined")  # noqa: F821

    @property
    def channel_name(self) -> str:
        """Backward-compatible accessor; pre-refactor code reads `video.channel_name`."""
        return self.channel.name if self.channel is not None else ""

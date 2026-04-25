from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Video(Base):
    """Global (single-tenant) source-document record.

    Today the table is populated entirely by the YouTube ingest path so the
    primary key remains the YouTube `video_id` and the table name is still
    `videos`. The L1 multi-source columns (`source_type`, `source_id`,
    `source_url`, …) coexist with the legacy YouTube columns; non-video
    sources will land in this same table in subsequent PRs without another
    migration. See `docs/source-types.md`.
    """

    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_channel_id", "channel_id"),
        Index(
            "ix_videos_source_type_source_id",
            "source_type",
            "source_id",
            unique=True,
        ),
    )

    video_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("channels.channel_id", ondelete="SET NULL"), nullable=True
    )

    # L1 multi-source discriminator. Defaults to "video" so every existing
    # row continues to round-trip the YouTube path unchanged.
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="video", server_default="video"
    )
    # External identity within `source_type`. For YouTube this mirrors
    # `video_id`; for podcasts it'd be the episode GUID, for articles a
    # canonical URL hash, etc. Unique per `source_type`.
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(200))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Nullable for non-video sources (articles, threads) which have no duration.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    # Knowledge extraction artifacts (Unit 4)
    # `extracted_knowledge_json` holds the structured merged extraction as a
    # JSON-encoded string: {"topics": [...], "concepts": [...], "events": [...], "facts": [...]}
    # `knowledge_report_md` is the synthesized Markdown knowledge document.
    # `knowledge_extracted_at` is set once the agent has completed successfully.
    extracted_knowledge_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_report_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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

    def __init__(self, **kwargs: Any) -> None:
        # YouTube callers don't know about `source_id` yet; default it to
        # the YouTube video_id so legacy ingest call sites stay unchanged.
        kwargs.setdefault("source_type", "video")
        if "source_id" not in kwargs and "video_id" in kwargs:
            kwargs["source_id"] = kwargs["video_id"]
        if "source_url" not in kwargs and "url" in kwargs:
            kwargs["source_url"] = kwargs["url"]
        super().__init__(**kwargs)

    @property
    def channel_name(self) -> str:
        """Backward-compatible accessor; pre-refactor code reads `video.channel_name`."""
        return self.channel.name if self.channel is not None else ""

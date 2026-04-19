import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_job_id", "job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"))

    video_id: Mapped[str] = mapped_column(String(20))  # YouTube video ID
    title: Mapped[str] = mapped_column(String(500))
    channel_name: Mapped[str] = mapped_column(String(200))
    channel_id: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(200))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Approval
    approved: Mapped[bool] = mapped_column(Boolean, default=True)

    # Transcript
    transcript_status: Mapped[str] = mapped_column(String(20), default="pending")
    transcript_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    job: Mapped["Job"] = relationship(back_populates="videos")  # noqa: F821

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type: Mapped[str] = mapped_column(String(20))  # "topic" | "channel"
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Topic-based fields
    topic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    search_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    num_videos: Mapped[int] = mapped_column(Integer, default=10)
    min_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_type_filters: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # Channel-based fields
    channel_list: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    videos_per_channel: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Search metadata
    search_queries_used: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # Results
    chroma_collection_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Progress tracking
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Celery
    celery_task_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    videos: Mapped[list["Video"]] = relationship(  # noqa: F821
        back_populates="job", cascade="all, delete-orphan"
    )
    qa_exchanges: Mapped[list["QAExchange"]] = relationship(  # noqa: F821
        back_populates="job", cascade="all, delete-orphan"
    )

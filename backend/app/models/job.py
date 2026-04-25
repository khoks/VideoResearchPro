import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type: Mapped[str] = mapped_column(String(20))  # "topic" | "channel" | "subscription"
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
    # Topic-job only: JSON array of user-supplied channel hints (URLs/handles/UC-IDs).
    # Resolved to channel_ids by the Search Agent and used to walk each channel's
    # uploads playlist alongside broad topic searches.
    preferred_channels: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # Channel-based fields
    channel_list: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    videos_per_channel: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Search metadata
    search_queries_used: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # Subscription-job metadata: JSON array of {channel_id, name} for resolved channels
    channel_list_resolved: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    # Documents are a globally deduplicated library (one `documents` row
    # per source — YouTube video today, podcasts/articles/etc. soon).
    # The `job_videos` join carries per-job approval/audit state.
    # The attribute name `videos` is preserved for back-compat so existing
    # callers (`job.videos`) keep working; the join target is the renamed
    # `Document` model.
    videos: Mapped[list["Document"]] = relationship(  # noqa: F821
        "Document",
        secondary="job_videos",
        viewonly=True,
        lazy="select",
    )
    job_videos: Mapped[list["JobVideo"]] = relationship(  # noqa: F821
        "JobVideo",
        cascade="all, delete-orphan",
        lazy="select",
    )
    qa_exchanges: Mapped[list["QAExchange"]] = relationship(  # noqa: F821
        back_populates="job", cascade="all, delete-orphan"
    )

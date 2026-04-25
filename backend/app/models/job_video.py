from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column


from app.database import Base


class JobVideo(Base):
    """Join table associating Jobs to Documents (the global deduplicated library).

    A given source document may appear in many jobs; each row captures
    the per-job approval state and audit fields (`curated_at`,
    `selection_reason`). Use the composite `(job_id, video_id)` primary
    key to de-dupe within a single job.

    The column is still named `video_id` for back-compat — see the
    `Document.video_id` docstring for why the column rename is deferred.
    """

    __tablename__ = "job_videos"
    __table_args__ = (
        Index("ix_job_videos_job_id", "job_id"),
        Index("ix_job_videos_video_id", "video_id"),
    )

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    video_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("documents.video_id", ondelete="CASCADE"), primary_key=True
    )

    approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    curated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

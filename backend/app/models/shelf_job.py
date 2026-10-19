"""`shelf_jobs` — membership of a job on a shelf (E-8.1 / S-8.1.1).

Composite primary key `(shelf_id, job_id)`: a job is on a shelf once. Both
sides cascade in the ORM — `Shelf.shelf_jobs` and `Job.shelf_jobs` — so
deleting either parent removes the row and nothing else. The `ondelete`
clauses document the intent for databases that enforce them; SQLite here
does not (no `PRAGMA foreign_keys`), which is why the ORM owns the cascade.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ShelfJob(Base):
    __tablename__ = "shelf_jobs"
    __table_args__ = (Index("ix_shelf_jobs_job_id", "job_id"),)

    shelf_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shelves.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    shelf: Mapped["Shelf"] = relationship("Shelf", back_populates="shelf_jobs")  # noqa: F821
    job: Mapped["Job"] = relationship("Job", back_populates="shelf_jobs")  # noqa: F821

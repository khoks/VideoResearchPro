"""Search candidate pool per job — S-1.14.6.

Why this exists: ``rank_and_curate`` discards the videos it rejects. When
D-055 tried to measure selection quality on a real 200-video job, a true
re-rank was impossible because the ~217 rejected candidates had never been
stored — the evaluation had to fall back to auditing the 200 picks against
the stated criteria (which graded 6.5/10).

Persisting the whole pool with a ``selected`` flag makes selection quality
measurable the same way every other stage is: replay the ranking decision
against a different model or prompt and compare against what shipped.

Kept deliberately separate from ``job_documents``: a rejected candidate was
never ingested, has no transcript, and must not create a row in the global
``documents`` library.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobSearchCandidate(Base):
    __tablename__ = "job_search_candidates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # External source id (YouTube video id today; source-agnostic string so
    # the same table serves future connectors).
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    channel_name: Mapped[str | None] = mapped_column(String(255))
    channel_id: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[str | None] = mapped_column(String(64))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # The outcome of ranking: did this candidate make the cut?
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Full candidate dict as discovered, so a replay has everything the
    # ranker saw even if columns above drift.
    payload_json: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_job_search_candidates_job_selected", "job_id", "selected"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        mark = "+" if self.selected else "-"
        return f"<JobSearchCandidate {mark}{self.video_id} job={self.job_id[:8]}>"

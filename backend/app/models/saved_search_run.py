"""saved_search_runs — one row per run of a saved search (S-8.3.3 / M3).

The history behind a saved search: what each run did (or why it did not
run), the signals the change detector computed, whether it called the
judge, and what changed. ``exchange_id`` is the library Q&A exchange the run
produced; ``previous_exchange_id`` is the baseline it was compared with, so
a diff view can show the two answers side by side.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SavedSearchRun(Base):
    __tablename__ = "saved_search_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    saved_search_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("saved_searches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive, index=True)
    #: ``schedule`` (the tick) or ``manual`` (Run now).
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")
    #: saved_search_service status: ok, no_new_sources, failed, quota_exceeded, …
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    exchange_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_exchange_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: Null on the first run (it sets the baseline) and on runs that did not answer.
    changed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    jaccard: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: none | agreed | judged | judge_failed
    decided_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    added_reference_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dropped_reference_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

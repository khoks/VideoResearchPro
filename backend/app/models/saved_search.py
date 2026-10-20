"""saved_searches — a pinned library question re-asked on a schedule (S-8.3.2 / M3).

Plan: docs/plans/m3-saved-searches-alerts.md. The schedule itself lives in
``scheduled_runs`` (one row of kind ``saved_search`` per saved search, keyed
by this row's id), so the cadence and ``next_run_at`` have one home; this
table holds what is asked, over which scope, and what the last run found.

``scope_json`` is NULL for the whole library, or ``{"shelf_id": …}`` for a
shelf (the shape shelf-scoped Q&A, S-8.1.4, uses for its exchanges).

The ``last_*`` columns are the comparison baseline the change detector
(S-8.3.3) reads: the cited document set, a hash of the answer text and the
answer's embedding. A failed run never touches them, so the previous result
stays intact.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    scope_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive, onupdate=_utcnow_naive)

    # What the last run did. `last_status` is one of saved_search_service.STATUSES.
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The last successful answer: the baseline the next run is compared with.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_exchange_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_answer_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_reference_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_answer_embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: S-8.3.3: sha256 of the sorted document ids the last good run could
    #: cite. A scheduled run whose scope still resolves to the same set is
    #: skipped before the quota or the model (the gate).
    last_scope_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

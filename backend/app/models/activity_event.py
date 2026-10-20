"""ActivityEvent — one thing the user did, from a connector (Domain 2, S-3.2.1).

A commit pushed, a video liked, a calendar event attended, an item shared to
Pratidhvani. Connectors (``app/connectors/<name>/``) and importers write rows;
nothing else does. Rows are per tenant and part of Echo's brain
(``echo_privacy_service.ECHO_TABLES``): exported whole, erased with the brain,
and deleted with their connector when the user revokes it.

**Idempotent by construction.** ``(tenant_id, connector, external_id)`` is
unique: a re-sync, a retried task or an overlapping backfill rewrites the same
row instead of adding a second. ``external_id`` is the provider's id for the
event (GitHub's event id, a commit SHA) or a stable synthetic one
(``share:<id>`` for the ``internal`` connector). The tenant is part of the key
because two readers may connect the same third-party account.

``occurred_at`` is when it happened (UTC), ``ingested_at`` when we stored it.
``payload_json`` is the connector's structured record; ``text_content`` is the
user's own words when the event carries any (commit messages, PR
descriptions) and is what voice signals (E-3.3) will read. ``embedding_id`` is
reserved for when events are embedded; nothing embeds them yet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector", "external_id", name="uq_activity_events_external"),
        Index("ix_activity_events_user_connector_time", "user_id", "connector", "occurred_at"),
        Index("ix_activity_events_tenant_time", "tenant_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    connector: Mapped[str] = mapped_column(String(48), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

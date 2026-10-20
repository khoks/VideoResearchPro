"""EchoCardState — what the Echo panel's anticipation cards have shown, and
what the user did with them (S-3.8.2).

The frequency cap and the dismissal rule were pre-registered before any card
existed (docs/notes/2026-10-20-anticipation-cards-preregistration.md). One
row per (tenant, key):

- a card: ``saved_search:<notification id>``, ``shares:<share id>`` or
  ``questions:<context>``. ``shown_days`` counts distinct UTC days it was
  shown (capped at three), ``dismissed_at`` and ``acted_at`` retire it;
- ``mute:<kind>``: the kind is off while ``dismissed_at`` is set;
- ``seen:shares``: ``acted_at`` is when the user last opened the shares inbox.

Registered in ``echo_privacy_service.ECHO_TABLES`` (D-089): exported and erased
with the brain. These rows are also the data the pre-registered reading after
30 days is computed from.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EchoCardState(Base):
    __tablename__ = "echo_card_state"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_echo_card_state_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    shown_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_shown_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

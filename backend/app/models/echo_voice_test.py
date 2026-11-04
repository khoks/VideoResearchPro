"""echo_voice_tests — the in-app "which of these did you write?" test (T-3.4.1.8).

One row per test a user takes on the Echo page: the blinded pairs Echo wrote
for them (tier iii of D-100, built exactly as ``scripts/voice_match_harness.py
user-pairs`` builds them), the picks they made, and the score. Scoring writes
``echo_voice_gates`` as the harness's ``user-score --record`` does; that row,
not this one, is the switch "speak as me" reads.

``key_json`` says which side of each pair is the user's own note. It never
leaves the server through the API, before or after scoring.

Part of the brain (``echo_privacy_service.ECHO_TABLES``): it holds copies of
the user's notes and drafts in their voice, so it is exported whole and
erased with the brain.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EchoVoiceTest(Base):
    __tablename__ = "echo_voice_tests"
    __table_args__ = (Index("ix_echo_voice_tests_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: generating | ready | scored | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Which notes are held out and the order of each pair. Random per test;
    #: the harness uses its fixed seed.
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    pairs_total: Mapped[int] = mapped_column(Integer, nullable=False)
    pairs_built: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: [{pair, A, B}]: what the user is shown.
    pairs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: [{pair, own_is, note_id, topic}]: never sent to the client.
    key_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: {pair: "A" | "B"}
    picks_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    picked_own: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Why generation failed, in words for the user.
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

"""echo_voice_tests — the in-app "which of these did you write?" test (T-3.4.1.8).

One row per test a user takes on the Echo page: the blinded pairs Echo wrote
for them (tier iii of D-100, built exactly as ``scripts/voice_match_harness.py
user-pairs`` builds them), the picks they made, and the score. Scoring writes
``echo_voice_gates`` as the harness's ``user-score --record`` does; that row,
not this one, is the switch "speak as me" reads.

``key_json`` says which side of each pair is the user's own note. The test's
routes never send it, before or after scoring.

Part of the brain (``echo_privacy_service.ECHO_TABLES``): it holds copies of
the user's notes and drafts in their voice, so it is erased with the brain
and exported with it. An export keeps ``key_json`` and ``seed`` back while a
test is open (``echo_privacy_service.withheld_columns``): the seed fixes the
held-out sample and every coin flip, so it would rebuild the key. Once a test
is scored both are the user's copy like every other column.

At most one test per tenant is open (``OPEN_STATUSES``). The partial unique
index holds that, so two requests that both pass the check in
``echo_voice_test_service.start`` still make one test.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: A test still being written or taken. Spelled out in the index below and
#: in migration 6d5b3d5aa6fa.
OPEN_STATUSES = ("generating", "ready")
_OPEN = text("status IN ('generating', 'ready')")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EchoVoiceTest(Base):
    __tablename__ = "echo_voice_tests"
    __table_args__ = (
        Index("ix_echo_voice_tests_tenant_created", "tenant_id", "created_at"),
        Index("uq_echo_voice_tests_one_open", "tenant_id", unique=True, sqlite_where=_OPEN, postgresql_where=_OPEN),
    )

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
    #: The ``echo_draft`` model: the user's pin if they have one, which
    #: ``user_llm_overrides`` allows 128 characters.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Why generation failed, in words for the user.
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    #: The worker's last sign of life while ``generating``: when it picked the
    #: test up, then each finished pair. Staleness runs from this, else
    #: from ``created_at``.
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

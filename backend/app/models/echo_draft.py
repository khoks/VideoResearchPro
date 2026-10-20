"""echo_drafts and echo_voice_gates — "speak as me" (S-3.4.1 / E-3.4).

``echo_drafts``: every draft Echo wrote for the user: the incoming message,
the draft, what grounded it (citations), how close to the user's voice the
critic judged it, and what deviated. Drafts are never sent; S-3.4.2 records
the user's edited ``final_text`` as feedback.

``echo_voice_gates``: the per-user switch D-100 requires. "Speak as me"
works for a user only once they passed the blinded "which of these did you
write?" test (tier iii, pre-registered in
docs/notes/2026-10-19-voice-match-preregistration.md): at least 20 pairs,
their own text picked in at most 80% of them. One row per tenant, written by
``scripts/voice_match_harness.py user-score --record``.

Both are part of the brain (``echo_privacy_service.ECHO_TABLES``): exported
whole, erased with it. Deleting the brain resets the gate, so the test must
be passed again.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EchoDraft(Base):
    __tablename__ = "echo_drafts"
    __table_args__ = (Index("ix_echo_drafts_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: The message the user is replying to. It may hold other people's words;
    #: it is the user's own record, exported with the brain and never a voice input.
    input_message: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str | None] = mapped_column(String(200), nullable=True)
    register: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft: Mapped[str] = mapped_column(Text, nullable=False)
    voice_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    deviation_notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    flags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    critique_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disclosure: Mapped[str] = mapped_column(String(300), nullable=False)
    #: S-3.4.2: what the user finally sent, and whether the disclosure stayed.
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclosure_kept: Mapped[bool | None] = mapped_column(nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class EchoVoiceGate(Base):
    __tablename__ = "echo_voice_gates"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_echo_voice_gates_tenant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: passed | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    pairs: Mapped[int] = mapped_column(Integer, nullable=False)
    picked_own_share: Mapped[float] = mapped_column(Float, nullable=False)
    #: The pre-registration the rule came from.
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

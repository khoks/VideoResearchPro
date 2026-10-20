"""voice_signal_inputs — which of the user's own texts signal extraction has read (S-3.3.2).

One row per input (``note:<id>``, ``share:<id>``, ``qa:<id>``,
``library_qa:<id>``, ``history_qa:<id>``) with the hash of the text it read,
so an edited note is read again and a deleted one is withdrawn from every
signal it fed. ``features_json`` keeps the input's stylometric profile, so
the per-language style profile is a sum over rows, not a re-read of every
note.

Part of the brain: registered in ``echo_privacy_service.ECHO_TABLES``, so the
whole-brain export carries it and the brain delete removes it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VoiceSignalInput(Base):
    __tablename__ = "voice_signal_inputs"
    __table_args__ = (UniqueConstraint("tenant_id", "source_ref", name="uq_voice_signal_inputs_ref"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    #: note | question | share
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: SHA-256 of the text as read.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: en | hi-Deva | hi-Latn | mixed
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: False until the LLM pass has read this version (a failed or skipped
    #: call leaves it pending; stylometry does not need the LLM).
    llm_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

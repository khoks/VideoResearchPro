"""voice_signals — how the user writes and thinks, as rows (S-3.3.1 / E-3.3).

Plan: docs/plans/l3-echo-personal-brain.md (Domain 3); shape from
docs/personal-brain.md. Signals are inspectable, editable, exportable and
revocable rows, never a prompt blob. Each carries up to five verbatim
examples from the user's OWN words (D-089 item 1: context-only shares never
feed signals) and the provenance it was learned from.

``language`` and ``register`` exist because bilingual users measurably shift
voice per language and audience, so exemplars are bucketed by both.

**Tombstones.** "That's not me" sets ``suppressed_at`` (reason ``user``); the
row stays so a later extraction that finds the same ``(signal_type,
value_key, language)`` sees it and does not bring it back. A signal whose
every source was deleted is suppressed with reason ``source_deleted``: the
user withdrew the evidence, not the signal, so new evidence may re-derive it.

Registered in ``echo_privacy_service.ECHO_TABLES`` (D-089 item 2), so the
whole-brain export carries it and the brain delete removes it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VoiceSignal(Base):
    __tablename__ = "voice_signals"
    __table_args__ = (
        Index("ix_voice_signals_tenant_type", "tenant_id", "signal_type"),
        Index("ix_voice_signals_merge_key", "tenant_id", "signal_type", "value_key", "language"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: echo_signal_service.SIGNAL_TYPES (style and personality layers).
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    #: Normalised ``value`` (casefold, collapsed spaces): the merge and tombstone key.
    value_key: Mapped[str] = mapped_column(String(300), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: Up to five ``{text, source, at}`` verbatim examples.
    examples_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: en | hi-Deva | hi-Latn | mixed; null = not language-specific.
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: intimate | casual | professional | public; null = any.
    register: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: JSON list of provenance refs: ``note:<id>``, ``share:<id>``, ``qa:<id>``, ``user``.
    derived_from: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: user (typed on the panel) | llm (S-3.3.2 extraction) | stylometry (S-3.3.2 baseline).
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    #: The consent text version the user had accepted when this was learned.
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: user ("that's not me") | source_deleted (every source withdrawn).
    suppressed_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

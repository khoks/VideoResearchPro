"""Note model — M5 / E-8.5, the user's own voice in the library.

A note is free-text Markdown the user attaches to something they can see:
a document, a job, one of their Q&A exchanges, a channel, or a knowledge
artifact. Notes are the first text in the system written BY the user rather
than ingested FOR them, which is why Echo's voice capture (E-3.3) ranks them
as its richest input and why this table keeps authorship and timestamps
exact and never hard-deletes.

Shape follows the W3C Web Annotation Data Model loosely:

- ``target_type`` + ``target_id`` name the annotated thing. The type set is
  closed (``note_service.TARGET_TYPES``) because the closed set is what makes
  the existence check through visibility and ownership possible.
- ``selector_json`` is optional and, when present, a ``TextQuoteSelector``
  (``exact`` / ``prefix`` / ``suffix``) plus ``start_seconds`` so a note can
  anchor to a transcript span and carry a ``&t=`` link like a Q&A citation.
- ``motivation`` is one of ``commenting`` / ``highlighting`` / ``tagging``.
- ``deleted_at`` is a soft delete: the row stays so exports can carry
  deletions and Echo never loses a signal the user wrote and then withdrew.

Notes are strictly per tenant. D-063 visibility applies to the TARGET at
write time (you cannot annotate what you cannot see); the note itself is
read only through ``tenant_id``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_tenant_target", "tenant_id", "target_type", "target_id"),
        Index("ix_notes_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Closed set, validated in note_service. See TARGET_TYPES there.
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Canonical id of the target: ``documents.document_id`` for documents and
    # knowledge artifacts, ``jobs.id``, the exchange's id, or
    # ``channels.channel_id`` (50 chars). The service canonicalises a legacy
    # YouTube ``video_id`` to the document UUID before writing, so one
    # document has one note stream however it was addressed.
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional W3C-shaped selector, JSON text. See note_service.Selector.
    selector_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    motivation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="commenting", server_default="commenting"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Note {self.id[:8]} {self.target_type}:{self.target_id[:12]}>"

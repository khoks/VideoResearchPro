"""Share — one item in Echo's shares inbox (Domain 5, S-3.7.1).

The user forwards things all day — a link, a quote, a screenshot, a voice
memo — with no approval step, because the act of sharing is the curation
(`personal-brain.md` § Domain 5). Every surface (quick-share today; drag-drop,
the browser extension, email-in and the OS share target later) writes one row
here. Processing (OCR, Whisper, embedding, signal extraction) is S-3.7.2; a
row written today is `pending` unless it needed no processing.

**Third-party content is context-only by default.** ``author_is_tenant`` is
False unless the user says the words are their own. A context-only share may
be retrieved as context once S-3.7.2 embeds it, but is never quoted verbatim in
generated output and never enters a dataset or derived export. The full Echo
archive (S-3.10.1) is the exception: it is the user's own lossless copy of what
they handed over.

Files live under ``ECHO_SHARES_DIR/<tenant>/``; ``file_path`` is relative to
``ECHO_SHARES_DIR`` so the install can move.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Share(Base):
    __tablename__ = "shares_inbox"
    __table_args__ = (
        Index("ix_shares_inbox_tenant_received", "tenant_id", "received_at"),
        Index("ix_shares_inbox_tenant_state", "tenant_id", "processing_state"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    # os_share | browser_ext | email_in | drag_drop | manual_quick_share
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    # Open-ended (`personal-brain.md`): youtube_video, link, text_snippet,
    # image, voice_memo, ... Inferred at intake; the user may correct it.
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # What arrived, as JSON text: {"kind": "url"|"text"|"file", ...}.
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # False = third-party words, context-only (see module docstring).
    author_is_tenant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # pending | processed | skipped | failed
    processing_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    # Back-links written by later stories; a share delete cascades to them.
    derived_fact_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    derived_signal_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # S-3.7.2: what processing made of the share, as JSON text: resolved
    # title / author, the extraction path, the failure reason, the library
    # offer, `processed_at`. NULL = not processed yet. `raw_payload_json`
    # never changes; this does.
    processing_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Share {self.id[:8]} {self.content_type} {self.processing_state}>"

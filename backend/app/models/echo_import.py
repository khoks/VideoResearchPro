"""EchoImport — one export file the user imported into Echo (S-3.7.5).

An import turns a file from another service (a WhatsApp chat, a Google
Takeout archive) into many shares at once. This row records what was
imported, with which options and what came of it, so the user can see their
imports and undo one: deleting an import deletes every share it wrote
(``shares_inbox.import_id``) and their vectors.

The upload itself is never kept. Parsing streams it, and only what the
options allow is stored: with "redact the other party", the other side of a
WhatsApp thread never reaches the database.

Registered in ``echo_privacy_service.ECHO_TABLES`` (D-089): exported with the
brain and deleted with it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EchoImport(Base):
    __tablename__ = "echo_imports"
    __table_args__ = (Index("ix_echo_imports_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Registry name: whatsapp | google_keep | ...
    importer: Mapped[str] = mapped_column(String(32), nullable=False)
    # The client's filename, for the user's own list. Never a path.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # importing | embedding | done | failed | deleting
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="importing")
    # The options the import ran with (self_name, redact_other_party, ...).
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What came of it: shares, own_words, context_only, embedded, and what
    # the importer deliberately left out (redacted, skipped).
    counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The preview's summary (chat name, date range, ...).
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EchoImport {self.id[:8]} {self.importer} {self.status}>"

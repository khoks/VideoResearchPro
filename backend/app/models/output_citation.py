"""output_citations — every source an Author Studio output cites (S-6.7.3 / E-6.7).

One row per citation in output order (`position` is 1-based). Every
outputter writes them through `output_citation_service.record_citations`, so
a book, a deck and a site all cite the same way, and endnotes (S-6.1.4), a
sources slide (S-6.3.1) or a site's backlinks read one table.

`url` is the link a reader can follow: the citation's own absolute URL, or
one rebuilt from the resolved source and timestamp when the report wrote a
bare `&t=123` anchor (reports before S-1.14.9). `resolved_by` records how the
source was found (`video_id`, `url`, `title`, `channel`) and is NULL when no
library document matched. An unmatched absolute link keeps its own URL; an
unmatched bare anchor gets none. An unresolved citation is recorded, never
invented.

`document_id` is a plain column, not a foreign key: SQLite in this app does
not enforce foreign keys, and a citation must outlive nothing it refers to.
Rows are deleted with their output by `output_service.delete_output`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OutputCitation(Base):
    __tablename__ = "output_citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    output_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("outputs.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (Index("ix_output_citations_output_position", "output_id", "position"),)

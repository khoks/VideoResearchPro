"""Per-tenant visibility over the shared document cache — S-5.7.1 / D-063.

The decision (2026-07-31): **shared cache, private catalogue**. `documents`
stays the global deduplicated store — that is what makes transcripts,
embeddings and knowledge artifacts compute-once-reuse-forever — but no user
sees a document they did not themselves ingest.

Ownership cannot be derived from `job_documents` alone. Three ingest paths
create documents with no job at all:

* `upload_pdf`  (library.py) — a user's own PDF would become invisible
* `paste_urls`  (library.py)
* channel subscription sync

So visibility is recorded EXPLICITLY at every ingest point rather than
inferred. `source` records which path claimed it, which is what makes the
backfill auditable and future ingest paths obvious when they are missed.

One row per (document, tenant): two users ingesting the same video share the
cached transcript and embeddings but each hold their own visibility grant, and
neither can see that the other has one.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocumentVisibility(Base):
    __tablename__ = "document_visibility"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # The shared-cache row this grant refers to. Legacy PK column name.
    video_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.video_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # Which ingest path granted this: job | pdf_upload | paste_url | channel_sync
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="job")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("video_id", "tenant_id", name="uq_document_visibility"),
        Index("ix_document_visibility_tenant_video", "tenant_id", "video_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<DocumentVisibility {self.video_id} -> {self.tenant_id[:8]} ({self.source})>"

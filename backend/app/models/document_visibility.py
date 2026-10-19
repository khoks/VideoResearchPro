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

D-070 (2026-10-19): the grant references ``documents.document_id``, the real
primary key. Until then it referenced the legacy ``documents.video_id``, which
is NULL for every non-video source, so PDFs and pasted pages were ingested
but granted to nobody. Migration ``d8e9f0a1b2c3`` re-keyed the table.
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
    # The shared-cache row this grant refers to — the canonical PK, never
    # the legacy YouTube id (D-070).
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "documents.document_id",
            ondelete="CASCADE",
            name="fk_document_visibility_document_id",
        ),
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
        UniqueConstraint("document_id", "tenant_id", name="uq_document_visibility"),
        Index("ix_document_visibility_tenant_document", "tenant_id", "document_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<DocumentVisibility {self.document_id} -> {self.tenant_id[:8]} ({self.source})>"
        )

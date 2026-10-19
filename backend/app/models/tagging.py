"""`taggings` — one tag applied to one target (E-8.1 / S-8.1.3).

Polymorphic on `(target_type, target_id)` so jobs and channels can be tagged
later without a new table; v1 accepts only `document` (`target_id` =
`documents.document_id`, D-070). `tenant_id` is denormalised from the tag so
every read can filter without a join. Deleting a tag removes its taggings
through the ORM cascade on `Tag.taggings` (SQLite here never enforces the FK
cascade).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

TARGET_DOCUMENT = "document"
TARGET_TYPES = (TARGET_DOCUMENT,)


class Tagging(Base):
    __tablename__ = "taggings"
    __table_args__ = (
        UniqueConstraint("tag_id", "target_type", "target_id", name="uq_taggings_tag_target"),
        Index("ix_taggings_tenant_target", "tenant_id", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tag_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    tag: Mapped["Tag"] = relationship("Tag", back_populates="taggings")  # noqa: F821

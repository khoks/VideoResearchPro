"""Tags — per-tenant labels applied to documents (E-8.1 / M1, S-8.1.3).

Rows, not free strings (`docs/plans/m1-shelves.md`): a tag has a stable id
that survives rename (Notion keeps a `select` option's id when renamed), so
rename and merge are single updates and counts and colours are first-class.

Per tenant because `documents` is a shared cache (D-063): a tag is private to
the reader who made it, and another reader tagging the same shared document
never shows up here. The name is unique per tenant case-insensitively through
a functional index on `lower(name)`; the service checks first so a collision
is a clean 409 rather than an IntegrityError.

`color` is one of the ten label-palette NAMES in `theme.ts` (shared with
shelves), never a hex.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(
        String(20), nullable=False, default="default", server_default="default"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    taggings: Mapped[list["Tagging"]] = relationship(  # noqa: F821
        "Tagging",
        back_populates="tag",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Tag {self.name!r} tenant={self.tenant_id[:8]}>"


Index("uq_tags_tenant_lower_name", Tag.tenant_id, func.lower(Tag.name), unique=True)

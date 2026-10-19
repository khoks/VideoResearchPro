"""Shelves — named, per-tenant collections of jobs (E-8.1 / M1, S-8.1.1).

A shelf groups research runs into a project ("macroeconomics", "the book on
Kashmir"). Zotero semantics, decided in `docs/plans/m1-shelves.md`:

* a job may sit on several shelves (`shelf_jobs` is many-to-many);
* deleting a shelf never deletes its jobs, only the membership rows;
* deleting a job removes it from every shelf (ORM cascade from `Job`,
  because SQLite does not enforce `ON DELETE CASCADE` without a pragma this
  app never sets);
* no nesting in v1.

Shelves carry `tenant_id` from the start: every lookup includes it and a
foreign id is a 404 (the existence-leak posture every router already uses).
The name is unique per tenant case-insensitively — the service enforces the
case-insensitive half, the constraint is the exact-match backstop.

`color` is the NAME of one of the ten palette tokens that `theme.ts` will
define (the plan's "never a hex, never colour alone" rule), validated in
the schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Shelf(Base):
    __tablename__ = "shelves"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(
        String(20), nullable=False, default="default", server_default="default"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    shelf_jobs: Mapped[list["ShelfJob"]] = relationship(  # noqa: F821
        "ShelfJob",
        back_populates="shelf",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_shelves_tenant_name"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Shelf {self.name!r} tenant={self.tenant_id[:8]}>"

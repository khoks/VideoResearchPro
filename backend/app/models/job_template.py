"""Job templates — named, reusable research recipes (E-8.6 / M6, S-8.6.1).

Two tables, the Grafana model the M6 plan chose:

* ``job_templates`` is the template's identity and its mutable metadata
  (name, description). ``tenant_id`` is NULL for built-ins (S-8.6.2), which
  carry a stable ``builtin_key`` and are read-only. A delete is soft
  (``deleted_at``) so a job that ran "with template X v3" still resolves.
* ``job_template_versions`` holds the frozen parameters, one immutable row per
  saved change, numbered from 1. ``jobs.template_id`` + ``jobs.template_version``
  record provenance, so "re-run with the template as it was" works.

The plan sketched one table with ``is_latest``; splitting identity from
versions keeps the id stable across a rename (the single-table form keyed
identity on the name) without changing any behaviour the plan describes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobTemplate(Base):
    __tablename__ = "job_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # NULL = a built-in shared by every reader (S-8.6.2).
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    builtin_key: Mapped[str | None] = mapped_column(String(60), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    versions: Mapped[list["JobTemplateVersion"]] = relationship(
        "JobTemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="JobTemplateVersion.version.desc()",
        lazy="select",
    )

    @property
    def is_builtin(self) -> bool:
        return self.tenant_id is None


class JobTemplateVersion(Base):
    __tablename__ = "job_template_versions"

    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_templates.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    template: Mapped[JobTemplate] = relationship("JobTemplate", back_populates="versions")

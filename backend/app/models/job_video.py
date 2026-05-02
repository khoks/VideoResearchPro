from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column


from app.database import Base


class JobVideo(Base):
    """Join table associating Jobs to Documents (the global deduplicated library).

    Renamed at the table level to ``job_documents`` per E-1.10 cutover
    (D-017); the Python class name stays ``JobVideo`` for now since
    most reader code still imports ``JobVideo`` and the rename of the
    Python identifier is a low-priority cosmetic follow-up. SQLAlchemy
    maps the class to the renamed table via ``__tablename__``.

    A given source document may appear in many jobs; each row captures
    the per-job approval state and audit fields (``curated_at``,
    ``selection_reason``). Use the composite ``(job_id, document_id)``
    primary key to de-dupe within a single job.

    Per E-1.10:

    * ``document_id`` (UUID, FK → ``documents.document_id``) is the
      canonical join column and replaces the legacy ``video_id`` PK
      from earlier schemas.
    * ``video_id`` is retained as a NULLABLE back-compat column for
      readers that still want the YouTube native ID; not a PK, not a
      FK. NULL for non-video rows.
    """

    __tablename__ = "job_documents"
    __table_args__ = (
        Index("ix_job_documents_job_id", "job_id"),
        Index("ix_job_documents_document_id", "document_id"),
        Index("ix_job_documents_video_id", "video_id"),
    )

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Back-compat reading column. Lookups that still filter on
    # `video_id` (legacy code) work unchanged for video rows; new
    # code should filter on `document_id`.
    video_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    curated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# E-1.10 back-compat: legacy callers (tests, ingest paths) still construct
# JobVideo with `video_id=...` only; resolve `document_id` from
# `documents.video_id` at flush time so those callers don't have to be
# rewritten to pre-fetch the UUID.
@event.listens_for(JobVideo, "before_insert")
def _fill_document_id_from_video_id(mapper, connection, target):  # noqa: ARG001
    if target.document_id is None and target.video_id is not None:
        # Late import to break the circular dependency — Document model
        # imports happen via Base.metadata at module load time and
        # SQLAlchemy resolves the FK by reflection rather than via this
        # helper.
        from app.models.document import Document

        row = connection.execute(
            sa.select(Document.document_id).where(
                Document.video_id == target.video_id
            )
        ).first()
        if row is not None:
            target.document_id = row[0]

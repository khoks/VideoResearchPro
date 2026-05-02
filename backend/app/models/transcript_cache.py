from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TranscriptCache(Base):
    """Cache of fetched transcripts keyed by ``document_id``.

    Per E-1.10 cutover (D-017), the canonical key is now
    ``document_id`` (UUID4) rather than ``video_id``. The legacy
    ``video_id`` column is retained as NULLABLE back-compat reading
    metadata; readers that still query by ``video_id`` (legacy code)
    work unchanged, but the table's identity contract is the
    UUID-keyed FK to ``documents.document_id``.

    Transcripts rarely change for a given source, so caching avoids
    repeated YouTube Transcript API calls and Whisper transcriptions
    across jobs that reference the same document.
    """

    __tablename__ = "transcript_cache"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Back-compat reading column. Carries the YouTube native ID for
    # video rows; NULL for non-video rows.
    video_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    segments_json: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


# E-1.10 back-compat: legacy callers still pass `video_id=...` only;
# resolve `document_id` at flush time so we don't have to rewrite all
# transcript cache writers.
@event.listens_for(TranscriptCache, "before_insert")
def _fill_document_id_from_video_id(mapper, connection, target):  # noqa: ARG001
    if target.document_id is None and target.video_id is not None:
        from app.models.document import Document

        row = connection.execute(
            sa.select(Document.document_id).where(
                Document.video_id == target.video_id
            )
        ).first()
        if row is not None:
            target.document_id = row[0]

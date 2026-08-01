"""Captured video frames and their descriptions — R1 / S-1.18.1.

One row per (document, timestamp): a still image pulled from the video at a
moment the selector judged visually informative, plus the vision model's
description of what is on screen there.

**Why this is a separate table rather than a column on the transcript.**
`transcript_cache` is part of the globally-shared compute-once layer — one
row per video, reused by every job and every tenant that references it.
Writing annotations into that text would rewrite shared state to serve one
feature, make re-annotation destructive, and leave no way to distinguish a
transcript that was never annotated from one where the selector legitimately
found nothing. Frames live beside the transcript and are merged into it at
chunk time by `visual_service.annotate_segments`, which is a pure function
over inputs neither of which it mutates.

Frames follow the same compute-once-reuse-forever rule as transcripts and
embeddings: keyed on the document, never on the job. A second job over the
same video reuses whatever is already here. Per-tenant *visibility* is
governed by `document_visibility` on the parent document (D-063); this table
holds no tenant column of its own for the same reason `transcript_cache`
does not.

`status` distinguishes the three ways a row can exist:

* ``captured``  — the JPEG exists, description not attempted yet
* ``described`` — `description` is populated and usable
* ``failed``    — capture or description failed; kept so a retry can tell
  "we tried and it did not work" from "we never tried". A failed row is
  never merged into a transcript.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VisualFrame(Base):
    __tablename__ = "visual_frames"

    frame_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Parent document. Legacy PK column name on `documents` (D-063).
    video_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.video_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Position in the source media. Rounded to whole seconds on write so the
    # uniqueness constraint actually bites — two selectors asking for 132.0
    # and 132.4 mean the same frame.
    timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    # Path to the extracted JPEG, relative to `VISUAL_FRAMES_DIR` — resolve
    # with `frame_service.resolve_image_path`. Deliberately NOT relative to
    # the process cwd: the Celery worker, the API process and a CLI script do
    # not share one, so a cwd-relative path written by the worker may not
    # resolve anywhere else. Nullable because a row can be recorded as
    # `failed` before any image exists.
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Why the selector chose this moment. Not decoration: it is the audit
    # trail for "why did we spend a vision call here", and it is fed to the
    # describer as context so the description answers the right question.
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What the vision model saw. This is the text that gets merged into the
    # transcript as a `[VISUAL @ mm:ss — …]` annotation.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The describer's own judgement of whether the frame carried information
    # the words did not. A talking head against a plain wall is a legitimate
    # capture and a useless annotation; those are stored (so we do not
    # re-capture them) but excluded from the merge.
    informative: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Provider/model that produced `description`, for post-hoc quality
    # analysis when a model is swapped.
    description_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # captured | described | failed
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="captured"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    described_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("video_id", "timestamp_seconds", name="uq_visual_frame_ts"),
        Index("ix_visual_frames_video_status", "video_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<VisualFrame {self.video_id}@{self.timestamp_seconds:.0f}s "
            f"({self.status})>"
        )

"""Output model — I-6 Author Studio foundation (E-6.x).

Each row tracks one generated artifact: a book, a static site, a slide
deck, a newsletter issue, a video / reel. The lifecycle is a small
state machine:

    pending → generating → completed
                        \\→ failed

``kind`` selects the outputter implementation. ``source_ids_json`` is
the list of source IDs (job_ids / document_ids / library Q&A
exchange_ids) that went into this artifact — every paragraph in the
output traces back to one of these. ``parameters_json`` holds
kind-specific generator parameters (book length, site theme, deck
slide count, etc.).

``content_text`` holds the generated artifact for text-based outputs
(books → Markdown, newsletters → text). Binary outputs (PDF, PPTX,
video files) point at ``content_path`` on disk.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Output(Base):
    __tablename__ = "outputs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    # One of: book, site, deck, newsletter, reel. The set is closed at
    # the API layer; extending requires a new outputter implementation
    # + an entry in OutputKind.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # Lifecycle state. Transitions controlled by the service layer.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    # JSON-encoded list of source IDs (job_ids / document_ids /
    # exchange_ids — interpretation is per-kind).
    source_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    # JSON-encoded kind-specific generator parameters. Outputter reads
    # this dict to drive its generation logic.
    parameters_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    # Generated text content (Markdown for books, plain text for
    # newsletters). Null while pending / generating; set on success.
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # File path for binary content (PDF / PPTX / video). Null for
    # text-only outputs.
    content_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Set when status=failed. Reason becomes operator-readable in audits.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

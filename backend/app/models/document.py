import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Document(Base):
    """Global (single-tenant) source-document record.

    The table hosts every ingested source — videos today, podcasts /
    articles / threads / PDFs in upcoming PRs (see
    `docs/source-types.md`). The L1 multi-source columns (`source_type`,
    `source_id`, `source_url`, …) coexist with the legacy YouTube
    columns inherited from when this table was called `videos`.

    The primary key is now ``document_id`` (a UUID4 string) per E-1.10
    cutover (D-017). The legacy ``video_id`` column is retained as a
    NULLABLE back-compat reading column — for ``source_type='video'``
    rows it mirrors the YouTube native ID; for non-video rows it is
    NULL. New code should reference ``document_id`` for joins and
    ``source_id`` for the platform-native identifier.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_channel_id", "channel_id"),
        Index(
            "ix_documents_source_type_source_id",
            "source_type",
            "source_id",
            unique=True,
        ),
    )

    # Canonical PK as of E-1.10 cutover. Generated automatically when
    # not provided so `Document(...)` callers don't have to know about
    # UUID4 minting; tests + ingest paths still work unchanged.
    document_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Legacy back-compat column. Carries the YouTube native ID for
    # ``source_type='video'`` rows; NULL for newer source types
    # (Reddit, HN, etc.) which use ``source_id`` exclusively.
    video_id: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    channel_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("channels.channel_id", ondelete="SET NULL"), nullable=True
    )

    # L1 multi-source discriminator. Defaults to "video" so every existing
    # row continues to round-trip the YouTube path unchanged.
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="video", server_default="video"
    )
    # External identity within `source_type`. For YouTube this mirrors
    # `video_id`; for podcasts it'd be the episode GUID, for articles a
    # canonical URL hash, etc. Unique per `source_type`.
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(200))
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Nullable for non-video sources (articles, threads) which have no duration.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Transcript state
    transcript_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    transcript_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    transcript_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transcripted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # RAG state
    embedded_in_chroma: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Knowledge extraction artifacts (Unit 4)
    # `extracted_knowledge_json` holds the structured merged extraction as a
    # JSON-encoded string: {"topics": [...], "concepts": [...], "events": [...], "facts": [...]}
    # `knowledge_report_md` is the synthesized Markdown knowledge document.
    # `knowledge_extracted_at` is set once the agent has completed successfully.
    extracted_knowledge_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_report_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    channel: Mapped["Channel | None"] = relationship("Channel", lazy="joined")  # noqa: F821

    def __init__(self, **kwargs: Any) -> None:
        # YouTube callers don't know about `source_id` yet; default it to
        # the YouTube video_id so legacy ingest call sites stay unchanged.
        kwargs.setdefault("source_type", "video")
        if "source_id" not in kwargs and "video_id" in kwargs:
            kwargs["source_id"] = kwargs["video_id"]
        if "source_url" not in kwargs and "url" in kwargs:
            kwargs["source_url"] = kwargs["url"]
        # E-1.10: mint the document_id UUID at construct time (not flush
        # time) so callers that read `document.document_id` immediately
        # after construction (e.g. to thread it into a JobVideo link
        # before commit) see a populated value. The column-level default
        # would only fire at flush, which is too late for those callers.
        if "document_id" not in kwargs:
            kwargs["document_id"] = str(uuid.uuid4())
        super().__init__(**kwargs)

    @property
    def channel_name(self) -> str:
        """Backward-compatible accessor; pre-refactor code reads `document.channel_name`."""
        return self.channel.name if self.channel is not None else ""

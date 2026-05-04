import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class QAHistoryExchange(Base):
    """A single "Chat with my Q&A history" exchange (Unit 2 — Personal Wiki).

    This is a meta-conversation: the user asks a question across every Q&A
    they've ever had (job-scoped, library-scoped, and prior history chats).
    The RAG source is the central ``qa_library_global`` ChromaDB collection,
    not a specific job or video.

    Each persisted row is also upserted into ``qa_library_global`` with
    ``source="history"`` so future history questions can reference past
    history answers.
    """

    __tablename__ = "qa_history_exchanges"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Per E-5.1 phase 1 (Alembic a1b2c3d4e5f6). NULLABLE until
    # phase 2 backfill + NOT NULL enforcement.
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    references_json: Mapped[str] = mapped_column(Text, default="[]")
    answer_language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

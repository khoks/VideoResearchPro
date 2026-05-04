import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LibraryQAExchange(Base):
    """A single library-wide Q&A exchange.

    Unlike ``QAExchange``, this is not scoped to a job — it asks against the
    global video library (every video the instance has ever processed).
    """

    __tablename__ = "library_qa_exchanges"

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

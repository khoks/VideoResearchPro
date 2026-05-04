import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class QAExchange(Base):
    __tablename__ = "qa_exchanges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"))

    # Per E-5.1 phase 1 (audit doc + Alembic a1b2c3d4e5f6). NULLABLE
    # because phase 2 backfill + NOT NULL enforcement is a separate
    # PR. Until phase 2 lands, every reader / writer that ignores
    # this column is correct (single-tenant default); phase 2 makes
    # it mandatory.
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    references: Mapped[str] = mapped_column(Text, default="[]")  # JSON array

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="qa_exchanges")  # noqa: F821

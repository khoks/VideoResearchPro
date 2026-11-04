"""UsageRecord: what one tenant spent on one day, by feature (E-5.2).

One row per ``(tenant_id, day, feature, metric)``; ``amount`` only grows.
Written by ``usage_service`` when a metering scope closes, read by
``GET /api/v1/usage``. Metrics: ``llm_tokens_in``, ``llm_tokens_out``,
``llm_calls`` and ``youtube_units``. Features are the user-facing actions
(``library_qa``, ``report``, ``search``, ...) listed in
``usage_service.FEATURES``.

Records, never limits (D-111 took the token line off the pricing page).
The daily totals that ``/auth/quota`` reports still live in ``quota_usage``;
this table is the per-feature breakdown beside them.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", "feature", "metric", name="uq_usage_records_bucket"),
        Index("ix_usage_records_tenant_day", "tenant_id", "day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    feature: Mapped[str] = mapped_column(String(40), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

"""QuotaUsage model — T-5.5.5 / T-5.2.5 quota metering.

Tracks per-user, per-resource, per-period consumption. The composite
``(user_id, resource, period_kind, period_start)`` is unique. Each
row's ``consumed`` is monotonically incremented by
``quota_metering_service.record_usage``.

Resources are short string keys defined in the service module; each
maps to a tier-side limit in ``TIER_CAPABILITIES``. ``period_kind`` is
either ``daily`` or ``monthly``; periods are computed from the
resource's natural cadence (e.g. ``youtube_units`` is daily; document
counts are lifetime / monthly depending on the tier).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class QuotaUsage(Base):
    __tablename__ = "quota_usage"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "resource",
            "period_kind",
            "period_start",
            name="uq_quota_usage_user_resource_period",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    period_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )
    consumed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

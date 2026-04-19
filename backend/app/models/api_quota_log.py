import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiQuotaLog(Base):
    """Per-call log of YouTube Data API quota usage."""

    __tablename__ = "api_quota_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    operation: Mapped[str] = mapped_column(String(50))
    units: Mapped[int] = mapped_column(Integer)

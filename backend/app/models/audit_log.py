"""AuditLog model — E-5.4 auth hardening.

Append-only log of security-relevant events: user registration,
login (success / failure), logout, password changes, password resets,
account lockouts. Every row carries enough context (timestamp, user,
IP, user-agent, structured metadata) to support post-incident review.

The log is queryable per-user via ``GET /api/v1/auth/audit-log``;
admin-wide aggregation is a SaaS-time concern (covered separately).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # tenant_id mirrors the user id for self-host (one tenant per user). On
    # SaaS, tenant_id is the workspace. Nullable so events from anonymous
    # actions (e.g. failed login on a non-existent email) can still log.
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # User the event is about. Nullable for the same reason as tenant_id.
    user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # Short event name. Convention: snake_case. See
    # app/services/audit_service.py::Event for the canonical set.
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Source IP and User-Agent extracted from the request when available.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Free-form structured payload. JSON-encoded string for
    # back-compat with sqlite (no native JSON column).
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

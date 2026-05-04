import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    # E-5.2: Subscription tier gating. Self-host installs default to "free" for
    # everyone; operators may upgrade users manually. SaaS deployment will set
    # this field from the billing service. See app/services/tier_service.py
    # for the per-tier capability table.
    tier: Mapped[str] = mapped_column(
        String(16), nullable=False, default="free", server_default="free"
    )
    # E-5.4: Account lockout — credential-stuffing defence. Failed logins
    # increment the counter; on threshold (default 5 within `LOCKOUT_WINDOW`)
    # the account is locked until `locked_until`. Successful login resets
    # both columns. See app/services/auth_service.py.
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

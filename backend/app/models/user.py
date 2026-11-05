import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # T-5.4.14: whether the account holder knows a password. False for an
    # account Google or GitHub sign-in created: it still gets a random hash
    # (the column is NOT NULL) that nobody knows, so "change password" cannot
    # ask for the current one and sends the user to the reset flow, which
    # sets one and flips this back. Sign-in never reads it.
    has_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
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
    # S-8.10.1: the first-run wizard. `onboarded_at` is set when it is
    # finished; the JSON holds `{step, choices, dismissed, started_at,
    # completed_at, dismissed_at}` and is NULL until first touched. Read
    # and written only through `services/onboarding_service.py`.
    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    onboarding_state_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    # T-1.15.3.9: the depth this person's pages start from (D-064 values).
    # NULL is Auto. The server never applies it: the pages read it, preset
    # their depth control, and a request carries a depth only when that control
    # shows one. So nothing else reads this column, and it reaches nothing
    # another account can see.
    preferred_output_length: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None
    )

"""EchoEmailMessage — a message the email inbox has already taken (T-3.7.4.1).

One row per ``(tenant, message)``, written in the same commit as the share the
message became. It is what makes a re-poll add nothing: the poller flags a
message read, but a flag can fail to land, and a mailbox can hand old mail
back as unread (a migration, a client marking it unread).

It outlives the share on purpose. A share the user deleted stays deleted, as a
fact they deleted does (``echo_fact_tombstones``), so a message still in the
mailbox does not come back at the next poll.

``message_key`` is the SHA-256 of the ``Message-ID`` header, or of the raw
message when it has none. Nothing readable about the mail is kept here.

Registered in ``echo_privacy_service.ECHO_TABLES`` (D-089): exported with the
brain and erased by the full delete.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EchoEmailMessage(Base):
    __tablename__ = "echo_email_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_key", name="uq_echo_email_messages"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    message_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

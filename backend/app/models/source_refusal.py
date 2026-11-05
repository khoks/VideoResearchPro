"""source_refusals — a source that told this install no (T-1.5.14.1).

One row per source type, written by a run whose search came back 401 or 403.
A refused source has nothing to say about the topic, so the run reports it as
unavailable, and until the hold ends the submit form stops offering it
(``source_refusal_service``). Not tenant-scoped: a refusal is a fact about the
install's address and credentials, and ``/health`` reports it to everyone.

Here rather than in Redis because the hold has to outlive a restart, and it
is written from the worker's session and read by the API.

``config_fingerprint`` is a short hash of the settings that decide how the
source is reached, so changing them ends the hold at once. Times are naive
UTC, as SQLite stores them.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SourceRefusal(Base):
    __tablename__ = "source_refusals"

    source_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    refused_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

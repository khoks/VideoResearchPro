"""Per-tenant cache of a context's question suggestions (S-8.4.1 / M4).

One row per ``(tenant_id, context_key)``, where the key is ``job:<id>``,
``document:<id>`` or ``library``. ``fingerprint`` hashes the inputs the
suggestions were computed from (the latest exchange on the context, the
report, the knowledge state), so asking a question on the context makes the
row stale without any hook in the Q&A routers. A cache, not a record: a
table rather than an in-process TTL so the API workers agree and it
survives restarts (plan: docs/plans/m4-question-suggestions.md).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SuggestionCache(Base):
    __tablename__ = "suggestion_cache"
    __table_args__ = (
        UniqueConstraint("tenant_id", "context_key", name="uq_suggestion_cache_context"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    context_key: Mapped[str] = mapped_column(String(120), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)

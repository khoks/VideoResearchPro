"""Per-tenant cache of a channel's intelligence aggregate (E-8.7 / S-8.7.2).

Two readers following the same channel can see different documents (D-063),
so the aggregate is per ``(channel_id, tenant_id)``. ``fingerprint`` hashes
the inputs the document-derived part reads (the visible document set, each
document's knowledge-extraction time and transcript state); a request whose
fingerprint differs recomputes, which is how "invalidate on sync and on new
knowledge" works without hooks in either code path. The Q&A part is cheap
and always computed live, so asking a question never invalidates this row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChannelIntelligenceCache(Base):
    __tablename__ = "channel_intelligence_cache"
    __table_args__ = (
        UniqueConstraint("channel_id", "tenant_id", name="uq_channel_intelligence_tenant"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    channel_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("channels.channel_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)

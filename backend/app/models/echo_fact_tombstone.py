"""EchoFactTombstone — a derived fact the user deleted, kept deleted (T-3.2.4.4).

A connector's sync upserts its derived facts by ``(kind, key)``, so a skill
the user deleted came back at the next nightly sync ("Python (GitHub)"). A
tombstone, one row per ``(tenant, connector, kind, key)``, is recorded when
the user deletes a fact a connector or an export importer derived; the sync
(``echo_connector_service._store_facts``) and the importer
(``echo_import_service.run_import``) skip those keys. Accepted by D-110: a
fact the user deleted stays deleted, for every connector.

``connector`` is the connector or importer name (``github``,
``apple_health``), the same namespace as ``activity_events.connector``. The
fact's value is deliberately not kept: the user asked for it to be gone.
Disconnecting a connector leaves its tombstones (the user deleted those facts,
not the connection); the user clears one from the Echo page to let the next
sync bring it back.

Registered in ``echo_privacy_service.ECHO_TABLES`` (D-089): exported with the
brain and erased by the full delete, in its order.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EchoFactTombstone(Base):
    __tablename__ = "echo_fact_tombstones"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector", "kind", "key", name="uq_echo_fact_tombstones"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    connector: Mapped[str] = mapped_column(String(48), nullable=False)
    # personal_context.kind and .key, same widths.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

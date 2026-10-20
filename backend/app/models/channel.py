from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Channel(Base):
    """Global (single-tenant) source-creator record.

    **Going-forward name: Creator.** The class is exported as
    ``Creator`` from :mod:`app.models.creator` per E-1.9 (channels →
    creators rename). The legacy ``Channel`` name remains as a
    back-compat alias indefinitely — too much existing code
    references it. New code should prefer ``Creator``.

    Today the table holds YouTube channels exclusively. The L1 multi-source
    columns (`source_type`, `creator_external_id`, `creator_metadata_json`)
    are populated for every row so future creators (podcast shows, blog
    domains, X authors, …) can land here without another migration. See
    `docs/source-types.md`.

    **Only shared facts live here.** Per-user state — whether a tenant
    subscribes, their trust weight, when they last synced — is in
    `channel_subscriptions` and is read and written only through
    `subscription_service` (D-065). The global `subscribed`,
    `last_synced_at` and `source_weight` columns were dropped by migration
    `1a6e09517250` (S-5.10.3) once nothing read them.

    **Table-level rename.** The underlying table stays named ``channels``
    in v1 per [D-032](../../../docs/decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03)
    precedent — production data-bearing renames go through an
    operator-coordinated runbook (see ``docs/migration-channels-to-creators.md``)
    rather than an automatic startup migration. When the rename runs,
    only ``__tablename__`` here changes; both ``Channel`` and
    ``Creator`` Python names continue to resolve correctly against the
    new ``creators`` table.
    """

    __tablename__ = "channels"

    channel_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # L1 multi-source: the discriminator + per-source-type external id.
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="video", server_default="video"
    )
    creator_external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    creator_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("source_type", "video")
        if "creator_external_id" not in kwargs and "channel_id" in kwargs:
            kwargs["creator_external_id"] = kwargs["channel_id"]
        super().__init__(**kwargs)

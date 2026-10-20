"""Storing and removing ``activity_events`` (S-3.2.1).

The only writer of the table. ``store_events`` is idempotent on
``(tenant_id, connector, external_id)``: the same event synced twice is one
row, updated in place. Every function is scoped to one tenant.

The ``internal`` connector records what the user does inside Pratidhvani
that is worth knowing about them; today, sharing something to Echo
(``shared_to_pratidhvani``, T-3.2.1.9). Its ``text_content`` stays empty:
the shared words live in ``shares_inbox`` under D-089's context-only rule and
are not copied here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.connectors.base import ActivityEvent as EventIn
from app.models.activity_event import ActivityEvent

logger = logging.getLogger(__name__)

INTERNAL = "internal"
SHARED_EVENT = "shared_to_pratidhvani"
_BATCH = 200


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _payload(event: EventIn) -> str:
    return json.dumps(event.payload or {}, ensure_ascii=False, sort_keys=True, default=str)


def store_events(db: Session, tenant_id: str, connector: str, events: Iterable[EventIn],
                 *, batch_size: int = _BATCH) -> dict[str, int]:
    """Insert new events and refresh known ones. Returns
    ``{"added": n, "updated": n, "unchanged": n}``. Commits per batch, so a
    long backfill keeps what it stored if it fails part-way (the next sync
    resumes idempotently). Export imports pass a larger ``batch_size``: a
    commit costs about 25 ms on SQLite, which dominated a 200k-event import."""
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    batch: dict[str, EventIn] = {}

    def flush() -> None:
        if not batch:
            return
        existing = {
            row.external_id: row
            for row in db.query(ActivityEvent).filter(
                ActivityEvent.tenant_id == tenant_id,
                ActivityEvent.connector == connector,
                ActivityEvent.external_id.in_(list(batch)),
            )
        }
        new_rows = []
        for external_id, ev in batch.items():
            fields = {
                "event_type": ev.event_type,
                "occurred_at": _naive_utc(ev.occurred_at),
                "payload_json": _payload(ev),
                "text_content": ev.text_content or None,
                "linked_document_id": ev.linked_document_id,
            }
            row = existing.get(external_id)
            if row is None:
                new_rows.append({
                    "tenant_id": tenant_id, "user_id": tenant_id, "connector": connector,
                    "external_id": external_id, **fields,
                })
                counts["added"] += 1
            elif any(getattr(row, k) != v for k, v in fields.items()):
                for k, v in fields.items():
                    setattr(row, k, v)
                row.ingested_at = datetime.now(timezone.utc)
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
        if new_rows:
            # One executemany per batch; ORM objects cost several times more.
            db.execute(insert(ActivityEvent), new_rows)
        db.commit()
        batch.clear()

    for ev in events:
        if not ev.external_id:
            raise ValueError(f"{connector}: an event without external_id cannot be stored idempotently")
        batch[ev.external_id] = ev  # the same id twice in a batch: last wins
        if len(batch) >= batch_size:
            flush()
    flush()
    return counts


def delete_connector_events(db: Session, tenant_id: str, connector: str) -> int:
    """Every event ``connector`` wrote for ``tenant_id``. The caller commits."""
    return (
        db.query(ActivityEvent)
        .filter(ActivityEvent.tenant_id == tenant_id, ActivityEvent.connector == connector)
        .delete(synchronize_session=False)
    )


def count_events(db: Session, tenant_id: str, connector: str | None = None) -> int:
    q = db.query(ActivityEvent).filter(ActivityEvent.tenant_id == tenant_id)
    if connector:
        q = q.filter(ActivityEvent.connector == connector)
    return q.count()


def list_events(
    db: Session,
    tenant_id: str,
    *,
    connector: str | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> list[ActivityEvent]:
    """Newest first: the timeline."""
    q = db.query(ActivityEvent).filter(ActivityEvent.tenant_id == tenant_id)
    if connector:
        q = q.filter(ActivityEvent.connector == connector)
    if before is not None:
        q = q.filter(ActivityEvent.occurred_at < _naive_utc(before))
    return q.order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id).limit(limit).all()


# --------------------------------------------------------------- shares (internal)

def share_external_id(share_id: str) -> str:
    return f"share:{share_id}"


def record_share_event(db: Session, share, *, title: str | None = None) -> None:
    """One ``shared_to_pratidhvani`` event per processed share (idempotent
    on re-processing). Metadata only; the shared content stays in the inbox."""
    payload = {
        "share_id": share.id,
        "content_type": share.content_type,
        "surface": share.surface,
        "author_is_tenant": bool(share.author_is_tenant),
    }
    if title:
        payload["title"] = title[:300]
    store_events(db, share.tenant_id, INTERNAL, [EventIn(
        external_id=share_external_id(share.id),
        event_type=SHARED_EVENT,
        occurred_at=share.received_at or datetime.now(timezone.utc),
        payload=payload,
        linked_document_id=share.linked_document_id,
    )])


def delete_share_event(db: Session, tenant_id: str, share_id: str) -> int:
    """Remove a share's event with the share. The caller commits."""
    return (
        db.query(ActivityEvent)
        .filter(
            ActivityEvent.tenant_id == tenant_id,
            ActivityEvent.connector == INTERNAL,
            ActivityEvent.external_id == share_external_id(share_id),
        )
        .delete(synchronize_session=False)
    )

"""In-app notifications (S-8.3.3 / M3).

One table, ``notifications``, read by the bell in the sidebar. Producers
call ``create``; the first is a saved search whose answer changed. Every
read and write is scoped to the tenant: another tenant's id is "not found".

T-8.3.3.8: ``create`` also publishes on ``notifications:{tenant_id}`` so an
open bell refetches at once (``/ws/jobs`` with ``subscribe`` +
``topic: "notifications"``). The push is a doorbell, not the letter: it
carries the new row's id and kind, never its title or body, so what a
notice says is only ever read over HTTP, where the session is checked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.notification import Notification

logger = logging.getLogger(__name__)

KIND_SAVED_SEARCH_CHANGED = "saved_search_changed"
KIND_NEWSLETTER_ISSUE = "newsletter_issue"  # S-6.4.2: a scheduled digest was made


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create(db: Session, tenant_id: str, *, kind: str, title: str, body: str | None = None, href: str | None = None) -> Notification:
    row = Notification(tenant_id=tenant_id, kind=kind, title=title[:300], body=body, href=href)
    db.add(row)
    db.commit()
    db.refresh(row)
    push(row)
    return row


def push(row: Notification) -> bool:
    """Tell the owner's open sockets that ``row`` exists (after the commit,
    so the bell's refetch finds it). Never fails the producer."""
    from app.config import settings

    if not settings.NOTIFICATIONS_PUSH_ENABLED:
        return False
    try:
        from app.services import progress_service

        return progress_service.publish_notification(
            row.tenant_id, {"type": "notification", "id": row.id, "kind": row.kind}
        )
    except Exception:  # pragma: no cover - the publisher is already fail-soft
        logger.exception("notifications: push for %s failed", row.id)
        return False


def list_for(db: Session, tenant_id: str, *, unread_only: bool = False, limit: int = 30) -> tuple[list[Notification], int]:
    q = db.query(Notification).filter(Notification.tenant_id == tenant_id)
    unread = q.filter(Notification.read_at.is_(None)).count()
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    items = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return items, unread


def mark_read(db: Session, tenant_id: str, notification_id: str, read: bool = True) -> Notification | None:
    row = db.query(Notification).filter(Notification.id == notification_id, Notification.tenant_id == tenant_id).first()
    if row is None:
        return None
    row.read_at = (row.read_at or _now()) if read else None
    db.commit()
    db.refresh(row)
    return row


def mark_all_read(db: Session, tenant_id: str) -> int:
    n = (
        db.query(Notification)
        .filter(Notification.tenant_id == tenant_id, Notification.read_at.is_(None))
        .update({Notification.read_at: _now()}, synchronize_session=False)
    )
    db.commit()
    return n

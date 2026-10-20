"""``/notifications`` — the bell (S-8.3.3).

The caller's own notices only; another tenant's id is a 404. No tier gate:
every tier can receive notices, even if today's only producer (a changed
saved search) is Pro and Studio.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.notification import NotificationList, NotificationPatch, NotificationResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n) -> NotificationResponse:
    return NotificationResponse(
        id=n.id, kind=n.kind, title=n.title, body=n.body, href=n.href, read_at=n.read_at, created_at=n.created_at
    )


@router.get("", response_model=NotificationList)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, unread = notification_service.list_for(db, current_user.id, unread_only=unread_only, limit=limit)
    return NotificationList(items=[_out(n) for n in items], unread=unread)


@router.patch("/{notification_id}", response_model=NotificationResponse)
def patch_notification(
    notification_id: str,
    body: NotificationPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = notification_service.mark_read(db, current_user.id, notification_id, body.read)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return _out(row)


@router.post("/read-all")
def read_all_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"marked": notification_service.mark_all_read(db, current_user.id)}

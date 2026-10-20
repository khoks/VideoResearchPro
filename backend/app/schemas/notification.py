"""Notification payloads (S-8.3.3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: str
    kind: str
    title: str
    body: str | None
    href: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationResponse]
    unread: int


class NotificationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: bool

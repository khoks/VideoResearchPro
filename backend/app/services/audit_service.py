"""Audit log service — E-5.4 auth hardening.

Append-only event log for security-relevant actions. Failures are
logged but never propagate — auditing must not break the call site
it's instrumenting (mirrors the quota_service pattern).
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class Event(str, Enum):
    """Canonical event names. Add new entries here, never invent
    free-form strings at the call site."""

    USER_REGISTERED = "user_registered"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGIN_LOCKED_OUT = "login_locked_out"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    PASSWORD_RESET_INVALID_TOKEN = "password_reset_invalid_token"
    PASSWORD_CHANGED = "password_changed"


def _ip_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    # Prefer X-Forwarded-For if behind a proxy; fall back to direct.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # Trust the leftmost entry as the real client IP.
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return None


def _ua_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    return request.headers.get("user-agent")


def record(
    db: Session,
    *,
    event: Event | str,
    user_id: str | None = None,
    tenant_id: str | None = None,
    request: Request | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog | None:
    """Persist one audit event. Returns the row, or ``None`` on
    failure (the caller doesn't usually care — auditing is best-effort).

    Convenience: pass ``request`` and the IP / UA are auto-extracted.
    Explicit ``ip_address`` / ``user_agent`` overrides win over
    ``request``-derived values.
    """
    try:
        event_value = event.value if isinstance(event, Event) else str(event)
        if ip_address is None:
            ip_address = _ip_from_request(request)
        if user_agent is None:
            user_agent = _ua_from_request(request)
            # Truncate aggressively long UAs to fit the column.
            if user_agent is not None and len(user_agent) > 512:
                user_agent = user_agent[:512]
        # On self-host, tenant_id mirrors user_id when not specified.
        if tenant_id is None and user_id is not None:
            tenant_id = user_id

        row = AuditLog(
            event=event_value,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        logger.exception(
            "audit_service.record: failed to persist event=%s user_id=%s",
            event,
            user_id,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None


def list_for_user(
    db: Session,
    user_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Return the user's most-recent audit events, newest first."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

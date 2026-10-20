"""Echo connectors REST (S-3.2.1).

The provider sends the browser back to the frontend route
``/echo/connectors/{name}/callback``, which posts ``code`` and ``state`` here
with the reader's token: the state is bound to that reader, so a code cannot
be redeemed into someone else's account. The redirect URI is built on the
server (``echo_connector_service.redirect_uri``), never taken from a client.

Every endpoint is gated on ``echo_personal_brain`` like the rest of Echo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import activity_event_service, echo_connector_service
from app.services.echo_connector_service import (
    ConnectError,
    ConnectorNotFound,
    ConnectorUnavailable,
    ConsentMismatch,
)
from app.services.echo_service import SUPPORTED_KINDS
from app.services.tier_service import require_feature

router = APIRouter(prefix="/echo", tags=["echo"])
ECHO = require_feature("echo_personal_brain")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class ConnectorGrantOut(BaseModel):
    account_label: str | None
    granted_at: datetime | None
    consent_version: str
    consent_outdated: bool
    status: str
    last_sync_at: datetime | None
    backfilled_at: datetime | None
    last_error: str | None
    last_counts: dict[str, int] | None
    events: int


class ConnectorItem(BaseModel):
    name: str
    display_name: str
    privacy_weight: str
    consent_disclosure: str
    consent_version: str
    event_types: list[str]
    configured: bool
    connected: bool
    grant: ConnectorGrantOut | None


class ConnectorListResponse(BaseModel):
    # Kept from the v1 response: registered connector names.
    connectors: list[str]
    supported_kinds: list[str]
    items: list[ConnectorItem]


class AuthorizeRequest(BaseModel):
    # The version of the disclosure the consent screen showed.
    consent_version: str = Field(min_length=1, max_length=32)


class AuthorizeResponse(BaseModel):
    authorize_url: str


class CallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=128)


class SyncResponse(BaseModel):
    dispatched: str  # queued | ran | off | queue_failed
    connector: ConnectorItem


class RevokeResponse(BaseModel):
    connector: str
    events: int
    facts: int
    provider_revoked: bool


class ActivityItem(BaseModel):
    id: str
    connector: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    text_content: str | None
    linked_document_id: str | None


class ActivityResponse(BaseModel):
    items: list[ActivityItem]
    # Pass as `before` for the next page; null on the last page.
    next_before: datetime | None


def _item(db: Session, tenant_id: str, name: str) -> ConnectorItem:
    for d in echo_connector_service.list_for_tenant(db, tenant_id):
        if d["name"] == name:
            return _to_item(d)
    raise HTTPException(status_code=404, detail="Connector not found")


def _to_item(d: dict) -> ConnectorItem:
    grant = d["grant"]
    if grant is not None:
        grant = {**grant, **{k: _aware(grant[k]) for k in ("granted_at", "last_sync_at", "backfilled_at")}}
    return ConnectorItem(**{**d, "grant": grant})


@router.get("/connectors", response_model=ConnectorListResponse)
def list_connectors(
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
) -> ConnectorListResponse:
    """Every connector this install offers, with the caller's grant (if
    any): what the consent screen shows, and how syncing is going."""
    items = [_to_item(d) for d in echo_connector_service.list_for_tenant(db, current_user.id)]
    return ConnectorListResponse(
        connectors=[i.name for i in items],
        supported_kinds=sorted(SUPPORTED_KINDS),
        items=items,
    )


@router.post("/connectors/{name}/authorize", response_model=AuthorizeResponse)
def authorize(
    name: str,
    body: AuthorizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
) -> AuthorizeResponse:
    """Start connecting: returns the provider's sign-in URL for the browser to
    open. Refused (409) unless ``consent_version`` is the disclosure shown."""
    try:
        url = echo_connector_service.start_connect(db, current_user.id, name, body.consent_version)
    except ConnectorNotFound:
        raise HTTPException(status_code=404, detail="Connector not found")
    except ConnectorUnavailable:
        raise HTTPException(status_code=503, detail="This connector is not configured on this install.")
    except ConsentMismatch:
        raise HTTPException(status_code=409, detail="The connector's disclosure changed; review it again.")
    return AuthorizeResponse(authorize_url=url)


@router.post("/connectors/{name}/callback", response_model=ConnectorItem)
def callback(
    name: str,
    body: CallbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
) -> ConnectorItem:
    """Finish connecting with the code the provider handed the browser."""
    try:
        echo_connector_service.complete_connect(db, current_user.id, name, state=body.state, code=body.code)
    except ConnectorNotFound:
        raise HTTPException(status_code=404, detail="Connector not found")
    except ConnectError:
        # Never say which step failed (D-040's posture for OAuth).
        raise HTTPException(status_code=400, detail="Connecting failed. Start again from the Echo page.")
    return _item(db, current_user.id, name)


@router.post("/connectors/{name}/sync", response_model=SyncResponse)
def sync_now(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
) -> SyncResponse:
    grant = echo_connector_service.get_grant(db, current_user.id, name)
    if grant is None:
        raise HTTPException(status_code=404, detail="Not connected")
    dispatched = echo_connector_service.enqueue_sync(grant.id)
    db.expire_all()
    return SyncResponse(dispatched=dispatched, connector=_item(db, current_user.id, name))


@router.delete("/connectors/{name}", response_model=RevokeResponse)
def revoke(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
) -> RevokeResponse:
    """Disconnect and delete everything this connector brought in: events,
    derived facts, tokens. Revoking at the provider is best effort."""
    try:
        result = echo_connector_service.revoke(db, current_user.id, name)
    except ConnectorNotFound:
        raise HTTPException(status_code=404, detail="Connector not found")
    return RevokeResponse(**result)


@router.get("/activity", response_model=ActivityResponse)
def activity(
    connector: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
) -> ActivityResponse:
    """The caller's activity timeline, newest first."""
    rows = activity_event_service.list_events(
        db, current_user.id, connector=connector, before=before, limit=limit
    )
    items = [
        ActivityItem(
            id=r.id,
            connector=r.connector,
            event_type=r.event_type,
            occurred_at=_aware(r.occurred_at),
            payload=json.loads(r.payload_json or "{}"),
            text_content=r.text_content,
            linked_document_id=r.linked_document_id,
        )
        for r in rows
    ]
    return ActivityResponse(
        items=items, next_before=items[-1].occurred_at if len(items) == limit else None
    )

"""Echo (personal-brain) router — I-3 foundation.

Endpoints under ``/api/v1/echo/*``:

- ``GET /echo/status`` — cold-start readiness diagnostics. Returns
  ``{ready, total_rows, distinct_sources, has_personality_trait,
  threshold_total, threshold_sources}``. Frontend uses this to gate
  the "speak as me" UI.
- ``GET /echo/context`` — list the user's personal-context rows.
  Optional query: ``kind=...`` / ``source=...`` filters.
- ``POST /echo/context`` — manual entry. Body
  ``{kind, key, value, expires_at?, confidence?}``. Source is hard-coded
  to ``manual`` for this surface.
- ``DELETE /echo/context/{kind}/{key}`` — delete a single row.
- ``DELETE /echo/sources/{source}`` — revoke a connector. Deletes
  every row attributed to that source.
- ``GET /echo/connectors`` — list registered connectors. v1 ships
  with the registry empty; future connector PRs populate it.

All endpoints gated on ``require_feature("echo_personal_brain")`` —
Studio-tier-only initially.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import echo_service
from app.services.echo_service import SUPPORTED_KINDS, UnsupportedKindError
from app.services.tier_service import require_feature

router = APIRouter(prefix="/echo", tags=["echo"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class EchoStatusResponse(BaseModel):
    ready: bool
    total_rows: int
    distinct_sources: int
    has_personality_trait: bool
    threshold_total: int
    threshold_sources: int


class PersonalContextItem(BaseModel):
    id: str
    kind: str
    key: str
    value: str
    source: str
    confidence: float
    captured_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class RecordContextPayload(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    key: str = Field(min_length=1, max_length=128)
    value: Any
    expires_at: datetime | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class DeleteResponse(BaseModel):
    deleted: bool


class RevokeSourceResponse(BaseModel):
    deleted_count: int


class ConnectorListResponse(BaseModel):
    connectors: list[str]
    supported_kinds: list[str]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=EchoStatusResponse)
def echo_status(
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> EchoStatusResponse:
    r = echo_service.is_ready(db, current_user.id)
    return EchoStatusResponse(
        ready=r.ready,
        total_rows=r.total_rows,
        distinct_sources=r.distinct_sources,
        has_personality_trait=r.has_personality_trait,
        threshold_total=r.threshold_total,
        threshold_sources=r.threshold_sources,
    )


# ---------------------------------------------------------------------------
# Personal context CRUD
# ---------------------------------------------------------------------------


@router.get("/context", response_model=list[PersonalContextItem])
def list_context_endpoint(
    kind: str | None = Query(None),
    source: str | None = Query(None),
    include_expired: bool = Query(False),
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> list[PersonalContextItem]:
    try:
        rows = echo_service.list_context(
            db,
            current_user.id,
            kind=kind,
            source=source,
            include_expired=include_expired,
        )
    except UnsupportedKindError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return [PersonalContextItem.model_validate(r) for r in rows]


@router.post("/context", response_model=PersonalContextItem)
def record_context_endpoint(
    payload: RecordContextPayload,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> PersonalContextItem:
    try:
        row = echo_service.record_context(
            db,
            user_id=current_user.id,
            kind=payload.kind,
            key=payload.key,
            value=payload.value,
            source="manual",
            confidence=payload.confidence,
            expires_at=payload.expires_at,
        )
    except UnsupportedKindError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return PersonalContextItem.model_validate(row)


@router.delete("/context/{kind}/{key}", response_model=DeleteResponse)
def delete_context_endpoint(
    kind: str,
    key: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    deleted = echo_service.delete_context(db, current_user.id, kind, key)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Context row not found",
        )
    return DeleteResponse(deleted=True)


@router.delete("/sources/{source}", response_model=RevokeSourceResponse)
def revoke_source_endpoint(
    source: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> RevokeSourceResponse:
    """Revoke a connector — deletes every row attributed to that
    source for the current user. Idempotent: returns 0 when no rows
    matched."""
    n = echo_service.revoke_source(db, current_user.id, source)
    return RevokeSourceResponse(deleted_count=n)


# ---------------------------------------------------------------------------
# Connector registry
# ---------------------------------------------------------------------------


@router.get("/connectors", response_model=ConnectorListResponse)
def list_connectors_endpoint(
    _: User = Depends(require_feature("echo_personal_brain")),
) -> ConnectorListResponse:
    """List registered Echo connectors. v1 ships with an empty
    registry; future connector PRs populate it."""
    return ConnectorListResponse(
        connectors=echo_service.list_connectors(),
        supported_kinds=sorted(SUPPORTED_KINDS),
    )

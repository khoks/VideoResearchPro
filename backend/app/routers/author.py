"""Author Studio router — I-6 foundation.

Endpoints under ``/api/v1/author/*``:

- ``GET /author/kinds`` — list registered output kinds (those with a
  concrete outputter shipped). v1: ``["book"]``.
- ``POST /author/outputs`` — create + immediately generate. Body
  ``{kind, title, source_ids, parameters?}``. Returns the resulting
  Output row. Status will be ``completed`` on success or ``failed``
  with ``error_message`` populated on failure.
- ``GET /author/outputs`` — list current user's outputs (kind / status
  query filters).
- ``GET /author/outputs/{id}`` — get one (404 cross-user — existence-leak posture).
- ``GET /author/outputs/{id}/content`` — fetch generated content.
  Plain-text response (Content-Type: text/markdown for books).
- ``DELETE /author/outputs/{id}`` — delete.

All endpoints gated on ``require_feature("author_studio")``
(Pro+; see TIER_CAPABILITIES).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Import outputters to register them. Side-effect import.
from app.services import outputters  # noqa: F401
from app.dependencies import get_db
from app.models.user import User
from app.services import output_service
from app.services.output_service import (
    OutputError,
    OutputKind,
    SUPPORTED_KINDS,
    UnsupportedKindError,
)
from app.services.tier_service import require_feature

router = APIRouter(prefix="/author", tags=["author"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OutputItem(BaseModel):
    id: str
    kind: str
    title: str
    status: str
    source_ids: list[str]
    parameters: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    has_content: bool

    model_config = {"from_attributes": False}


class CreateOutputPayload(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=256)
    source_ids: list[str] = Field(default_factory=list, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)


class KindsResponse(BaseModel):
    available: list[str]
    supported: list[str]


class DeleteResponse(BaseModel):
    deleted: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_item(row) -> OutputItem:
    import json
    return OutputItem(
        id=row.id,
        kind=row.kind,
        title=row.title,
        status=row.status,
        source_ids=json.loads(row.source_ids_json or "[]"),
        parameters=json.loads(row.parameters_json or "{}"),
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        has_content=bool(row.content_text or row.content_path),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/kinds", response_model=KindsResponse)
def list_kinds(
    _: User = Depends(require_feature("author_studio")),
) -> KindsResponse:
    """Return the kinds that have a concrete outputter registered
    (``available``) vs every kind defined in the OutputKind enum
    (``supported``). Frontend uses this to disable buttons for
    not-yet-implemented kinds."""
    return KindsResponse(
        available=output_service.list_outputters(),
        supported=sorted(SUPPORTED_KINDS),
    )


@router.post("/outputs", response_model=OutputItem)
def create_and_generate(
    payload: CreateOutputPayload,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> OutputItem:
    """Create the row + run generation synchronously. v1's outputters
    are deterministic and fast (no LLM); a future PR can wrap this in
    a Celery task when generation gets expensive."""
    try:
        row = output_service.create_output(
            db,
            user_id=current_user.id,
            kind=payload.kind,
            title=payload.title,
            source_ids=payload.source_ids,
            parameters=payload.parameters,
        )
    except UnsupportedKindError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    except OutputError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    if output_service.get_outputter(payload.kind) is None:
        # Kind is in the enum but no outputter shipped (e.g. site /
        # deck / newsletter / reel today). Leave the row in pending
        # state so future PRs can pick it up; return 501 + a clear
        # message.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"Output kind '{payload.kind}' is supported by the schema "
                f"but no concrete outputter is registered yet. "
                f"Available today: {output_service.list_outputters()}."
            ),
        )

    row = output_service.run_generation(db, current_user, row)
    return _to_item(row)


@router.get("/outputs", response_model=list[OutputItem])
def list_outputs_endpoint(
    kind: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> list[OutputItem]:
    try:
        rows = output_service.list_outputs(
            db, current_user.id, kind=kind, status=status_filter
        )
    except UnsupportedKindError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return [_to_item(r) for r in rows]


@router.get("/outputs/{output_id}", response_model=OutputItem)
def get_output_endpoint(
    output_id: str,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> OutputItem:
    row = output_service.get_output(db, current_user.id, output_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Output not found"
        )
    return _to_item(row)


@router.get("/outputs/{output_id}/content")
def get_output_content(
    output_id: str,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
):
    row = output_service.get_output(db, current_user.id, output_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Output not found"
        )
    if not row.content_text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output has no content (status={row.status})",
        )
    media_type = "text/markdown" if row.kind == OutputKind.BOOK.value else "text/plain"
    return PlainTextResponse(row.content_text, media_type=media_type)


@router.delete("/outputs/{output_id}", response_model=DeleteResponse)
def delete_output_endpoint(
    output_id: str,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    deleted = output_service.delete_output(db, current_user.id, output_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Output not found"
        )
    return DeleteResponse(deleted=True)

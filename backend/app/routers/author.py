"""Author Studio router — I-6 foundation.

Endpoints under ``/api/v1/author/*``:

- ``GET /author/kinds`` — list registered output kinds (those with a
  concrete outputter shipped). v1: ``["book"]``.
- ``POST /author/outputs`` — create a ``pending`` row and dispatch
  ``generate_output`` to the worker on the owner's tier queue (S-6.7.1).
  Body ``{kind, title, source_ids, parameters?}``. Progress arrives on the
  `/ws/jobs` socket under the output's id. ``?sync=true`` generates inline
  and returns the finished row (the test path). A kind with no outputter
  is 501 before any row is written.
- ``POST /author/outputs/{id}/cancel`` — cancel a pending or generating
  output (S-6.7.1).
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
from app.services import output_service, task_routing_service
from app.services.output_service import (
    OutputError,
    OutputKind,
    SUPPORTED_KINDS,
    UnsupportedKindError,
)
from app.services.tier_service import require_feature
from app.tasks.output_tasks import generate_output

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
    # S-6.7.1: what the worker last reported. A row with no task id and a
    # `pending` status predates S-6.7.1 (it was never queued).
    progress_pct: int = 0
    progress_message: str | None = None
    celery_task_id: str | None = None
    # S-6.1.1: whitespace-separated words in the generated text; None
    # until there is content. The page shows it beside the chapter count.
    word_count: int | None = None

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
        word_count=len(row.content_text.split()) if row.content_text else None,
        progress_pct=row.progress_pct or 0,
        progress_message=row.progress_message,
        celery_task_id=row.celery_task_id,
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
    sync: bool = Query(False, description="Generate inline and return the finished row (tests, scripts)"),
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> OutputItem:
    """Create the row and queue its generation in the worker (S-6.7.1).

    Returns the `pending` row at once; the worker publishes progress on
    `job_progress:{output_id}`. ``sync=true`` runs generation inside the
    request instead and returns the finished row.
    """
    # S-6.1.1: a book is one chapter per run, so zero runs is a request
    # error, not a generation failure. Refusing here means no `failed`
    # row is left behind for the user to clean up.
    if payload.kind == OutputKind.BOOK.value and not payload.source_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A book needs at least one run: source_ids is empty.",
        )
    # T-6.7.1.5: a kind with no outputter is refused before any row is
    # written. It used to leave a `pending` row behind, which no worker
    # would ever pick up.
    if payload.kind in SUPPORTED_KINDS and output_service.get_outputter(payload.kind) is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"Output kind '{payload.kind}' is supported by the schema "
                f"but no concrete outputter is registered yet. "
                f"Available today: {output_service.list_outputters()}."
            ),
        )
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

    if sync:
        row = output_service.run_generation(db, current_user, row)
        return _to_item(row)

    try:
        result = task_routing_service.dispatch_for_user(generate_output, current_user, row.id)
    except Exception as e:  # noqa: BLE001 — broker down: say so on the row
        output_service.transition_to(
            db, row, output_service.OutputStatus.FAILED,
            error_message=f"Could not queue generation: {e}", progress_message="Failed",
        )
        db.refresh(row)
        return _to_item(row)
    row.celery_task_id = getattr(result, "id", None)
    row.progress_message = "Queued"
    db.commit()
    db.refresh(row)
    return _to_item(row)


@router.post("/outputs/{output_id}/cancel", response_model=OutputItem)
def cancel_output_endpoint(
    output_id: str,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> OutputItem:
    """Cancel a pending or generating output; mirrors `/jobs/{id}/cancel`.
    404 for another user's output, 400 once it has finished."""
    try:
        row = output_service.cancel_output(db, current_user.id, output_id)
    except OutputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output not found")
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

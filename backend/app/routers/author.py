"""Author Studio router — I-6 foundation.

Endpoints under ``/api/v1/author/*``:

- ``GET /author/kinds`` — list registered output kinds (those with a
  concrete outputter shipped). v1: ``["book"]``. S-6.1.5: ``formats`` says
  which downloads each kind can be built as on this server, and why any
  other is unavailable (a book's PDF needs an optional converter).
- ``POST /author/outputs`` — create a ``pending`` row and dispatch
  ``generate_output`` to the worker on the owner's tier queue (S-6.7.1).
  Body ``{kind, title, source_ids, parameters?}``. Progress arrives on the
  `/ws/jobs` socket under the output's id. ``?sync=true`` generates inline
  and returns the finished row (the test path). A kind with no outputter
  is 501 before any row is written, and so is a format the server cannot
  build (a book's ``pdf`` with no converter installed; S-6.1.5).
- ``POST /author/outputs/estimate`` — what generating this output would
  cost before it runs (S-6.1.3: a book's cohesion pass). Same body as create.
- ``POST /author/outputs/{id}/cancel`` — cancel a pending or generating
  output (S-6.7.1).
- ``GET /author/outputs`` — list current user's outputs (kind / status
  query filters).
- ``GET /author/outputs/{id}`` — get one (404 cross-user — existence-leak posture).
- ``GET /author/outputs/{id}/download?format=`` — the output as a file
  (S-6.7.2): its text (`md` for books) or a binary artifact (`pdf`,
  `epub`, `pptx`, `zip`) from `OUTPUTS_DIR`. Header-bearer only (D-079).
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
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, object_session

# Import outputters to register them. Side-effect import.
from app.services import outputters  # noqa: F401
from app.dependencies import get_db
from app.models.user import User
from app.services import newsletter_service, output_artifacts, output_citation_service, output_service, task_routing_service
from app.services.output_service import (
    OutputError,
    OutputKind,
    SUPPORTED_KINDS,
    UnsupportedKindError,
)
from app.services.tier_service import require_feature
from app.tasks.newsletter_tasks import issue_newsletter
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
    # S-6.7.2: the formats `GET …/download?format=` can serve, text first.
    formats: list[str] = []
    # S-6.7.3: rows in `output_citations` (GET …/citations lists them).
    citation_count: int = 0
    # S-6.1.1: whitespace-separated words in the generated text; None
    # until there is content. The page shows it beside the chapter count.
    word_count: int | None = None
    # S-6.1.3: the model calls generation made (use case, model, tokens,
    # cost) and their total; None when it made none.
    usage: dict[str, Any] | None = None

    model_config = {"from_attributes": False}


class CreateOutputPayload(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=256)
    source_ids: list[str] = Field(default_factory=list, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)


class KindFormats(BaseModel):
    available: list[str]
    # format -> why it cannot be built here (with what to install)
    unavailable: dict[str, str] = {}
    pdf_engine: str | None = None


class KindsResponse(BaseModel):
    available: list[str]
    supported: list[str]
    # S-6.1.5: per available kind, the download formats this server builds.
    formats: dict[str, KindFormats] = {}


class DeleteResponse(BaseModel):
    deleted: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _citation_count(row) -> int:
    db = object_session(row)
    return output_citation_service.counts_for(db, [row.id]).get(row.id, 0) if db is not None else 0


def _to_item(row, citation_count: int | None = None) -> OutputItem:
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
        formats=output_artifacts.available_formats(row),
        citation_count=citation_count if citation_count is not None else _citation_count(row),
        word_count=len(row.content_text.split()) if row.content_text else None,
        progress_pct=row.progress_pct or 0,
        progress_message=row.progress_message,
        celery_task_id=row.celery_task_id,
        usage=json.loads(row.usage_json) if row.usage_json else None,
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
    formats: dict[str, KindFormats] = {}
    for kind in output_service.list_outputters():
        options = getattr(output_service.get_outputter(kind), "format_options", None)
        if options is not None:
            formats[kind] = KindFormats(**options())
    return KindsResponse(
        available=output_service.list_outputters(),
        supported=sorted(SUPPORTED_KINDS),
        formats=formats,
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
    # S-6.1.5: the outputter resolves and checks its parameters before the
    # row exists, so a format this server cannot build leaves nothing behind.
    parameters = payload.parameters
    prepare = getattr(output_service.get_outputter(payload.kind), "prepare_parameters", None)
    if prepare is not None:
        try:
            parameters = prepare(dict(parameters))
        except output_service.OutputUnavailable as e:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(e))
        except OutputError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    try:
        row = output_service.create_output(
            db,
            user_id=current_user.id,
            kind=payload.kind,
            title=payload.title,
            source_ids=payload.source_ids,
            parameters=parameters,
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


@router.post("/outputs/estimate")
def estimate_output(
    payload: CreateOutputPayload,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """S-6.1.3 / T-6.1.3.5: what generating this output would cost, before
    it runs, on the models its use cases resolve to now. Writes nothing.
    ``{"cohesion", "calls": [{use_case, provider, model, reasoning,
    input_tokens, output_tokens, cost_usd}], "cost_usd", "pricing_as_of"}``;
    a kind or setting that calls no model returns no calls and cost 0."""
    outputter = output_service.get_outputter(payload.kind)
    if outputter is None:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=f"No outputter for kind '{payload.kind}'.")
    estimate = getattr(outputter, "estimate", None)
    if estimate is None:
        return {"calls": [], "cost_usd": 0.0}
    try:
        return estimate(db, current_user, payload.title, payload.source_ids, dict(payload.parameters))
    except OutputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


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
    counts = output_citation_service.counts_for(db, [r.id for r in rows])
    return [_to_item(r, counts.get(r.id, 0)) for r in rows]


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


@router.get("/outputs/{output_id}/download")
def download_output(
    output_id: str,
    fmt: str | None = Query(None, alias="format", pattern=r"^[a-z0-9]{1,8}$"),
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
):
    """The output as a file (S-6.7.2). ``format`` picks one of the row's
    ``formats``; without it the first (the text, for a book) is served.

    Header-bearer only, like every new report-shaped route since D-079: the
    page fetches with the header and saves a blob, so no token ever sits in
    a URL. 404 for another user's output, for a format the output does not
    have, and for an artifact whose stored path resolves outside
    ``OUTPUTS_DIR``.
    """
    row = output_service.get_output(db, current_user.id, output_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output not found")
    formats = output_artifacts.available_formats(row)
    if not formats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output has no content (status={row.status})",
        )
    chosen = fmt or formats[0]
    if chosen not in formats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No '{chosen}' file for this output; available: {formats}",
        )
    filename = output_artifacts.download_filename(row.title, chosen)
    headers = {"Content-Disposition": output_artifacts.content_disposition(filename)}
    media_type = output_artifacts.FORMATS[chosen]

    if chosen == output_artifacts.text_format(row) and row.content_text:
        return Response(row.content_text, media_type=media_type, headers=headers)

    path = output_artifacts.artifact_file(row, chosen)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact file is missing")
    return FileResponse(path, media_type=media_type, headers=headers)


class CitationItem(BaseModel):
    position: int
    label: str
    url: str | None
    seconds: int | None
    document_id: str | None
    source_type: str | None
    source_id: str | None
    resolved_by: str | None
    title: str | None = None
    channel_name: str | None = None


@router.get("/outputs/{output_id}/citations", response_model=list[CitationItem])
def list_output_citations(
    output_id: str,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> list[CitationItem]:
    """Every source the output cites, in order (S-6.7.3). `resolved_by` is
    null for a citation no library document matched; such a bare anchor has
    no `url`. 404 for another user's output."""
    row = output_service.get_output(db, current_user.id, output_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output not found")
    return [
        CitationItem(
            position=c.position,
            label=c.label,
            url=c.url,
            seconds=c.seconds,
            document_id=c.document_id,
            source_type=c.source_type,
            source_id=c.source_id,
            resolved_by=c.resolved_by,
            title=doc.title if doc is not None else None,
            channel_name=(doc.channel_name or None) if doc is not None else None,
        )
        for c, doc in output_citation_service.list_citations(db, row)
    ]


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


# ---------------------------------------------------------------------------
# Newsletter subscription (S-6.4.2)
# ---------------------------------------------------------------------------


class NewsletterSettings(BaseModel):
    """Every field optional: a PUT changes what it names. ``cadence`` is the
    scheduler's shape (weekly / daily / monthly with hour, minute, weekday or
    day_of_month, and an IANA timezone); ``sections`` the newsletter's."""

    title: str | None = Field(default=None, max_length=200)
    cadence: dict[str, Any] | None = None
    sections: dict[str, bool] | None = None
    enabled: bool | None = None


@router.get("/newsletter")
def get_newsletter(
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The caller's digest subscription, or ``{"subscription": null}``."""
    sub = newsletter_service.get_for(db, current_user.id)
    return {"subscription": newsletter_service.to_dict(db, sub) if sub else None}


@router.put("/newsletter")
def save_newsletter(
    payload: NewsletterSettings,
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create or update the subscription; schedules it on the scheduler
    (S-8.3.1). Turning it off disables the schedule. 400 for a bad cadence,
    an unknown section or no section at all."""
    try:
        sub = newsletter_service.save(
            db, current_user, cadence=payload.cadence, sections=payload.sections,
            enabled=payload.enabled, title=payload.title,
        )
    except newsletter_service.NewsletterError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"subscription": newsletter_service.to_dict(db, sub)}


@router.delete("/newsletter")
def delete_newsletter(
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Unsubscribe: removes the subscription and its schedule. Past issues
    stay in the outputs list."""
    sub = newsletter_service.get_for(db, current_user.id)
    if sub is None:
        return {"deleted": False}
    newsletter_service.delete(db, sub)
    return {"deleted": True}


@router.post("/newsletter/send-now")
def send_newsletter_now(
    sync: bool = Query(False, description="Deliver inside the request (tests, scripts)"),
    current_user: User = Depends(require_feature("author_studio")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Make and send an issue now, outside the schedule. It covers what is
    new since the last issue and counts as one."""
    sub = newsletter_service.get_for(db, current_user.id)
    if sub is None or not sub.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Turn the digest on first.")
    if sync:
        return newsletter_service.deliver(db, sub.id, trigger="manual")
    result = task_routing_service.dispatch_for_user(issue_newsletter, current_user, sub.id, trigger="manual")
    return {"status": "queued", "task_id": getattr(result, "id", None)}


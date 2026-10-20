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
- ``/echo/shares`` — the shares inbox (S-3.7.1): ``POST`` a link or text,
  ``POST /echo/shares/upload`` a file, ``GET`` the list, ``GET/PATCH/DELETE
  /echo/shares/{id}``, ``GET /echo/shares/{id}/file``.
- ``GET /echo/export`` — the whole brain as one zip (S-3.10.1).
- ``GET /echo/brain/footprint`` and ``DELETE /echo/brain?confirm=...`` —
  what Echo holds in every store, and the full delete (S-3.10.2).

All endpoints gated on ``require_feature("echo_personal_brain")`` —
Studio-tier-only initially.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import settings
from app.dependencies import get_db
from app.models.share import Share
from app.models.user import User
from app.services import (
    audit_service,
    echo_import_service,
    echo_intake_service,
    echo_privacy_service,
    echo_processing_service,
    echo_service,
)
from app.services.echo_import_service import ImportNotFound
from app.connectors.archive import ExportUnreadable
from app.services.echo_intake_service import InvalidShare, ShareNotFound, ShareTooLarge
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
    # Domain 3 feeder: live notes and their words (S-8.5.3). Not a gate yet.
    notes_total: int = 0
    notes_words: int = 0
    # Domain 5 feeder: items in the shares inbox (S-3.7.1). Not a gate yet.
    shares_total: int = 0


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
        notes_total=r.notes_total,
        notes_words=r.notes_words,
        shares_total=r.shares_total,
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


# S-3.2.1: `GET /echo/connectors` and the rest of the connector API live in
# `routers/echo_connectors.py`.


# ---------------------------------------------------------------------------
# Shares inbox (S-3.7.1)
# ---------------------------------------------------------------------------


class ShareFileInfo(BaseModel):
    filename: str
    mime: str
    size: int


class ShareLibraryOffer(BaseModel):
    eligible: bool = False
    reason: str | None = None
    source_type: str | None = None


class ShareProcessing(BaseModel):
    """What processing made of a share (S-3.7.2). Absent until it ran."""

    title: str | None = None
    author: str | None = None
    extractor: str | None = None
    error: str | None = None
    note: str | None = None
    embedded: bool | None = None
    processed_at: str | None = None
    library_offer: ShareLibraryOffer | None = None
    # Part 2 (media): how a file was read. `extractor` says where the
    # reading happened: ocr_local (on this machine), ocr_vision (a vision
    # model), whisper (OpenAI), pdf_text, text_file.
    ocr_confidence: float | None = None
    language: str | None = None
    duration_seconds: float | None = None
    page_count: int | None = None
    pages_with_text: int | None = None
    truncated: bool | None = None


class ShareItem(BaseModel):
    id: str
    received_at: datetime
    updated_at: datetime
    surface: str
    content_type: str
    # "url" | "text" | "file"
    kind: str
    url: str | None = None
    text: str | None = None
    file: ShareFileInfo | None = None
    user_annotation: str | None = None
    # False = someone else's words: context-only (never quoted, never in a
    # dataset or derived export). True = the user's own words.
    author_is_tenant: bool
    processing_state: str
    linked_document_id: str | None = None
    # S-3.7.2: the extracted text (any kind) and what processing found.
    extracted_text: str | None = None
    processing: ShareProcessing | None = None
    # S-3.7.5: set on shares an export import wrote. `imported` is the
    # importer's provenance (chat, sender, note title, labels, ...).
    import_id: str | None = None
    occurred_at: datetime | None = None
    imported: dict[str, Any] | None = None


class ShareListResponse(BaseModel):
    items: list[ShareItem]
    total: int
    limit: int
    offset: int


class CreateSharePayload(BaseModel):
    """Exactly one of ``url`` or ``text``. Files go to ``/echo/shares/upload``."""

    url: str | None = Field(default=None, max_length=2000)
    text: str | None = None
    annotation: str | None = None
    content_type: str | None = Field(default=None, max_length=64)
    author_is_tenant: bool = False
    surface: str = "manual_quick_share"


class UpdateSharePayload(BaseModel):
    annotation: str | None = None
    content_type: str | None = Field(default=None, max_length=64)
    author_is_tenant: bool | None = None


class ShareDeleteResponse(BaseModel):
    deleted: bool
    vectors: int
    files: int
    derived_facts: int


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _share_item(share: Share) -> ShareItem:
    payload = echo_intake_service.load_payload(share)
    kind = str(payload.get("kind", "unknown"))
    file_info = None
    if kind == "file":
        file_info = ShareFileInfo(
            filename=str(payload.get("filename") or "file"),
            mime=str(payload.get("mime") or "application/octet-stream"),
            size=int(payload.get("size") or 0),
        )
    return ShareItem(
        id=share.id,
        received_at=_aware(share.received_at),  # type: ignore[arg-type]
        updated_at=_aware(share.updated_at),  # type: ignore[arg-type]
        surface=share.surface,
        content_type=share.content_type,
        kind=kind,
        url=payload.get("url") if kind == "url" else None,
        text=share.extracted_text if kind == "text" else None,
        file=file_info,
        user_annotation=share.user_annotation,
        author_is_tenant=bool(share.author_is_tenant),
        processing_state=share.processing_state,
        linked_document_id=share.linked_document_id,
        extracted_text=share.extracted_text if kind != "text" else None,
        processing=_processing(share),
        import_id=share.import_id,
        occurred_at=_aware(share.occurred_at) if share.occurred_at else None,  # type: ignore[arg-type]
        imported=(payload.get("import") if isinstance(payload.get("import"), dict) else None),
    )


def _processing(share: Share) -> ShareProcessing | None:
    data = echo_processing_service.load_processing(share)
    if not data:
        return None
    known = {k: data.get(k) for k in ShareProcessing.model_fields if k in data}
    return ShareProcessing.model_validate(known)


def _queued(db: Session, share: Share, user: User) -> Share:
    """S-3.7.2: hand the share to processing; inline mode changes it now."""
    if echo_processing_service.enqueue(share, user) == "processed":
        db.expire(share)
        db.refresh(share)
    return share


def _invalid(e: InvalidShare) -> HTTPException:
    code = 413 if isinstance(e, ShareTooLarge) else 422
    return HTTPException(status_code=code, detail=str(e))


@router.post("/shares", response_model=ShareItem, status_code=status.HTTP_201_CREATED)
def create_share_endpoint(
    payload: CreateSharePayload,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareItem:
    has_url = bool(payload.url and payload.url.strip())
    has_text = bool(payload.text and payload.text.strip())
    if has_url == has_text:
        raise HTTPException(status_code=422, detail="send exactly one of url or text")
    common = dict(
        annotation=payload.annotation,
        content_type=payload.content_type,
        author_is_tenant=payload.author_is_tenant,
        surface=payload.surface,
    )
    try:
        if has_url:
            share = echo_intake_service.create_url_share(
                db, current_user.id, current_user.id, url=payload.url or "", **common
            )
        else:
            share = echo_intake_service.create_text_share(
                db, current_user.id, current_user.id, text=payload.text or "", **common
            )
    except InvalidShare as e:
        raise _invalid(e)
    return _share_item(_queued(db, share, current_user))


@router.post("/shares/upload", response_model=ShareItem, status_code=status.HTTP_201_CREATED)
async def upload_share_endpoint(
    file: UploadFile = File(...),
    annotation: str | None = Form(None),
    content_type: str | None = Form(None),
    author_is_tenant: bool = Form(False),
    surface: str = Form("manual_quick_share"),
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareItem:
    # Read one byte past the cap so an oversized upload is refused without
    # holding more than the cap in memory.
    data = await file.read(settings.ECHO_SHARE_MAX_BYTES + 1)
    try:
        share = echo_intake_service.create_file_share(
            db,
            current_user.id,
            current_user.id,
            filename=file.filename or "file",
            data=data,
            mime=file.content_type,
            annotation=annotation,
            content_type=content_type or None,
            author_is_tenant=author_is_tenant,
            surface=surface,
        )
    except InvalidShare as e:
        raise _invalid(e)
    return _share_item(_queued(db, share, current_user))


@router.get("/shares", response_model=ShareListResponse)
def list_shares_endpoint(
    state: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    origin: str = Query("direct", pattern="^(direct|import|all)$"),
    import_id: str | None = Query(None, max_length=36),
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareListResponse:
    """``origin``: ``direct`` (the default: shares handed over one at a
    time), ``import`` (written by export imports) or ``all``. ``import_id``
    lists one import's shares in the order they were written."""
    try:
        page, total = echo_intake_service.list_shares(
            db, current_user.id, state=state, q=q, limit=limit, offset=offset,
            origin=origin, import_id=import_id,
        )
    except InvalidShare as e:
        raise _invalid(e)
    return ShareListResponse(
        items=[_share_item(s) for s in page], total=total, limit=limit, offset=offset
    )


@router.get("/shares/{share_id}", response_model=ShareItem)
def get_share_endpoint(
    share_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareItem:
    try:
        return _share_item(echo_intake_service.get_share(db, current_user.id, share_id))
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="Share not found")


@router.patch("/shares/{share_id}", response_model=ShareItem)
def update_share_endpoint(
    share_id: str,
    payload: UpdateSharePayload,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareItem:
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("content_type") is None:
        fields.pop("content_type", None)
    if fields.get("author_is_tenant") is None:
        fields.pop("author_is_tenant", None)
    try:
        share = echo_intake_service.update_share(db, current_user.id, share_id, **fields)
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="Share not found")
    except InvalidShare as e:
        raise _invalid(e)
    return _share_item(share)


@router.delete("/shares/{share_id}", response_model=ShareDeleteResponse)
def delete_share_endpoint(
    share_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareDeleteResponse:
    try:
        result = echo_intake_service.delete_share(db, current_user.id, share_id)
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="Share not found")
    return ShareDeleteResponse(
        deleted=True,
        vectors=result.vectors,
        files=result.files,
        derived_facts=result.derived_facts,
    )


@router.post("/shares/{share_id}/process", response_model=ShareItem)
def reprocess_share_endpoint(
    share_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareItem:
    """S-3.7.2: queue the share for processing again ("Retry" in the inbox).
    Processing is idempotent: it re-derives everything from what arrived."""
    try:
        share = echo_intake_service.get_share(db, current_user.id, share_id)
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="Share not found")
    return _share_item(_queued(db, share, current_user))


@router.post("/shares/{share_id}/library", response_model=ShareItem)
def add_share_to_library_endpoint(
    share_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ShareItem:
    """S-3.7.2: the library offer. Ingests a shared link through the same path
    as the library's "Paste URLs" (so it is deduplicated and visible to the
    sharer only, D-063) and links the share to the document. Only for links
    processing marked eligible; videos enter the library through a research
    run."""
    try:
        share = echo_intake_service.get_share(db, current_user.id, share_id)
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="Share not found")
    offer = (echo_processing_service.load_processing(share).get("library_offer") or {})
    payload = echo_intake_service.load_payload(share)
    if payload.get("kind") != "url" or not offer.get("eligible"):
        raise HTTPException(
            status_code=409,
            detail=offer.get("reason") or "This share cannot be added to the library.",
        )
    if share.linked_document_id:
        return _share_item(share)

    from app.routers.library import _ingest_single_paste_url

    result = _ingest_single_paste_url(payload.get("url") or "", db, current_user)
    if result.get("status") not in ("created", "deduped") or not result.get("document_id"):
        raise HTTPException(
            status_code=422,
            detail="The page could not be extracted for the library. It stays in your inbox.",
        )
    share.linked_document_id = result["document_id"]
    db.commit()
    db.refresh(share)
    return _share_item(share)


@router.get("/shares/{share_id}/file")
def download_share_file_endpoint(
    share_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        share = echo_intake_service.get_share(db, current_user.id, share_id)
    except ShareNotFound:
        raise HTTPException(status_code=404, detail="Share not found")
    if not share.file_path:
        raise HTTPException(status_code=404, detail="This share has no file")
    try:
        path = echo_intake_service.resolve_share_file(share.file_path, current_user.id)
    except InvalidShare:
        raise HTTPException(status_code=404, detail="The file is missing on disk")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The file is missing on disk")
    payload = echo_intake_service.load_payload(share)
    # Always an attachment and never sniffed: an uploaded HTML or SVG must
    # not render on the API origin.
    return FileResponse(
        path,
        media_type=str(payload.get("mime") or "application/octet-stream"),
        filename=str(payload.get("filename") or path.name),
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


# ---------------------------------------------------------------------------
# Privacy: full export and full delete (S-3.10.1, S-3.10.2)
# ---------------------------------------------------------------------------


class FootprintResponse(BaseModel):
    rows: dict[str, int]
    files: int
    vectors: dict[str, int]


class BrainDeleteResponse(BaseModel):
    deleted: bool
    removed: FootprintResponse
    footprint_after: FootprintResponse


# What the client must send to delete the whole brain. A query parameter
# rather than a body so no client library drops it on DELETE.
BRAIN_DELETE_CONFIRMATION = "delete-everything"


@router.get("/export")
def export_brain_endpoint(
    request: Request,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Everything Echo holds for the caller as one zip: a manifest, one JSONL
    per table, and the files. Built in a temporary file (constant memory) and
    removed after it is sent."""
    path, manifest = echo_privacy_service.build_archive_file(db, current_user.id)
    audit_service.record(
        db,
        event=audit_service.Event.ECHO_EXPORTED,
        user_id=current_user.id,
        request=request,
        metadata={
            "rows": {k: v["rows"] for k, v in manifest["tables"].items()},
            "files": len(manifest["files"]),
            "missing_files": len(manifest["missing_files"]),
        },
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"echo-export-{stamp}.zip",
        background=BackgroundTask(os.unlink, path),
    )


@router.get("/brain/footprint", response_model=FootprintResponse)
def brain_footprint_endpoint(
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> FootprintResponse:
    return FootprintResponse(**echo_privacy_service.footprint(db, current_user.id))


@router.delete("/brain", response_model=BrainDeleteResponse)
def delete_brain_endpoint(
    request: Request,
    confirm: str = Query(..., description="Must be 'delete-everything'."),
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> BrainDeleteResponse:
    """Delete every Echo row, file and vector the caller owns. Irreversible;
    export first. ``footprint_after`` is all zeros, or the call fails with
    500 and says what is left."""
    if confirm != BRAIN_DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=400, detail=f"confirm must be '{BRAIN_DELETE_CONFIRMATION}'"
        )
    try:
        result = echo_privacy_service.delete_brain(db, current_user.id)
    except echo_privacy_service.EchoPrivacyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    audit_service.record(
        db,
        event=audit_service.Event.ECHO_BRAIN_DELETED,
        user_id=current_user.id,
        request=request,
        metadata={"removed": result["removed"]},
    )
    return BrainDeleteResponse(
        deleted=True,
        removed=FootprintResponse(**result["removed"]),
        footprint_after=FootprintResponse(**result["footprint_after"]),
    )


# ---------------------------------------------------------------------------
# Export-file imports (S-3.7.5)
# ---------------------------------------------------------------------------


class ImportParticipant(BaseModel):
    name: str
    messages: int


class ImportPreviewResponse(BaseModel):
    importer: str
    label: str
    summary: dict[str, Any]
    participants: list[ImportParticipant]
    options: dict[str, Any]
    warnings: list[str]


class ImportItem(BaseModel):
    id: str
    importer: str
    filename: str
    # importing | embedding | done | failed | deleting
    status: str
    options: dict[str, Any]
    counts: dict[str, Any]
    summary: dict[str, Any]
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class ImportListResponse(BaseModel):
    items: list[ImportItem]


class ImportDeleteResponse(BaseModel):
    deleted: bool
    shares: int
    vectors: int
    facts: int


def _import_item(record) -> ImportItem:
    def _json(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw) if raw else {}
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    return ImportItem(
        id=record.id,
        importer=record.importer,
        filename=record.filename,
        status=record.status,
        options=_json(record.options_json),
        counts=_json(record.counts_json),
        summary=_json(record.summary_json),
        error=record.error,
        created_at=_aware(record.created_at),  # type: ignore[arg-type]
        finished_at=_aware(record.finished_at) if record.finished_at else None,  # type: ignore[arg-type]
    )


def _import_upload(file: UploadFile, options: str | None) -> tuple[Any, dict[str, Any]]:
    """The spooled upload (never stored) and the parsed options object."""
    fh = file.file
    fh.seek(0, os.SEEK_END)
    size = fh.tell()
    fh.seek(0)
    if size == 0:
        raise HTTPException(status_code=422, detail="The file is empty.")
    if size > settings.ECHO_IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Exports up to {settings.ECHO_IMPORT_MAX_BYTES // (1024 * 1024)} MB can be imported here.",
        )
    try:
        opts = json.loads(options) if options else {}
    except ValueError:
        raise HTTPException(status_code=422, detail="options must be a JSON object")
    if not isinstance(opts, dict):
        raise HTTPException(status_code=422, detail="options must be a JSON object")
    return fh, opts


@router.post("/import/preview", response_model=ImportPreviewResponse)
def import_preview_endpoint(
    file: UploadFile = File(...),
    importer: str | None = Form(None),
    options: str | None = Form(None),
    current_user: User = Depends(require_feature("echo_personal_brain")),
) -> ImportPreviewResponse:
    """What importing this file would produce. Writes nothing."""
    fh, opts = _import_upload(file, options)
    try:
        pv = echo_import_service.preview(fh, file.filename or "upload", importer=importer, options=opts)
    except ExportUnreadable as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ImportPreviewResponse(
        importer=pv.importer,
        label=pv.label,
        summary=pv.summary,
        participants=[ImportParticipant(name=p["name"], messages=p["messages"]) for p in pv.participants],
        options=pv.options,
        warnings=pv.warnings,
    )


@router.post("/import", response_model=ImportItem, status_code=status.HTTP_201_CREATED)
def import_endpoint(
    file: UploadFile = File(...),
    importer: str | None = Form(None),
    options: str | None = Form(None),
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ImportItem:
    """Import an export file as shares (``surface=file_import``). The upload
    itself is not kept; embedding follows like share processing."""
    fh, opts = _import_upload(file, options)
    try:
        record = echo_import_service.run_import(
            db, current_user, fh, file.filename or "upload", importer=importer, options=opts
        )
    except ExportUnreadable as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _import_item(record)


@router.get("/imports", response_model=ImportListResponse)
def list_imports_endpoint(
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ImportListResponse:
    return ImportListResponse(items=[_import_item(r) for r in echo_import_service.list_imports(db, current_user.id)])


@router.get("/imports/{import_id}", response_model=ImportItem)
def get_import_endpoint(
    import_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ImportItem:
    try:
        return _import_item(echo_import_service.get_import(db, current_user.id, import_id))
    except ImportNotFound:
        raise HTTPException(status_code=404, detail="Import not found")


@router.post("/imports/{import_id}/embed", response_model=ImportItem)
def retry_import_embedding_endpoint(
    import_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ImportItem:
    """Embed whatever of this import is still pending (Retry after a failure)."""
    try:
        record = echo_import_service.get_import(db, current_user.id, import_id)
    except ImportNotFound:
        raise HTTPException(status_code=404, detail="Import not found")
    if record.status in ("importing", "deleting"):
        raise HTTPException(status_code=409, detail=f"This import is {record.status}.")
    record.status = "embedding"
    record.error = None
    db.commit()
    echo_import_service.enqueue_embedding(db, record, current_user)
    db.refresh(record)
    return _import_item(record)


@router.delete("/imports/{import_id}", response_model=ImportDeleteResponse)
def delete_import_endpoint(
    import_id: str,
    current_user: User = Depends(require_feature("echo_personal_brain")),
    db: Session = Depends(get_db),
) -> ImportDeleteResponse:
    """Undo an import: every share it wrote, their vectors and anything
    derived from them, then the import itself."""
    try:
        result = echo_import_service.delete_import(db, current_user.id, import_id)
    except ImportNotFound:
        raise HTTPException(status_code=404, detail="Import not found")
    return ImportDeleteResponse(deleted=True, **result)

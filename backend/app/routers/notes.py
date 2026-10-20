"""Notes API (M5 / S-8.5.1) — ``/api/v1/notes``.

    GET    /notes?target=document:<id>      notes on one target (either document id form)
    GET    /notes?target_type=job&q=…       the tenant's notes, filtered, newest first
    POST   /notes                           write a note (target checked through visibility)
    GET    /notes/{id}
    PUT    /notes/{id}                      partial update
    DELETE /notes/{id}                      soft delete

Every response row carries ``target_label`` and, for document-backed
targets, ``target_video_id`` — see ``schemas/note.py``. Missing and foreign
are the same 404.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.note import Note
from app.models.user import User
from app.schemas.note import (
    NoteCreate,
    NoteDeleteResponse,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
    Selector,
)
from app.services import note_index, note_service
from app.services.note_service import (
    TARGET_TYPES,
    InvalidNote,
    NoteNotFound,
    NoteTargetNotFound,
    ResolvedTarget,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notes",
    tags=["notes"],
    dependencies=[Depends(get_current_user)],
)

_LIST_LIMIT_MAX = 2000


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands naive datetimes back; they were written as UTC. Say so, so
    the JSON carries an offset and a browser does not read them as local."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _to_response(
    note: Note, target: ResolvedTarget | None
) -> NoteResponse:
    selector = note_service.load_selector(note.selector_json)
    return NoteResponse(
        id=note.id,
        target_type=note.target_type,  # type: ignore[arg-type]
        target_id=note.target_id,
        body_md=note.body_md,
        motivation=note.motivation,  # type: ignore[arg-type]
        selector=Selector.model_validate(selector) if selector else None,
        created_at=_aware(note.created_at),  # type: ignore[arg-type]
        updated_at=_aware(note.updated_at),  # type: ignore[arg-type]
        deleted_at=_aware(note.deleted_at),
        target_label=target.label if target else None,
        target_video_id=target.video_id if target else None,
        target_parent_id=target.parent_id if target else None,
    )


def _responses(db: Session, notes: list[Note]) -> list[NoteResponse]:
    summaries = note_service.describe_targets(db, notes)
    return [_to_response(n, summaries.get((n.target_type, n.target_id))) for n in notes]


def _parse_target(target: str) -> tuple[str, str]:
    """``document:abc`` → ``("document", "abc")``. 422 on anything else."""
    kind, sep, ident = target.partition(":")
    if not sep or kind not in TARGET_TYPES or not ident.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "target must be <target_type>:<id> with target_type one of "
                + ", ".join(sorted(TARGET_TYPES))
            ),
        )
    return kind, ident.strip()


@router.get("", response_model=NoteListResponse)
def list_notes(
    target: str | None = Query(
        None, description="Scope to one target, e.g. document:<id> or job:<id>."
    ),
    target_type: str | None = Query(None),
    q: str | None = Query(None, max_length=200, description="Substring filter on the body."),
    include_deleted: bool = Query(False),
    limit: int = Query(500, ge=1, le=_LIST_LIMIT_MAX),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteListResponse:
    kind = target_type
    ident: str | None = None
    if target is not None:
        kind, raw = _parse_target(target)
        try:
            ident = note_service.resolve_target(db, current_user.id, kind, raw).target_id
        except NoteTargetNotFound:
            raise HTTPException(status_code=404, detail="Target not found")
    if kind is not None and kind not in TARGET_TYPES:
        raise HTTPException(
            status_code=422,
            detail="unknown target_type",
        )
    page, total = note_service.list_notes(
        db,
        current_user.id,
        target_type=kind,
        target_id=ident,
        q=q,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return NoteListResponse(
        items=_responses(db, page), total=total, limit=limit, offset=offset
    )


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteResponse:
    try:
        note = note_service.create_note(
            db,
            current_user.id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            body_md=payload.body_md,
            motivation=payload.motivation,
            selector=payload.selector.model_dump(exclude_none=True)
            if payload.selector
            else None,
        )
    except NoteTargetNotFound:
        raise HTTPException(status_code=404, detail="Target not found")
    except InvalidNote as e:
        raise HTTPException(status_code=422, detail=str(e))
    # S-8.5.2: best-effort; never fails the write (startup backfill repairs).
    note_index.sync_note(db, note)
    return _responses(db, [note])[0]


@router.get("/{note_id}", response_model=NoteResponse)
def get_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteResponse:
    try:
        note = note_service.get_note(db, current_user.id, note_id)
    except NoteNotFound:
        raise HTTPException(status_code=404, detail="Note not found")
    return _responses(db, [note])[0]


@router.put("/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: str,
    payload: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteResponse:
    fields = payload.model_dump(exclude_unset=True)
    kwargs: dict = {}
    if "body_md" in fields:
        kwargs["body_md"] = fields["body_md"]
    if "motivation" in fields:
        kwargs["motivation"] = fields["motivation"]
    if "selector" in fields:
        kwargs["selector"] = (
            payload.selector.model_dump(exclude_none=True) if payload.selector else None
        )
    try:
        note = note_service.update_note(db, current_user.id, note_id, **kwargs)
    except NoteNotFound:
        raise HTTPException(status_code=404, detail="Note not found")
    except InvalidNote as e:
        raise HTTPException(status_code=422, detail=str(e))
    note_index.sync_note(db, note)  # S-8.5.2: re-embed the edited text
    return _responses(db, [note])[0]


@router.delete("/{note_id}", response_model=NoteDeleteResponse)
def delete_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteDeleteResponse:
    try:
        note = note_service.delete_note(db, current_user.id, note_id)
    except NoteNotFound:
        raise HTTPException(status_code=404, detail="Note not found")
    note_index.remove_note(note.id)  # S-8.5.2: a withdrawn note leaves retrieval
    return NoteDeleteResponse(deleted=True, deleted_at=_aware(note.deleted_at))  # type: ignore[arg-type]

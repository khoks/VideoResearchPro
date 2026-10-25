"""Fine-tune dataset export endpoints.

Streams JSONL files over HTTP. Each endpoint yields one row per DB record in
constant memory — users download the file, then feed it to the OpenAI or
Gemini fine-tune API externally so the fine-tuned model carries their
personal wiki as parametric knowledge.

Four endpoints, two datasets × two formats:
  GET /api/v1/exports/qa-dataset/openai.jsonl
  GET /api/v1/exports/qa-dataset/tuple.jsonl
  GET /api/v1/exports/knowledge-dataset/openai.jsonl
  GET /api/v1/exports/knowledge-dataset/tuple.jsonl

Plus the user's own notes (S-8.5.3), which are not fine-tune data but the
user's words leaving the system in a form they can keep:
  GET /api/v1/exports/notes.jsonl   W3C Web Annotation JSON-LD, lossless
  GET /api/v1/exports/notes.md      readable, grouped by target

Auth: header-bearer JWT only. Until T-8.8.1.5 (2026-10-25) these routes also
took ``?token=`` because a plain ``<a download>`` cannot set an Authorization
header; a token in a URL leaks into history, logs and Referer headers, so the
frontend now fetches the file with the header and saves it from a blob: URL
(``services/apiFiles.ts``, D-085 addendum).
"""
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.services import dataset_service, note_export_service

logger = logging.getLogger(__name__)

_MEDIA_TYPE = "application/x-ndjson"

router = APIRouter(
    prefix="/exports",
    tags=["exports"],
)

# S-5.7.1: the router-level dependency only proved you were logged in; every
# endpoint then streamed EVERY tenant's data. The user is now bound per
# endpoint so the identity actually reaches the query layer.


def _attachment(filename: str) -> dict[str, str]:
    """Content-Disposition header so the browser saves with a meaningful name."""
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/qa-dataset/openai.jsonl")
def export_qa_openai(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_qa_openai(db, current_user.id),
        media_type=_MEDIA_TYPE,
        headers=_attachment("qa-dataset-openai.jsonl"),
    )


@router.get("/qa-dataset/tuple.jsonl")
def export_qa_tuple(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_qa_tuple(db, current_user.id),
        media_type=_MEDIA_TYPE,
        headers=_attachment("qa-dataset-tuple.jsonl"),
    )


@router.get("/knowledge-dataset/openai.jsonl")
def export_knowledge_openai(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_knowledge_openai(db, current_user.id),
        media_type=_MEDIA_TYPE,
        headers=_attachment("knowledge-dataset-openai.jsonl"),
    )


@router.get("/knowledge-dataset/tuple.jsonl")
def export_knowledge_tuple(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_knowledge_tuple(db, current_user.id),
        media_type=_MEDIA_TYPE,
        headers=_attachment("knowledge-dataset-tuple.jsonl"),
    )


@router.get("/notes.jsonl")
def export_notes_jsonld(
    include_deleted: bool = Query(
        True, description="Withdrawn notes too, with their `deleted` timestamp."
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    """Every note as a W3C Web Annotation, one JSON-LD object per line,
    oldest first. Lossless: `note_export_service.parse_note_jsonld` is the
    exact inverse."""
    return StreamingResponse(
        note_export_service.stream_notes_jsonld(
            db, current_user.id, include_deleted=include_deleted
        ),
        media_type=_MEDIA_TYPE,
        headers=_attachment("notes.jsonl"),
    )


@router.get("/notes.md")
def export_notes_markdown(
    include_deleted: bool = Query(True),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    """The same notes as a Markdown document grouped by target type and
    target, every note dated."""
    return StreamingResponse(
        note_export_service.stream_notes_markdown(
            db, current_user.id, include_deleted=include_deleted
        ),
        media_type="text/markdown; charset=utf-8",
        headers=_attachment("notes.md"),
    )

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

Auth: header-bearer JWT is preferred. ?token= query fallback is also
accepted because browser-initiated downloads (``window.location.href = url``,
``<a download>``) cannot set an Authorization header — same pattern used for
the HTML report download in ``routers/qa.py``.
"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_user_from_query_or_header
from app.services import dataset_service

logger = logging.getLogger(__name__)

_MEDIA_TYPE = "application/x-ndjson"

router = APIRouter(
    prefix="/exports",
    tags=["exports"],
    # All four endpoints are read-only downloads — query-token fallback is OK.
    dependencies=[Depends(get_user_from_query_or_header)],
)


def _attachment(filename: str) -> dict[str, str]:
    """Content-Disposition header so the browser saves with a meaningful name."""
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/qa-dataset/openai.jsonl")
def export_qa_openai(db: Session = Depends(get_db)) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_qa_openai(db),
        media_type=_MEDIA_TYPE,
        headers=_attachment("qa-dataset-openai.jsonl"),
    )


@router.get("/qa-dataset/tuple.jsonl")
def export_qa_tuple(db: Session = Depends(get_db)) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_qa_tuple(db),
        media_type=_MEDIA_TYPE,
        headers=_attachment("qa-dataset-tuple.jsonl"),
    )


@router.get("/knowledge-dataset/openai.jsonl")
def export_knowledge_openai(db: Session = Depends(get_db)) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_knowledge_openai(db),
        media_type=_MEDIA_TYPE,
        headers=_attachment("knowledge-dataset-openai.jsonl"),
    )


@router.get("/knowledge-dataset/tuple.jsonl")
def export_knowledge_tuple(db: Session = Depends(get_db)) -> StreamingResponse:
    return StreamingResponse(
        dataset_service.stream_knowledge_tuple(db),
        media_type=_MEDIA_TYPE,
        headers=_attachment("knowledge-dataset-tuple.jsonl"),
    )

"""The library's document filters as one query builder (S-8.1.4).

``routers/library.py::query_library_documents`` (the listing: library page,
shelf page, channel page) and ``qa_scope_service.resolve_document_ids`` (what a
scoped question may retrieve) both start here, so a shelf means the same
documents in its list and in its answers (D-083). Every query is inside the
tenant's visible set (D-063 / D-070).
"""
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models.channel import Channel
from app.models.document import Document
from app.models.job_video import JobVideo
from app.services import tag_service, visibility_service


def documents_query(
    db: Session,
    tenant_id: str,
    *,
    job_ids: list[str] | None = None,
    search: str | None = None,
    language: str | None = None,
    channel_id: str | None = None,
    transcript_status: str | None = None,
    tag_id: str | None = None,
    document_id: str | None = None,
) -> Query | None:
    """Visible documents matching the filters, unordered and unpaged.

    Returns ``None`` when the scope is empty by construction: ``job_ids=[]``
    means "the documents of no runs", which is nothing, never everything.
    """
    if job_ids is not None and not job_ids:
        return None

    q = (
        db.query(Document)
        .outerjoin(Channel, Document.channel_id == Channel.channel_id)
        .filter(Document.document_id.in_(visibility_service.visible_document_ids(db, tenant_id)))
    )
    if job_ids is not None:
        q = q.filter(
            Document.document_id.in_(
                db.query(JobVideo.document_id).filter(JobVideo.job_id.in_(job_ids))
            )
        )
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Document.title.ilike(like), Channel.name.ilike(like)))
    if language:
        q = q.filter(Document.transcript_language == language)
    if channel_id:
        q = q.filter(Document.channel_id == channel_id)
    if transcript_status:
        q = q.filter(Document.transcript_status == transcript_status)
    if document_id:
        # S-8.2.2: a palette result lands on its one row
        # (`/library?document=<id>`). Inside the visibility scope above, so
        # another tenant's id matches nothing.
        q = q.filter(Document.document_id == document_id)
    if tag_id:
        # The tenant is part of the subquery, so another reader's tag id
        # matches nothing rather than revealing what they tagged.
        q = q.filter(
            Document.document_id.in_(tag_service.tagged_document_ids(db, tenant_id, tag_id))
        )
    return q


def document_ids(db: Session, tenant_id: str, **filters) -> list[str]:
    """Every matching document id, sorted (no page). Empty means nothing."""
    q = documents_query(db, tenant_id, **filters)
    if q is None:
        return []
    return sorted({row[0] for row in q.with_entities(Document.document_id).all()})

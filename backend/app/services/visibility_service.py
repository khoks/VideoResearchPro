"""Granting and querying per-tenant visibility over the shared document cache.

S-5.7.1 / D-063 — shared cache, private catalogue. Every ingest path must call
``grant`` so the ingesting tenant can see what they ingested. A path that
forgets produces a document nobody can see, which is the safe failure
direction but still a bug — the tests assert every path grants.

D-070 (2026-10-19): grants are keyed on ``documents.document_id``, the one
identifier every source type has. The first version keyed them on the legacy
``documents.video_id``, which is NULL for every non-video source, so
``grant(db, [doc.video_id], ...)`` was a silent no-op for PDFs and pasted
pages and ``visible_video_ids`` could never list them. There is deliberately
no ``visible_video_ids`` shim: no reader needs YouTube ids — the listing,
the channel views and the Chroma retrieval filter all key on ``document_id``.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.document_visibility import DocumentVisibility

logger = logging.getLogger(__name__)

# Which ingest path claimed the document. Kept as a small closed set so a
# missing grant is greppable by source.
SOURCE_JOB = "job"
SOURCE_PDF = "pdf_upload"
SOURCE_PASTE = "paste_url"
SOURCE_CHANNEL = "channel_sync"


def grant(
    db: Session,
    document_ids: Iterable[str],
    tenant_id: str | None,
    source: str = SOURCE_JOB,
) -> int:
    """Grant ``tenant_id`` visibility over ``document_ids``. Idempotent.

    ``document_ids`` are ``documents.document_id`` values — never the legacy
    YouTube id, which does not exist for most source types.

    Returns the number of NEW grants written. Best-effort: a visibility write
    must never fail an ingest that otherwise succeeded — a missing grant hides
    a document, which is recoverable; a failed ingest loses work.
    """
    ids = [d for d in dict.fromkeys(document_ids) if d]
    if not ids or not tenant_id:
        return 0
    try:
        existing = {
            row[0]
            for row in db.query(DocumentVisibility.document_id).filter(
                DocumentVisibility.tenant_id == tenant_id,
                DocumentVisibility.document_id.in_(ids),
            )
        }
        new = [d for d in ids if d not in existing]
        if not new:
            return 0
        db.bulk_save_objects(
            [
                DocumentVisibility(document_id=d, tenant_id=tenant_id, source=source)
                for d in new
            ]
        )
        db.commit()
        logger.info(
            "visibility: granted %d document(s) to tenant %s via %s",
            len(new), tenant_id[:8], source,
        )
        return len(new)
    except Exception:
        logger.exception(
            "visibility: grant failed for tenant %s (%s); ingest continues",
            tenant_id, source,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def visible_document_ids(db: Session, tenant_id: str):
    """Subquery of the ``document_id`` values ``tenant_id`` may see.

    Returned as a query (not a materialised list) so callers compose it into
    an ``IN`` clause without pulling ids into Python. Callers that need the
    list (library Q&A hands it to Chroma) iterate it; an EMPTY result means
    "this tenant has ingested nothing" and must retrieve nothing.
    """
    return db.query(DocumentVisibility.document_id).filter(
        DocumentVisibility.tenant_id == tenant_id
    )


def visible_document(db: Session, tenant_id: str, raw_id: str):
    """The document ``raw_id`` names, if ``tenant_id`` may see it; else None.

    ``raw_id`` may be the primary key (``document_id``) or the legacy YouTube
    id (``video_id``) — URL paths written before E-1.10 still carry the
    latter. Callers turn ``None`` into a 404 so a document that exists but
    belongs to someone else is indistinguishable from one that does not
    exist (the T-5.10.1.4 rule). One query.
    """
    from app.models.document import Document

    if not raw_id or not tenant_id:
        return None
    return (
        db.query(Document)
        .filter(
            or_(Document.document_id == raw_id, Document.video_id == raw_id),
            Document.document_id.in_(visible_document_ids(db, tenant_id)),
        )
        .first()
    )

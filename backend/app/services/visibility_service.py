"""Granting and querying per-tenant visibility over the shared document cache.

S-5.7.1 / D-063 — shared cache, private catalogue. Every ingest path must call
``grant`` so the ingesting tenant can see what they ingested. A path that
forgets produces a document nobody can see, which is the safe failure
direction but still a bug — the tests assert every path grants.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

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
    video_ids: Iterable[str],
    tenant_id: str | None,
    source: str = SOURCE_JOB,
) -> int:
    """Grant ``tenant_id`` visibility over ``video_ids``. Idempotent.

    Returns the number of NEW grants written. Best-effort: a visibility write
    must never fail an ingest that otherwise succeeded — a missing grant hides
    a document, which is recoverable; a failed ingest loses work.
    """
    ids = [v for v in dict.fromkeys(video_ids) if v]
    if not ids or not tenant_id:
        return 0
    try:
        existing = {
            row[0]
            for row in db.query(DocumentVisibility.video_id).filter(
                DocumentVisibility.tenant_id == tenant_id,
                DocumentVisibility.video_id.in_(ids),
            )
        }
        new = [v for v in ids if v not in existing]
        if not new:
            return 0
        db.bulk_save_objects(
            [
                DocumentVisibility(video_id=v, tenant_id=tenant_id, source=source)
                for v in new
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


def visible_video_ids(db: Session, tenant_id: str):
    """Subquery of the video_ids ``tenant_id`` may see.

    Returned as a query (not a materialised list) so callers compose it into
    an ``IN`` clause without pulling ids into Python.
    """
    return db.query(DocumentVisibility.video_id).filter(
        DocumentVisibility.tenant_id == tenant_id
    )

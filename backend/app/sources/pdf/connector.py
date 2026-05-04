"""PDF connector — exposes the BaseConnector contract for ``source_type='pdf'``.

PDFs come from upload, not search/discovery. The connector's
discovery methods raise NotImplementedError per the BaseConnector
contract (the dispatcher's `dispatch_search` handles this gracefully
per [D-026](../../../docs/decisions.md#d-026--sequential-fan-out-for-the-connector-dispatcher-2026-05-02)
— treats as zero candidates, not an error).

The connector's load-bearing method is `fetch_text(candidate)` which
reads the upload-stored PDF bytes and runs them through PyMuPDF via
the flatten module.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from typing import Iterator

from app.config import settings
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.pdf import flatten as pdf_flatten
from app.sources.types import Candidate, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)

SOURCE_TYPE = "pdf"
SOURCE_ID_PREFIX = "pdf:"


def _strip_prefix(source_id: str) -> str:
    if source_id.startswith(SOURCE_ID_PREFIX):
        return source_id[len(SOURCE_ID_PREFIX) :]
    return source_id


def hash_pdf_bytes(pdf_bytes: bytes) -> str:
    """Stable identifier for a PDF — SHA-256 of the first 64KB.

    Hashing the first 64KB rather than the full file:
    - is fast for very large PDFs (academic books, technical manuals
      can run 50-200MB).
    - is enough for collision avoidance in practice (PDF headers +
      object table content in the first 64KB are highly file-specific).
    - dedups identical files even when trailing trailer metadata
      differs (e.g. timestamp-based linearization markers).

    Returns a 64-char hex digest.
    """
    head = pdf_bytes[: 64 * 1024]
    return hashlib.sha256(head).hexdigest()


def upload_path_for_source_id(source_id: str) -> str:
    """Return the on-disk path where the raw PDF for ``source_id`` lives.

    Source ID is the namespaced ``pdf:<hash>`` form; we strip the
    prefix and append `.pdf`. The upload directory is configured via
    ``PDF_UPLOAD_DIR`` (default ``./data/uploads/pdf``) and is
    created lazily — not the connector's job to manage.
    """
    bare = _strip_prefix(source_id)
    return os.path.join(settings.PDF_UPLOAD_DIR, f"{bare}.pdf")


class PDFConnector(BaseConnector):
    """`BaseConnector` for ``source_type='pdf'``."""

    source_type = SOURCE_TYPE

    # ------------------------------------------------------------------
    # Discovery — not supported (PDFs come from upload, not search)
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        raise NotImplementedError(
            "PDF connector has no search surface — PDFs are ingested via upload"
        )

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        raise NotImplementedError(
            "PDF connector has no creator concept — PDFs are uploaded directly"
        )

    # ------------------------------------------------------------------
    # Enrichment — pass-through (the upload endpoint already wrote the
    # full metadata into Document.source_metadata_json)
    # ------------------------------------------------------------------
    def fetch_metadata(
        self,
        source_ids: list[str],
        *,
        job_id: str = "",
    ) -> dict[str, SourceMetadata]:
        return {}

    # ------------------------------------------------------------------
    # Text payload
    # ------------------------------------------------------------------
    def fetch_text(
        self,
        candidate: Candidate,
        *,
        job_id: str = "",
        query: str = "",
    ) -> ExtractedText | None:
        """Read the upload-stored PDF and extract per-page segments.

        The candidate's `source_url` is expected to be a URL where
        the PDF can be re-served — typically the upload endpoint's
        path. We pass it through to `flatten_pdf` so per-page
        `comment_url` carries `#page=<N>` fragments for citation
        deep-links in standard PDF viewers.

        Fail-soft: missing file / unreadable bytes / corrupt PDF
        all return None with an INFO log.
        """
        path = upload_path_for_source_id(candidate.source_id)
        if not os.path.exists(path):
            logger.warning(
                "PDF fetch_text: upload missing for %s (expected at %s)",
                candidate.source_id,
                path,
                extra={"job_id": job_id},
            )
            return None

        try:
            with open(path, "rb") as f:
                pdf_bytes = f.read()
        except OSError as e:
            logger.warning(
                "PDF fetch_text: read failed for %s: %s",
                path,
                e,
                extra={"job_id": job_id},
            )
            return None

        document_url = candidate.source_url or ""
        segments = pdf_flatten.flatten_pdf(
            pdf_bytes, candidate.source_id, document_url=document_url
        )
        if not segments:
            return None

        word_count = sum(len(seg.get("text", "").split()) for seg in segments)
        # PDF language detection is hard without an LLM — most academic
        # PDFs are English; multilingual PDFs would need a per-page
        # detector. Default to "en" and let downstream multilingual
        # embedder handle the rest. (`paraphrase-multilingual-MiniLM`
        # works on every language we ingest.)
        language = (candidate.extra.get("language") if candidate.extra else None) or "en"

        return ExtractedText(
            segments=segments,
            language=language,
            text_source="pdf",
            word_count=word_count,
            extra={
                "page_count": (
                    segments[-1].get("extra", {}).get("total_pages")
                    if segments
                    else 0
                ),
            },
        )


# Eager registration.
_INSTANCE = PDFConnector()
registry.register(_INSTANCE)

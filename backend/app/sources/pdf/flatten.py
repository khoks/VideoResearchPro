"""Flatten a PDF document into chunkable text segments — one per page.

Uses PyMuPDF (`fitz`) to extract per-page text. Tables are
extracted via PyMuPDF's `page.find_tables()` and joined into the
page text with `[TABLE]` markers so the chunker treats them as
continuous prose. (Future enhancement: emit tables as separate
segments with `extra.kind="table"` so they get their own
chunks — better retrieval for tabular content. For now we keep
them inline to avoid regressing on table-heavy academic papers.)

Page numbers are 1-indexed in segment `extra` for human-readable
citations.

Pseudo-timestamps follow the same 3-words-per-second convention as
the social connectors (per [D-013](../../../docs/decisions.md#d-013--pseudo-timestamps-at-3-wps-as-a-shared-cross-source-constant-2026-04-26))
so the chunker's timestamp-arithmetic invariants hold without a
PDF-specific branch.
"""
from __future__ import annotations

import logging
from typing import Any

import fitz  # PyMuPDF — module name is `fitz`, package is `pymupdf`

from app.sources._text_utils import _segment_for_text

logger = logging.getLogger(__name__)


def _extract_page_text(page: Any) -> str:
    """Pull text from a PyMuPDF Page including any embedded tables.

    `page.get_text()` returns the page's reading-order text. Tables
    are inline-rendered via PyMuPDF's table-extraction API when
    available (1.23+); on older versions we silently skip.
    """
    base_text = (page.get_text() or "").strip()

    # Table extraction — PyMuPDF's `find_tables()` returns a TableFinder
    # object that's iterable. Each table has `.extract()` which gives
    # a list-of-rows. We render each table as TSV-ish text so it
    # survives chunking + embedding.
    table_chunks: list[str] = []
    try:
        finder = page.find_tables()
        for tbl in finder:
            try:
                rows = tbl.extract()
            except Exception:
                continue
            if not rows:
                continue
            rendered = "\n".join(
                "\t".join((str(cell) if cell is not None else "") for cell in row)
                for row in rows
            )
            if rendered:
                table_chunks.append(f"[TABLE]\n{rendered}\n[/TABLE]")
    except (AttributeError, Exception) as e:
        # find_tables not available, or PyMuPDF raised on a malformed
        # PDF. Log + continue with text-only.
        if not isinstance(e, AttributeError):
            logger.debug(
                "PDF table extraction failed for page: %s", e
            )

    if table_chunks:
        return base_text + "\n\n" + "\n\n".join(table_chunks)
    return base_text


def flatten_pdf(
    pdf_bytes: bytes, source_id: str, document_url: str = ""
) -> list[dict[str, Any]]:
    """Flatten PDF bytes into chunkable segments.

    Args:
        pdf_bytes: raw PDF file content.
        source_id: ``Candidate.source_id`` (used in segment ``extra``
            so the chunker has stable per-page identity).
        document_url: optional URL where the PDF can be re-served
            (the upload endpoint's URL). When set, per-page
            ``comment_url`` is synthesised as ``<url>#page=<N>`` so
            citation deep-links work in standard PDF viewers.

    Returns:
        list of ``{text, start, duration, extra}`` segments — one per
        page with non-empty extracted text. Empty pages are skipped.
        Returns ``[]`` on truly malformed input rather than raising.
    """
    if not pdf_bytes:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning("PDF flatten: fitz.open failed: %s", e)
        return []

    segments: list[dict[str, Any]] = []
    cursor = 0.0
    try:
        total_pages = doc.page_count
        for page_num in range(total_pages):
            try:
                page = doc.load_page(page_num)
            except Exception as e:
                logger.warning(
                    "PDF flatten: load_page(%d) failed: %s", page_num, e
                )
                continue
            text = _extract_page_text(page)
            if not text:
                continue
            page_index_1based = page_num + 1
            comment_url = (
                f"{document_url}#page={page_index_1based}" if document_url else ""
            )
            seg, cursor = _segment_for_text(
                text,
                cursor,
                extra={
                    "kind": "page",
                    "page": page_index_1based,
                    "total_pages": total_pages,
                    "comment_id": f"{source_id}:p{page_index_1based}",
                    "comment_url": comment_url,
                    "author": "",  # PDFs don't have a per-page author
                    "depth": 0,
                },
            )
            segments.append(seg)
    finally:
        doc.close()

    return segments

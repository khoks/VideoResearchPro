"""A document's full text, from the right store for its source type.

Knowledge extraction (and anything else that needs a whole source rather than
retrieval hits) reads text through ``full_text``. Before this module the
knowledge router read ``transcript_cache`` by ``video_id`` only, so an
uploaded PDF, a pasted page, a Reddit or HN thread or a podcast episode had
nothing to read and got a 422 (found 2026-10-25, PR #378).

Where the text lives, by source:

* ``transcript_cache`` — YouTube transcripts (and any future source that
  writes the cache). Keyed on ``document_id`` (D-070); the legacy ``video_id``
  is a fallback for rows written before E-1.10 settled the key.
* the global Chroma collection — every other source. PDFs, pasted pages and
  connector sources are chunked and embedded at ingest and their text is kept
  nowhere else, so it is reassembled from the chunks in ``chunk_index`` order
  with the chunk overlap removed (``reassemble_chunks``).

Visibility is the caller's job: this module reads shared, global stores and
must only ever be handed a document the caller has already resolved through
``visibility_service`` (D-063).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.transcript_cache import TranscriptCache

logger = logging.getLogger(__name__)

ORIGIN_TRANSCRIPT_CACHE = "transcript_cache"
ORIGIN_CHUNKS = "chunks"

# The paragraph size `_text_from_segments` groups transcript segments into, so
# the knowledge splitter has natural boundaries to cut on.
_SEGMENTS_PER_PARAGRAPH = 20

_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class DocumentText:
    """The text, and which store it came from (``""`` when nothing was found)."""

    text: str
    origin: str = ""
    chunk_count: int = 0


def full_text(db: Session, document: Any) -> DocumentText:
    """The whole text of ``document``: the transcript cache first, then its chunks.

    ``document`` is a ``Document`` row the caller may see. Returns an empty
    ``DocumentText`` when neither store holds anything.
    """
    cached = _text_from_transcript_cache(db, document)
    if cached.strip():
        return DocumentText(text=cached, origin=ORIGIN_TRANSCRIPT_CACHE)

    from app.services import chroma_service

    chunks = chroma_service.get_document_chunks(
        document.document_id, getattr(document, "video_id", None) or None
    )
    text = reassemble_chunks(chunks)
    if text.strip():
        return DocumentText(text=text, origin=ORIGIN_CHUNKS, chunk_count=len(chunks))
    return DocumentText(text="")


# ---------------------------------------------------------------------------
# transcript_cache
# ---------------------------------------------------------------------------


def _text_from_transcript_cache(db: Session, document: Any) -> str:
    row = (
        db.query(TranscriptCache)
        .filter(TranscriptCache.document_id == document.document_id)
        .first()
    )
    video_id = getattr(document, "video_id", None)
    if row is None and video_id:
        row = db.query(TranscriptCache).filter(TranscriptCache.video_id == video_id).first()
    if row is None:
        return ""
    try:
        segments = json.loads(row.segments_json)
    except (ValueError, TypeError):
        logger.exception("Corrupt transcript cache for document %s", document.document_id)
        return ""
    return _text_from_segments(segments)


def _text_from_segments(segments: Any) -> str:
    """Join transcript segments' ``text`` into paragraphs of a few segments.

    Segments are joined with spaces and a paragraph break every
    ``_SEGMENTS_PER_PARAGRAPH`` segments so the knowledge splitter has
    semantic boundaries to work with.
    """
    if not isinstance(segments, list):
        return ""
    parts: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "") or "").strip()
        if text:
            parts.append(text)
    paragraphs = [
        " ".join(parts[i:i + _SEGMENTS_PER_PARAGRAPH])
        for i in range(0, len(parts), _SEGMENTS_PER_PARAGRAPH)
    ]
    return "\n\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Chroma chunks
# ---------------------------------------------------------------------------


def _chunk_index(chunk: dict) -> int | None:
    """``metadata.chunk_index``, else the ``:<n>`` suffix of the chunk id."""
    meta = chunk.get("metadata") or {}
    raw = meta.get("chunk_index")
    if raw is None:
        chunk_id = str(chunk.get("id") or "")
        raw = chunk_id.rsplit(":", 1)[-1] if ":" in chunk_id else None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _max_overlap_words() -> int:
    """The longest run of words two neighbouring chunks may share.

    The chunker carries at most ``CHUNK_OVERLAP`` tokens into the next chunk
    and every whitespace word is at least one token, so the overlap is at most
    that many words. The bound is padded because the setting may have been
    lower when an older document was chunked than it is now.
    """
    return max(4 * int(settings.CHUNK_OVERLAP), 64)


def strip_overlap(previous: str, current: str, max_words: int | None = None) -> str:
    """``current`` without the words it repeats from the end of ``previous``.

    ``chunk_transcript`` starts each chunk with whole sentences carried over
    from the end of the one before it (the ``CHUNK_OVERLAP`` window), so the
    longest run of words that ends ``previous`` and starts ``current`` is that
    window. Matching is on whitespace-separated words; what is kept of
    ``current`` is its own text from the first new word on, verbatim.
    """
    limit_cap = _max_overlap_words() if max_words is None else max_words
    prev_words = previous.split()
    matches = list(_WORD_RE.finditer(current))
    cur_words = [m.group(0) for m in matches]
    limit = min(len(prev_words), len(cur_words), limit_cap)
    for k in range(limit, 0, -1):
        if prev_words[-k:] == cur_words[:k]:
            if k == len(cur_words):
                return ""
            return current[matches[k].start():]
    return current


def reassemble_chunks(chunks: list[dict]) -> str:
    """One document's text rebuilt from its stored chunks.

    Chunks are put in ``chunk_index`` order (numeric: Chroma ids sort ``:10``
    before ``:2``), a repeated index is read once, and each chunk loses the
    overlap it shares with the one before it. Each chunk becomes a paragraph:
    chunks end on sentence boundaries, which gives the knowledge splitter the
    same kind of boundary the transcript path gives it. Chunks with no index
    cannot be placed and are skipped.
    """
    indexed: dict[int, str] = {}
    skipped = 0
    for chunk in chunks:
        index = _chunk_index(chunk)
        if index is None:
            skipped += 1
            continue
        indexed.setdefault(index, str(chunk.get("text") or "").strip())
    if skipped:
        logger.warning("Reassembly skipped %d chunk(s) with no chunk_index", skipped)

    paragraphs: list[str] = []
    previous = ""
    for index in sorted(indexed):
        text = indexed[index]
        if not text:
            continue
        new_part = strip_overlap(previous, text).strip() if previous else text
        previous = text
        if new_part:
            paragraphs.append(new_part)
    return "\n\n".join(paragraphs)

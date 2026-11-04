"""The per-document language profile, kept on ``documents.language_mix`` (T-1.16.1.7).

``code_mixing_service.profile_transcript`` measures a source's primary
language of communication, the script its non-English words are written in,
their share, the share of speech framed by Hindi grammar and the quote form.
S-1.16.2 computed it inside ``chunk_transcript`` and kept it only on the
chunks (``code_mix_*`` metadata), so nothing outside Chroma could see a
source's language, and documents chunked before S-1.16.2 had no profile at
all. This module persists the same profile on the document.

Writers:

* every chunking path calls ``ensure`` with the segments it is about to
  chunk and hands the returned profile to ``chunk_transcript``
  (``language_profile=``), so the transcript is profiled once and the column
  always describes the text the chunks were built from (a re-fetched
  transcript replaces the profile of the old one);
* ``scripts/backfill_language_mix.py`` profiles older documents from their
  stored text (``stored_segments``), without an LLM.

Readers get the profile through ``load`` and a serialisable summary through
``public_view``. Visibility is the caller's job: the profile describes a
shared document and must only be shown for one the caller resolved through
``visibility_service`` (D-063).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services import code_mixing_service

logger = logging.getLogger(__name__)

ORIGIN_TRANSCRIPT_CACHE = "transcript_cache"
ORIGIN_CHUNKS = "chunks"

# The fields a reader needs; the rest of the stored profile (window counts,
# per-window modes, unresolved flicker) is diagnostic.
PUBLIC_KEYS = ("primary_language", "native_script", "hi_share", "matrix_hi_share", "quote_mode")


def compute(segments_or_text: Any) -> dict[str, Any]:
    """The profile for a transcript (segments) or a plain text. No LLM."""
    return code_mixing_service.profile_transcript(segments_or_text)


def load(document: Any) -> dict[str, Any] | None:
    """The document's stored profile; None when missing or unreadable."""
    raw = getattr(document, "language_mix", None)
    if not raw:
        return None
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(data, dict) or "primary_language" not in data:
        return None
    return data


def record(document: Any, profile: dict[str, Any] | None) -> bool:
    """Store ``profile`` on the document when it differs. Returns whether it changed.

    Does not commit: every caller commits the document right after chunking.
    Comparing parsed profiles (not strings) keeps a re-run from rewriting an
    identical profile.
    """
    if not isinstance(profile, dict):
        return False
    if load(document) == profile:
        return False
    document.language_mix = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    return True


def ensure(document: Any, segments_or_text: Any) -> dict[str, Any] | None:
    """Profile the text about to be chunked, store it on the document, return it.

    Fail-soft: the profile is enrichment on top of a working ingest, so an
    error is logged and reads as None, and ``chunk_transcript`` then
    profiles the segments itself as it did before T-1.16.1.7.
    """
    try:
        profile = compute(segments_or_text)
    except Exception:
        logger.exception(
            "Language profile failed for document %s; chunks profile themselves",
            getattr(document, "document_id", "?"),
        )
        return None
    try:
        record(document, profile)
    except Exception:
        logger.exception(
            "Could not store the language profile of document %s",
            getattr(document, "document_id", "?"),
        )
    return profile


def public_view(document: Any) -> dict[str, Any] | None:
    """The stored profile for an API response, or None when not profiled.

    ``code_mixed`` applies the chunker's own rule (``chunk_metadata_from_profile``,
    with its 3% presence floor) to the stored profile, so it says whether the
    TEXT is not plain English. It is not a fact about the chunks: a document
    chunked before S-1.16.2 and profiled since (the backfill, or a job that
    reused its chunks without re-embedding) reads true while its chunks carry
    no ``code_mix_*`` until it is re-chunked.
    """
    profile = load(document)
    if profile is None:
        return None
    view: dict[str, Any] = {k: profile.get(k) for k in PUBLIC_KEYS}
    view["code_mixed"] = bool(code_mixing_service.chunk_metadata_from_profile(profile))
    return view


# ---------------------------------------------------------------------------
# Stored text, for the backfill
# ---------------------------------------------------------------------------


def stored_segments(db: Any, document: Any) -> tuple[list[dict] | None, str]:
    """The document's text as it was chunked, from the stores that keep it.

    ``transcript_cache`` first (by ``document_id``, D-070, then the legacy
    ``video_id``): the segments the chunker read, so the profile equals the
    one chunking computes. Otherwise the document's chunks in the global
    Chroma collection, reassembled the way ``document_text_service`` does for
    knowledge reports (stale tail dropped, ``chunk_index`` order, overlap
    removed), one segment per chunk, with any ``[VISUAL @ ...]`` annotation
    removed: those are our words, not the speaker's. PDFs and pasted pages
    keep their text nowhere else.

    Returns ``(segments, origin)``; ``(None, "")`` when neither store holds text.
    """
    from app.models.transcript_cache import TranscriptCache

    row = db.get(TranscriptCache, document.document_id)
    video_id = getattr(document, "video_id", None)
    if row is None and video_id:
        row = db.query(TranscriptCache).filter(TranscriptCache.video_id == video_id).first()
    if row is not None:
        try:
            segments = json.loads(row.segments_json)
        except (TypeError, ValueError):
            logger.warning("Corrupt transcript cache for document %s", document.document_id)
            segments = None
        if isinstance(segments, list) and any(
            isinstance(s, dict) and str(s.get("text") or "").strip() for s in segments
        ):
            return segments, ORIGIN_TRANSCRIPT_CACHE

    from app.services import chroma_service, document_text_service
    from app.services.visual_service import strip_annotations

    chunks = chroma_service.get_document_chunks(document.document_id, video_id or None)
    text = document_text_service.reassemble_chunks(chunks)
    paragraphs = [
        p for p in (strip_annotations(part).strip() for part in text.split("\n\n")) if p
    ]
    if paragraphs:
        return [{"text": p} for p in paragraphs], ORIGIN_CHUNKS
    return None, ""

"""Echo share processing (S-3.7.2): what a share becomes after intake.

One call per share, run by the ``echo.process_share`` Celery task (or inline
in single-process dev). Idempotent: running it again re-derives everything
from ``raw_payload_json``, which never changes.

By kind:

- **text** — the words are the content. Embedded.
- **url** — a YouTube link resolves its title, channel and description through
  the Data API (one quota unit); any other link goes through the article
  extractor the paste path uses. The extracted text is embedded. A non-YouTube
  link that the paste path can ingest gets a **library offer**: one click
  later adds it to the library, visible to the sharer only.
- **file** — a plain-text file is decoded and embedded. Images (OCR) and audio
  (transcription) are part 2 of this story; until then such shares stay
  ``pending`` with a note saying why, and part 2 processes them.

Fail-soft: a share whose processing fails is marked ``failed`` with the
reason in ``processing_json`` and stays browsable, editable and deletable.

Not done here because what they feed does not exist yet: the activity event
per share (E-3.2's ``activity_events``) and the signal-extraction queue
(S-3.3.2). ``voice_eligible`` is the gate S-3.3.2 must use: only the user's
own words (``author_is_tenant``) may feed voice signals (D-089 item 1).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.orm import Session

from app.config import settings
from app.models.share import Share
from app.services import echo_intake_service, echo_vectors

logger = logging.getLogger(__name__)

YOUTUBE_CONTENT_TYPES = frozenset({"youtube_video", "youtube_short"})
_TEXT_FILE_TYPES = frozenset({"text_file"})
_PART_TWO_TYPES = {
    "image": "Text recognition for images arrives with S-3.7.2 part 2.",
    "voice_memo": "Transcription for audio arrives with S-3.7.2 part 2.",
    "video_clip": "Transcription for video clips arrives with S-3.7.2 part 2.",
    "pdf": "PDF text extraction for shares arrives with S-3.7.2 part 2.",
}


class ProcessingError(RuntimeError):
    """Expected failure with a reason fit to show the user."""


@dataclass(frozen=True)
class ProcessResult:
    state: str
    reason: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_processing(share: Share) -> dict:
    try:
        data = json.loads(share.processing_json or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def voice_eligible(share: Share) -> bool:
    """May this share feed voice signals (S-3.3.2)? Only the user's own words.
    Context-only shares may be retrieved as context, never learned from as
    the user's voice (D-089 item 1)."""
    return bool(share.author_is_tenant)


def youtube_video_id(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
        return vid or None
    if host.endswith("youtube.com"):
        if parts.path.startswith("/shorts/") or parts.path.startswith("/live/"):
            return parts.path.split("/")[2] or None
        return (parse_qs(parts.query).get("v") or [None])[0]
    return None


# ---------------------------------------------------------------------------
# Per-kind processors: return (extracted_text, processing_fields)
# ---------------------------------------------------------------------------


def _process_text(share: Share, payload: dict) -> tuple[str, dict]:
    text = payload.get("text") or share.extracted_text or ""
    return text, {"extractor": "as_is"}


def _process_youtube(url: str) -> tuple[str, dict]:
    from app.services import youtube_service

    vid = youtube_video_id(url)
    if not vid:
        raise ProcessingError("Could not read a video id from that YouTube link.")
    try:
        details = youtube_service.get_video_details([vid]).get(vid)
    except Exception as e:
        raise ProcessingError(f"YouTube lookup failed: {type(e).__name__}") from e
    if not details:
        raise ProcessingError("YouTube has no public video at that link.")
    title = details.get("title") or ""
    channel = details.get("channel_name") or ""
    description = details.get("description") or ""
    text = "\n\n".join(p for p in (title, f"by {channel}" if channel else "", description) if p)
    return text, {
        "extractor": "youtube_data_api",
        "title": title,
        "author": channel,
        "video_id": vid,
        "published_at": details.get("published_at"),
        "duration_seconds": details.get("duration_seconds"),
        # No single-video library ingest exists; a research run is the way in.
        "library_offer": {"eligible": False,
                          "reason": "Videos enter the library through a research run."},
    }


def _process_article(url: str) -> tuple[str, dict]:
    from app.services.article_extraction.extractor import extract_text
    from app.services.paste_url_resolver import is_recognised_paste_source, resolve_source_type

    try:
        result = extract_text(url)
    except Exception as e:
        raise ProcessingError(f"Fetching the page failed: {type(e).__name__}") from e
    if result is None or not (result.text or "").strip():
        raise ProcessingError("No readable text could be extracted from that page.")
    source_type = resolve_source_type(url)
    return result.text, {
        "extractor": result.source or "trafilatura",
        "title": result.title,
        "author": result.author,
        "language": result.language,
        "word_count": result.word_count,
        "library_offer": {
            "eligible": is_recognised_paste_source(source_type),
            "source_type": source_type,
        },
    }


def _process_url(share: Share, payload: dict) -> tuple[str, dict]:
    url = payload.get("url") or ""
    if share.content_type in YOUTUBE_CONTENT_TYPES or youtube_video_id(url):
        return _process_youtube(url)
    return _process_article(url)


def _process_file(share: Share, payload: dict) -> tuple[str, dict] | ProcessResult:
    if share.content_type in _TEXT_FILE_TYPES:
        path = echo_intake_service.resolve_share_file(share.file_path or "", share.tenant_id)
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        return text[: settings.ECHO_SHARE_TEXT_MAX_CHARS], {"extractor": "text_file"}
    reason = _PART_TWO_TYPES.get(
        share.content_type, "No processor handles this kind of file yet."
    )
    return ProcessResult("pending", reason)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def embed_text(share: Share, title: str | None) -> str:
    parts = [share.user_annotation or "", title or "", share.extracted_text or ""]
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return text[: settings.ECHO_SHARE_EMBED_MAX_CHARS]


def vector_metadata(share: Share) -> dict:
    received = share.received_at
    if received is not None and received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    return {
        "tenant_id": share.tenant_id,
        "share_id": share.id,
        "content_type": share.content_type,
        "surface": share.surface,
        "author_is_tenant": bool(share.author_is_tenant),
        "voice_eligible": voice_eligible(share),
        "received_at": received.isoformat() if received else None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def process_share(db: Session, share_id: str) -> ProcessResult:
    """Process one share. Never raises for an expected failure: the share is
    marked ``failed`` with the reason and stays in the inbox."""
    share = db.get(Share, share_id)
    if share is None:
        logger.info("echo: share %s is gone; nothing to process", share_id)
        return ProcessResult("missing")
    payload = echo_intake_service.load_payload(share)
    kind = payload.get("kind")
    processing = load_processing(share)
    processing.pop("error", None)
    try:
        if kind == "text":
            outcome = _process_text(share, payload)
        elif kind == "url":
            outcome = _process_url(share, payload)
        elif kind == "file":
            outcome = _process_file(share, payload)
        else:
            raise ProcessingError(f"Unknown share kind {kind!r}.")
    except ProcessingError as e:
        return _finish(db, share, processing, "failed", error=str(e))
    except Exception as e:  # unexpected: still fail-soft, but logged loudly
        logger.exception("echo: processing share %s failed", share.id)
        return _finish(db, share, processing, "failed", error=f"Processing failed: {type(e).__name__}")

    if isinstance(outcome, ProcessResult):
        processing["note"] = outcome.reason
        return _finish(db, share, processing, outcome.state)

    text, fields = outcome
    processing.pop("note", None)
    processing.update({k: v for k, v in fields.items() if v is not None})
    share.extracted_text = text
    try:
        share.embedding_id = echo_vectors.upsert_share_vector(
            share.id, embed_text(share, processing.get("title")), vector_metadata(share)
        )
        processing["embedded"] = True
    except Exception:
        # Text is still useful in the inbox; embedding is retried by the next
        # processing run of this share.
        logger.exception("echo: embedding share %s failed", share.id)
        processing["embedded"] = False
    return _finish(db, share, processing, "processed")


def _finish(db: Session, share: Share, processing: dict, state: str, error: str | None = None) -> ProcessResult:
    if error:
        processing["error"] = error
    processing["processed_at"] = _now_iso()
    share.processing_json = json.dumps(processing, ensure_ascii=False)
    share.processing_state = state
    share.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("echo: share %s -> %s%s", share.id[:8], state, f" ({error})" if error else "")
    return ProcessResult(state, error or processing.get("note"))


def enqueue(share: Share, user) -> str:
    """Hand a share to processing according to ``ECHO_SHARE_PROCESSING``.
    Returns what happened: "queued", "processed" (inline), "off" or
    "queue_failed" (the share stays pending; Retry re-queues it)."""
    mode = (settings.ECHO_SHARE_PROCESSING or "off").lower()
    if mode == "off":
        return "off"
    if mode == "inline":
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            process_share(db, share.id)
        finally:
            db.close()
        return "processed"
    try:
        from app.services import task_routing_service
        from app.tasks.echo_tasks import process_share_task

        task_routing_service.dispatch_for_user(process_share_task, user, share.id)
        return "queued"
    except Exception:
        logger.exception("echo: could not queue share %s; it stays pending", share.id)
        return "queue_failed"

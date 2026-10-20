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
- **file** — a plain-text file is decoded. An image is read by on-device OCR,
  with a vision-model fallback when that reading is not confident; a voice
  memo or video clip is transcribed by Whisper; a PDF gives its text layer
  (``echo_media``). Remote readers honour ``ECHO_REMOTE_MEDIA``: when it is
  off a share they would need is ``skipped`` with a note saying so.
  Extracted text is capped at ``ECHO_SHARE_TEXT_MAX_CHARS``; the file
  itself stays whole in the archive.

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
from app.services import echo_intake_service, echo_media, echo_vectors

logger = logging.getLogger(__name__)

YOUTUBE_CONTENT_TYPES = frozenset({"youtube_video", "youtube_short"})
_TEXT_FILE_TYPES = frozenset({"text_file"})
_RECORDING_TYPES = frozenset({"voice_memo", "video_clip"})


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


def _capped(text: str, fields: dict) -> tuple[str, dict]:
    """Keep the first ``ECHO_SHARE_TEXT_MAX_CHARS`` of a file's text; the
    file itself stays whole in the archive."""
    limit = settings.ECHO_SHARE_TEXT_MAX_CHARS
    if len(text) <= limit:
        return text, fields
    note = (
        f"Only the first {limit:,} of {len(text):,} characters are kept here; "
        "the file itself is whole in your archive."
    )
    return text[:limit], {**fields, "truncated": True, "note": fields.get("note") or note}


def _process_image(db: Session, share: Share, path) -> tuple[str, dict] | ProcessResult:
    image = echo_media.load_image(path)
    local = echo_media.ocr_local(image)
    fields: dict = {"extractor": "ocr_local"}
    if local is not None:
        fields["ocr_confidence"] = round(local.mean_score, 3)
        if local.confident():
            return local.text, fields
    if not echo_media.vision_permitted():
        blocked = echo_media.remote_block_reason() or "no vision model is allowed"
        if local is not None and local.text:
            return local.text, {
                **fields,
                "note": "On-device OCR read this with low confidence. It was not "
                f"sent to a vision model: {blocked}.",
            }
        return ProcessResult(
            "skipped",
            "On-device OCR found no text. The image was not sent to a vision "
            f"model: {blocked}.",
        )
    try:
        text = echo_media.ocr_vision(image, tenant_id=share.tenant_id, db=db)
    except Exception as e:
        logger.warning("echo: vision OCR failed for share %s: %s", share.id, e)
        if local is not None and local.text:
            return local.text, {
                **fields,
                "note": "The vision model could not be reached, so this is the "
                "on-device reading, which had low confidence.",
            }
        raise ProcessingError("Reading the image failed: the vision model could not be reached.") from e
    vision_fields = {k: v for k, v in fields.items() if k != "extractor"}
    vision_fields["extractor"] = "ocr_vision"
    if not text:
        vision_fields["note"] = "No text found in this image."
    return text, vision_fields


def _process_recording(db: Session, share: Share, path) -> tuple[str, dict]:
    transcript = echo_media.transcribe(
        path, tenant_id=share.tenant_id, db=db, label=f"share:{share.id[:8]}"
    )
    fields = {
        "extractor": "whisper",
        "language": transcript.language,
        "duration_seconds": transcript.duration_seconds,
    }
    if not transcript.text:
        fields["note"] = "No speech found in this recording."
    return transcript.text, fields


def _process_pdf(path) -> tuple[str, dict]:
    pdf = echo_media.pdf_text(path)
    return pdf.text, {
        "extractor": "pdf_text",
        "page_count": pdf.total_pages,
        "pages_with_text": pdf.pages_with_text,
    }


def _process_file(db: Session, share: Share, payload: dict) -> tuple[str, dict] | ProcessResult:
    path = echo_intake_service.resolve_share_file(share.file_path or "", share.tenant_id)
    kind = share.content_type
    try:
        if kind in _TEXT_FILE_TYPES:
            data = path.read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
            return _capped(text, {"extractor": "text_file"})
        if kind == "image":
            outcome = _process_image(db, share, path)
            return outcome if isinstance(outcome, ProcessResult) else _capped(*outcome)
        if kind in _RECORDING_TYPES:
            return _capped(*_process_recording(db, share, path))
        if kind == "pdf":
            return _capped(*_process_pdf(path))
    except echo_media.MediaSkipped as e:
        return ProcessResult("skipped", str(e))
    except echo_media.MediaError as e:
        raise ProcessingError(str(e)) from e
    return ProcessResult(
        "skipped",
        "No reader handles this kind of file yet; it is kept in your archive.",
    )


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
    from app.services import llm_service

    try:
        # The tenant's own keys and model overrides decide which models read
        # their media, and whether they count as local-only (echo_media).
        with llm_service.byok_context(share.tenant_id, db):
            if kind == "text":
                outcome = _process_text(share, payload)
            elif kind == "url":
                outcome = _process_url(share, payload)
            elif kind == "file":
                outcome = _process_file(db, share, payload)
            else:
                raise ProcessingError(f"Unknown share kind {kind!r}.")
    except ProcessingError as e:
        return _finish(db, share, processing, "failed", error=str(e))
    except Exception as e:  # unexpected: still fail-soft, but logged loudly
        logger.exception("echo: processing share %s failed", share.id)
        return _finish(db, share, processing, "failed", error=f"Processing failed: {type(e).__name__}")

    for stale in _DERIVED_FIELDS:
        processing.pop(stale, None)
    if isinstance(outcome, ProcessResult):
        processing["note"] = outcome.reason
        return _finish(db, share, processing, outcome.state)

    text, fields = outcome
    processing.update({k: v for k, v in fields.items() if v is not None})
    share.extracted_text = text
    vector_text = embed_text(share, processing.get("title"))
    if not vector_text:
        # Nothing searchable (a photo with no text and no annotation):
        # drop any vector an earlier run wrote rather than keep a stale one.
        if share.embedding_id:
            try:
                echo_vectors.delete_share_vector(share.tenant_id, share.id)
            except Exception:
                logger.exception("echo: removing the stale vector of share %s failed", share.id)
            share.embedding_id = None
        processing["embedded"] = False
        return _finish(db, share, processing, "processed")
    try:
        share.embedding_id = echo_vectors.upsert_share_vector(
            share.id, vector_text, vector_metadata(share)
        )
        processing["embedded"] = True
    except Exception:
        # Text is still useful in the inbox; embedding is retried by the next
        # processing run of this share.
        logger.exception("echo: embedding share %s failed", share.id)
        processing["embedded"] = False
    return _finish(db, share, processing, "processed")


# Fields a reader derives; a re-run clears them so nothing stale survives.
_DERIVED_FIELDS = (
    "note", "extractor", "truncated", "ocr_confidence", "language",
    "duration_seconds", "page_count", "pages_with_text",
)


def _finish(db: Session, share: Share, processing: dict, state: str, error: str | None = None) -> ProcessResult:
    if error:
        processing["error"] = error
    processing["processed_at"] = _now_iso()
    share.processing_json = json.dumps(processing, ensure_ascii=False)
    share.processing_state = state
    share.updated_at = datetime.now(timezone.utc)
    db.commit()
    if state != "failed":
        # T-3.2.1.9: sharing is something the user did. Fail-soft: the event
        # is a by-product, never a reason for processing to fail.
        try:
            from app.services import activity_event_service

            activity_event_service.record_share_event(db, share, title=processing.get("title"))
        except Exception:
            db.rollback()
            logger.exception("echo: could not record the share event for %s", share.id)
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

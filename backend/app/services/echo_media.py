"""Reading media shares for Echo (S-3.7.2 part 2): images, recordings, PDFs.

Each reader takes a path inside the tenant's share directory and returns what
it read, or raises:

- ``MediaError`` when the file cannot be read (the share is marked
  ``failed`` with the message, and Retry is offered);
- ``MediaSkipped`` when policy or configuration says not to read it (the
  share is marked ``skipped`` with the message, which names what to change).

Images: on-device OCR first (RapidOCR, ONNX models, nothing leaves the
machine). When that reading is not confident (see ``OcrResult.confident``) a
vision model reads the image instead. A remote one runs only when
``remote_block_reason()`` finds nothing against it: ``ECHO_REMOTE_MEDIA`` is
on and the tenant is not local-only (every other model they use resolves
to ``local``, through the install's config or their own overrides). A
vision model the install runs locally is always allowed. The tenant's own
provider key is used when they have one (BYOK).

Recordings (voice memos, video clips): ffmpeg reduces them to 16 kHz mono
speech audio, which OpenAI Whisper transcribes in the speaker's language.
Remote by nature, so the same ``remote_block_reason()`` skips them.

Run inside ``llm_service.byok_context(tenant, db)`` (``process_share`` does)
so the tenant's overrides and keys are the ones consulted.

PDFs: the text layer, through the library's own PDF flattener. A scan has no
text layer and fails with a reason.
"""
from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# What the hosted Whisper endpoint accepts without conversion.
WHISPER_FORMATS = frozenset(
    {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"}
)
# Speech needs little: 32 kbit/s mono keeps about 100 minutes under the cap.
_SPEECH_BITRATE = "32k"


class MediaError(RuntimeError):
    """The file could not be read; the message is fit to show the user."""


class MediaSkipped(RuntimeError):
    """Not read by policy or configuration; the message says what to change."""


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrResult:
    text: str
    mean_score: float
    boxes: int

    @property
    def chars(self) -> int:
        return len("".join(self.text.split()))

    def confident(self) -> bool:
        return (
            self.chars >= settings.ECHO_OCR_MIN_CHARS
            and self.mean_score >= settings.ECHO_OCR_MIN_CONFIDENCE
        )


_engine: Any = None
_engine_lock = threading.Lock()


def _ocr_engine() -> Any:
    """One RapidOCR engine per process; loading the models takes ~0.5 s."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR(
                intra_op_num_threads=settings.ECHO_OCR_THREADS,
                inter_op_num_threads=1,
            )
        return _engine


def load_image(path: Path) -> Any:
    """Decode an image as RGB, upright per its EXIF orientation."""
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as im:
            return ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:  # unknown format, truncated file, decompression bomb
        raise MediaError("The image could not be read (unsupported format or a damaged file).") from e


def ocr_local(image: Any) -> OcrResult | None:
    """On-device OCR. ``None`` when the engine is not installed."""
    try:
        engine = _ocr_engine()
    except ImportError:
        logger.warning("echo: rapidocr_onnxruntime is not installed; on-device OCR is off")
        return None
    import numpy as np

    result, _elapsed = engine(np.asarray(image))
    items = result or []
    lines = [str(item[1]).strip() for item in items if str(item[1]).strip()]
    scores = [float(item[2]) for item in items]
    mean = sum(scores) / len(scores) if scores else 0.0
    return OcrResult(text="\n".join(lines), mean_score=mean, boxes=len(items))


def local_only() -> bool:
    """Every model this tenant uses runs on-device. Read inside the tenant's
    ``byok_context``, so their own overrides count. ``echo_share_ocr`` is left
    out: a tenant who moved everything local before it existed still has its
    remote default, and their images must not be sent there."""
    from app.services.llm_routing import USE_CASE_REGISTRY, resolve_config

    return all(
        resolve_config(uc).provider == "local"
        for uc in USE_CASE_REGISTRY
        if uc != "echo_share_ocr"
    )


def remote_block_reason() -> str | None:
    """Why a shared image or recording may not go to a remote provider, or
    ``None`` when it may."""
    if not settings.ECHO_REMOTE_MEDIA:
        return "sending media to remote providers is off on this install (ECHO_REMOTE_MEDIA)"
    if local_only():
        return "every model you use runs locally, so media stays on this machine"
    return None


def vision_permitted() -> bool:
    """The vision fallback may run: its model is one the install runs
    itself, or nothing blocks sending the image out."""
    from app.services.llm_routing import resolve_config

    if resolve_config("echo_share_ocr").provider == "local":
        return True
    return remote_block_reason() is None


def _jpeg_b64(image: Any, max_side: int) -> str:
    w, h = image.size
    scale = max_side / max(w, h)
    if scale < 1:
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ocr_vision(image: Any, *, tenant_id: str, db: Any) -> str:
    """Read an image's text with the ``echo_share_ocr`` vision model. Returns
    "" when the model says the image holds no text. Raises on provider errors;
    the caller decides what to fall back to."""
    from langchain_core.messages import HumanMessage

    from app.agents.prompts.echo_prompts import NO_TEXT_SENTINEL, SHARE_OCR_PROMPT
    from app.services.llm_service import get_llm_for, response_text

    b64 = _jpeg_b64(image, settings.ECHO_OCR_VISION_MAX_SIDE)
    message = HumanMessage(
        content=[
            {"type": "text", "text": SHARE_OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]
    )
    llm = get_llm_for(
        "echo_share_ocr",
        temperature=0.0,
        max_tokens=settings.ECHO_OCR_VISION_MAX_TOKENS,
        tenant_id=tenant_id,
        db=db,
    )
    text = response_text(llm.invoke([message])).strip()
    if not text or text.strip().strip(".") == NO_TEXT_SENTINEL:
        return ""
    return text


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    duration_seconds: float


def _openai_key(tenant_id: str, db: Any) -> str | None:
    from app.services.llm_service import _resolve_byok_api_key

    return _resolve_byok_api_key("openai", tenant_id, db) or settings.OPENAI_API_KEY or None


def _speech_audio(src: Path, workdir: Path) -> Path:
    """A file Whisper accepts: ffmpeg's 16 kHz mono speech track when ffmpeg
    is installed, else the original when its format is one Whisper reads."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        out = workdir / "speech.mp3"
        cmd = [
            ffmpeg, "-v", "error", "-y", "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", _SPEECH_BITRATE, str(out),
        ]
        try:
            subprocess.run(
                cmd, check=True, capture_output=True,
                timeout=settings.ECHO_MEDIA_DECODE_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as e:
            raise MediaError("Decoding the recording took too long.") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode("utf-8", "replace").lower()
            if "does not contain any stream" in stderr or "matches no streams" in stderr:
                raise MediaError("This file has no audio track to transcribe.") from e
            raise MediaError("The recording could not be decoded.") from e
        if not out.exists() or out.stat().st_size == 0:
            raise MediaError("This file has no audio track to transcribe.")
        return out
    ext = src.suffix.lower()
    if ext == ".opus":  # Ogg Opus under another name: Whisper reads it as .ogg
        copy = workdir / "speech.ogg"
        shutil.copyfile(src, copy)
        return copy
    if ext in WHISPER_FORMATS:
        return src
    raise MediaError("Reading this kind of recording needs ffmpeg, which is not installed.")


def transcribe(path: Path, *, tenant_id: str, db: Any, label: str) -> Transcript:
    """Transcribe a voice memo or video clip with OpenAI Whisper, in the
    speaker's own language (``transcribe``, never ``translate``)."""
    blocked = remote_block_reason()
    if blocked:
        raise MediaSkipped(
            f"Not transcribed: transcription sends the recording to OpenAI "
            f"Whisper, and {blocked}."
        )
    api_key = _openai_key(tenant_id, db)
    if not api_key:
        raise MediaSkipped("Transcription needs an OpenAI API key, and none is configured.")

    from openai import OpenAI

    from app.services.youtube_service import (
        WHISPER_MAX_FILE_BYTES,
        _whisper_response_to_segments,
        _whisper_transcribe_with_retry,
    )

    with tempfile.TemporaryDirectory(prefix="echo-media-") as tmp:
        audio = _speech_audio(path, Path(tmp))
        size = audio.stat().st_size
        if size > WHISPER_MAX_FILE_BYTES:
            raise MediaError(
                "This recording is too long to transcribe in one piece "
                f"(over Whisper's {WHISPER_MAX_FILE_BYTES // (1024 * 1024)} MB limit)."
            )
        client = OpenAI(api_key=api_key)
        try:
            response = _whisper_transcribe_with_retry(
                client, str(audio), label, "[echo]", size / (1024 * 1024)
            )
        except Exception as e:
            raise MediaError(f"Transcription failed: {type(e).__name__}.") from e
    if response is None:
        raise MediaError("Transcription failed.")
    segments, language, duration = _whisper_response_to_segments(response, "[echo]", label)
    text = " ".join(s["text"] for s in segments if s.get("text")).strip()
    return Transcript(text=text, language=language, duration_seconds=round(duration, 1))


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdfText:
    text: str
    pages_with_text: int
    total_pages: int


def pdf_text(path: Path) -> PdfText:
    from app.sources.pdf.flatten import flatten_pdf

    segments = flatten_pdf(path.read_bytes(), source_id="echo-share")
    if not segments:
        raise MediaError(
            "No text could be extracted from this PDF. It may be a scan, which "
            "is not read yet, or a damaged file."
        )
    total = int((segments[0].get("extra") or {}).get("total_pages") or len(segments))
    text = "\n\n".join(s["text"] for s in segments if s.get("text"))
    return PdfText(text=text, pages_with_text=len(segments), total_pages=total)

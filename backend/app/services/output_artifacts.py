"""Author Studio artifacts on disk (S-6.7.2 / E-6.7).

Text outputs (a book's Markdown) live in ``outputs.content_text``. Binary
outputs (PDF, EPUB, PPTX, a site zip, an MP4) live on disk here:

    <OUTPUTS_DIR>/<user_id>/<output_id>/artifact.<format>

One directory per output, so an output can carry several formats (a book's
PDF and EPUB beside its Markdown) and deleting the output removes one
directory. ``outputs.content_path`` holds the primary artifact **relative to
``OUTPUTS_DIR``** (the `frame_service` precedent): the Celery worker writes
it and the API serves it, and the two need not share a working directory.

Safety: path components come from ids we minted, but they are still
validated (``[A-Za-z0-9_-]`` only, never sanitised into a different string
that could collide), formats come from a whitelist, and every resolved path
must sit inside ``OUTPUTS_DIR`` or it is refused. A tampered ``content_path``
therefore cannot be used to read another file on the host.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import settings
from app.models.output import Output
from app.services.output_service import OutputError

logger = logging.getLogger(__name__)

# Format → media type. A format not listed here cannot be written or served.
FORMATS: dict[str, str] = {
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
    "mp4": "video/mp4",
}

# How an output's ``content_text`` is served, by kind.
TEXT_FORMAT_BY_KIND: dict[str, str] = {"book": "md", "deck": "md", "site": "md", "newsletter": "md"}  # a deck's text is its Markdown rendering (S-6.3.1)
DEFAULT_TEXT_FORMAT = "txt"

ARTIFACT_STEM = "artifact"

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ArtifactError(OutputError):
    pass


def outputs_root() -> Path:
    return Path(os.path.abspath(settings.OUTPUTS_DIR))


def _component(value: str | None, what: str) -> str:
    if not value or not _SAFE_COMPONENT.match(value):
        raise ArtifactError(f"unusable {what} for an artifact path: {value!r}")
    return value


def _inside_root(path: Path) -> bool:
    root = outputs_root()
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def output_dir(output: Output, *, create: bool = False) -> Path:
    path = outputs_root() / _component(output.user_id, "user id") / _component(output.id, "output id")
    if not _inside_root(path):  # pragma: no cover - guarded by _component already
        raise ArtifactError("artifact directory escapes OUTPUTS_DIR")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def text_format(output: Output) -> str:
    return TEXT_FORMAT_BY_KIND.get(output.kind, DEFAULT_TEXT_FORMAT)


def _check_format(fmt: str) -> str:
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        raise ArtifactError(f"unknown artifact format {fmt!r}; expected one of {sorted(FORMATS)}")
    return fmt


def artifact_file(output: Output, fmt: str) -> Path:
    """Where ``fmt`` for ``output`` lives (whether or not it exists yet)."""
    return output_dir(output) / f"{ARTIFACT_STEM}.{_check_format(fmt)}"


def write_artifact(output: Output, fmt: str, data: bytes | str, *, primary: bool = True) -> Path:
    """Write one artifact atomically and, when ``primary``, point
    ``output.content_path`` at it (the caller commits the row)."""
    target = artifact_file(output, fmt)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=f".{fmt}")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if primary:
        output.content_path = target.relative_to(outputs_root()).as_posix()
    return target


def resolve_content_path(stored: str | None) -> Path | None:
    """``content_path`` back to a file, or None when it is missing, absolute
    or outside ``OUTPUTS_DIR`` (refused, logged)."""
    if not stored:
        return None
    candidate = Path(stored)
    if candidate.is_absolute() or ".." in candidate.parts:
        logger.warning("output_artifacts: refusing content_path %r", stored)
        return None
    path = outputs_root() / candidate
    if not _inside_root(path):
        logger.warning("output_artifacts: content_path %r escapes OUTPUTS_DIR", stored)
        return None
    return path if path.is_file() else None


def available_formats(output: Output) -> list[str]:
    """Formats this output can be downloaded in: its text first, then every
    artifact file present, in ``FORMATS`` order."""
    formats: list[str] = []
    if output.content_text:
        formats.append(text_format(output))
    try:
        directory = output_dir(output)
    except ArtifactError:
        return formats
    if directory.is_dir():
        for fmt in FORMATS:
            if fmt not in formats and (directory / f"{ARTIFACT_STEM}.{fmt}").is_file():
                formats.append(fmt)
    return formats


def download_filename(title: str, fmt: str) -> str:
    """A readable file name from the title. Letters, combining marks and
    digits of any script are kept, by Unicode category, because the regex
    word class drops Devanagari vowel signs (they are marks); separators
    become hyphens and punctuation is dropped."""
    chars: list[str] = []
    for ch in (title or "").strip().lower():
        category = unicodedata.category(ch)
        if category[0] in "LMN":
            chars.append(ch)
        elif ch in "_-" or category[0] == "Z" or ch.isspace():
            chars.append(" ")
    slug = re.sub(r"\s+", "-", "".join(chars)).strip("-")[:80].strip("-") or "output"
    return f"{slug}.{fmt}"


def content_disposition(filename: str) -> str:
    """RFC 6266 attachment header with an ASCII fallback and the UTF-8 name
    (Devanagari titles must survive)."""
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    ascii_stem = re.sub(r"-{2,}", "-", stem.encode("ascii", "ignore").decode("ascii")).strip("-")
    ascii_stem = ascii_stem.replace('"', "") or "output"
    ascii_name = f"{ascii_stem}.{ext}" if ext else ascii_stem
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def delete_artifacts(output: Output) -> bool:
    """Remove the output's directory. Best effort; True when one existed."""
    try:
        directory = output_dir(output)
    except ArtifactError:
        return False
    if not directory.is_dir():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    parent = directory.parent
    try:
        if parent != outputs_root() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    return True


def find_orphans(db: Session) -> list[Path]:
    """Artifact directories whose output row no longer exists, or that sit
    under a user other than the row's owner. Read-only."""
    root = outputs_root()
    if not root.is_dir():
        return []
    owners = {row_id: user_id for row_id, user_id in db.query(Output.id, Output.user_id)}
    orphans: list[Path] = []
    for user_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for out_dir in sorted(p for p in user_dir.iterdir() if p.is_dir()):
            if owners.get(out_dir.name) != user_dir.name:
                orphans.append(out_dir)
    return orphans

"""Echo shares inbox — intake, listing, editing, deletion (S-3.7.1).

Everything the user forwards to Echo lands here with no approval step
(`personal-brain.md` § Domain 5, "zero approval, not zero trust"). This module
writes the row and, for files, the bytes. It does no processing: OCR, Whisper,
embedding and signal extraction are S-3.7.2, so a new share is ``pending``.

Invariants every caller relies on:

1. **Per tenant.** Every read and write filters on ``Share.tenant_id``; a
   foreign id is indistinguishable from a missing one (``ShareNotFound``).
2. **Files stay inside ``ECHO_SHARES_DIR/<tenant>/``.** The stored name is
   the share id plus a sanitised extension, never the client's filename, and
   every resolved path is checked to sit under the root before it is read or
   removed.
3. **Third-party content is context-only by default** (``author_is_tenant``
   False). See ``app.models.share``.
4. **Deleting a share removes everything derived from it**: its vector (if
   S-3.7.2 wrote one), its file, the facts it produced, and the row. The
   vector goes first and a failure there aborts, so a retry can still find it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import func, or_
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.config import settings
from app.models.personal_context import PersonalContext
from app.models.share import Share
from app.services import echo_vectors

logger = logging.getLogger(__name__)

SURFACES: frozenset[str] = frozenset(
    {"manual_quick_share", "drag_drop", "browser_ext", "email_in", "os_share", "file_import"}
)
PROCESSING_STATES: frozenset[str] = frozenset({"pending", "processed", "skipped", "failed"})

_CONTENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")
_URL_MAX = 2000
_ANNOTATION_MAX = 5000


class ShareNotFound(LookupError):
    """No share with that id belongs to this tenant."""


class InvalidShare(ValueError):
    """The share as submitted cannot be stored (bad URL, empty text, ...)."""


class ShareTooLarge(InvalidShare):
    """Over ``ECHO_SHARE_MAX_BYTES`` or ``ECHO_SHARE_TEXT_MAX_CHARS``."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def shares_root() -> Path:
    return Path(settings.ECHO_SHARES_DIR).resolve()


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def tenant_dir(tenant_id: str, *, create: bool = False) -> Path:
    """``ECHO_SHARES_DIR/<tenant>``. The tenant id is used as a path component
    only if it is exactly a safe token; anything else is refused rather than
    sanitised, so two tenants can never collapse onto one directory."""
    if not _TENANT_RE.fullmatch(tenant_id or ""):
        raise InvalidShare("tenant id is not usable as a directory name")
    root = shares_root()
    path = (root / tenant_id).resolve()
    if not _inside(root, path):
        raise InvalidShare("tenant directory escapes the shares root")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_share_file(stored_path: str, tenant_id: str) -> Path:
    """Absolute path of a stored share file, guarded: it must sit inside this
    tenant's directory, whatever the row says."""
    base = tenant_dir(tenant_id)
    path = (shares_root() / stored_path).resolve()
    if not _inside(base, path):
        raise InvalidShare("stored share path escapes the tenant directory")
    return path


def _safe_extension(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if _EXT_RE.fullmatch(ext) else ""


# ---------------------------------------------------------------------------
# Content-type inference (open-ended; the user may correct it)
# ---------------------------------------------------------------------------


def infer_url_content_type(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path.lower()
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube_short" if path.startswith("/shorts/") else "youtube_video"
    if host.endswith("instagram.com"):
        return "instagram_reel" if "/reel" in path else "instagram_post"
    if host.endswith("tiktok.com"):
        return "tiktok_video"
    if host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.twitter.com"}:
        return "tweet"
    if host.endswith("reddit.com"):
        return "reddit_post"
    return "link"


def infer_file_content_type(filename: str, mime: str | None) -> str:
    mime = (mime or "").lower()
    ext = _safe_extension(filename)
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/") or ext in {".m4a", ".mp3", ".ogg", ".opus", ".wav"}:
        return "voice_memo"
    if mime.startswith("video/"):
        return "video_clip"
    if mime == "application/pdf" or ext == ".pdf":
        return "pdf"
    if mime in {"application/zip", "application/x-zip-compressed"} or ext == ".zip":
        return "archive"
    if mime.startswith("text/") or ext in {".txt", ".md"}:
        return "text_file"
    return "file"


def _validate_content_type(value: str) -> str:
    if not _CONTENT_TYPE_RE.fullmatch(value or ""):
        raise InvalidShare(
            "content_type must be lower-case letters, digits and underscores, "
            "starting with a letter (e.g. book_quote)"
        )
    return value


def _validate_surface(value: str) -> str:
    if value not in SURFACES:
        raise InvalidShare(f"unknown surface {value!r}")
    return value


def _clean_annotation(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > _ANNOTATION_MAX:
        raise ShareTooLarge(f"annotation is over {_ANNOTATION_MAX} characters")
    return value or None


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url or len(url) > _URL_MAX:
        raise InvalidShare("a URL is required (at most 2000 characters)")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise InvalidShare("only http and https links can be shared")
    return url


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def _new_share(
    *,
    tenant_id: str,
    user_id: str,
    surface: str,
    content_type: str,
    payload: dict,
    annotation: str | None,
    author_is_tenant: bool,
    extracted_text: str | None = None,
    share_id: str | None = None,
    file_path: str | None = None,
) -> Share:
    return Share(
        id=share_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        surface=_validate_surface(surface),
        content_type=_validate_content_type(content_type),
        raw_payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        extracted_text=extracted_text,
        user_annotation=_clean_annotation(annotation),
        author_is_tenant=bool(author_is_tenant),
        processing_state="pending",
        file_path=file_path,
    )


def share_source(source_url: str | None, source_title: str | None) -> dict | None:
    """Where a quote or an image came from (S-3.7.3): the page it was on.
    Stored in the payload as ``source``; the URL is validated like any share
    URL, and the title is trimmed."""
    if not source_url and not source_title:
        return None
    out: dict = {}
    if source_url:
        out["url"] = validate_url(source_url)
    title = " ".join((source_title or "").split())[:300]
    if title:
        out["title"] = title
    return out or None


def create_url_share(
    db: Session,
    tenant_id: str,
    user_id: str,
    *,
    url: str,
    annotation: str | None = None,
    content_type: str | None = None,
    author_is_tenant: bool = False,
    surface: str = "manual_quick_share",
    source: dict | None = None,
) -> Share:
    url = validate_url(url)
    share = _new_share(
        tenant_id=tenant_id,
        user_id=user_id,
        surface=surface,
        content_type=content_type or infer_url_content_type(url),
        payload={"kind": "url", "url": url, **({"source": source} if source else {})},
        annotation=annotation,
        author_is_tenant=author_is_tenant,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


def create_text_share(
    db: Session,
    tenant_id: str,
    user_id: str,
    *,
    text: str,
    annotation: str | None = None,
    content_type: str | None = None,
    author_is_tenant: bool = False,
    surface: str = "manual_quick_share",
    source: dict | None = None,
) -> Share:
    if not text or not text.strip():
        raise InvalidShare("text must not be blank")
    if len(text) > settings.ECHO_SHARE_TEXT_MAX_CHARS:
        raise ShareTooLarge(
            f"text is over {settings.ECHO_SHARE_TEXT_MAX_CHARS} characters; "
            "share it as a file instead"
        )
    share = _new_share(
        tenant_id=tenant_id,
        user_id=user_id,
        surface=surface,
        content_type=content_type or "text_snippet",
        payload={"kind": "text", "text": text, **({"source": source} if source else {})},
        annotation=annotation,
        author_is_tenant=author_is_tenant,
        # The words are the content; no extraction step stands between them
        # and the inbox. Embedding and signals are still S-3.7.2's.
        extracted_text=text,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


def create_file_share(
    db: Session,
    tenant_id: str,
    user_id: str,
    *,
    filename: str,
    data: bytes,
    mime: str | None = None,
    annotation: str | None = None,
    content_type: str | None = None,
    author_is_tenant: bool = False,
    surface: str = "manual_quick_share",
) -> Share:
    if not data:
        raise InvalidShare("the file is empty")
    if len(data) > settings.ECHO_SHARE_MAX_BYTES:
        raise ShareTooLarge(
            f"file is over {settings.ECHO_SHARE_MAX_BYTES // (1024 * 1024)} MB"
        )
    display_name = os.path.basename((filename or "").replace("\\", "/"))[:255] or "file"
    share_id = str(uuid.uuid4())
    directory = tenant_dir(tenant_id, create=True)
    target = (directory / f"{share_id}{_safe_extension(display_name)}").resolve()
    if not _inside(directory, target):  # belt and braces: the name is ours
        raise InvalidShare("refusing to write outside the tenant directory")
    stored = target.relative_to(shares_root()).as_posix()

    share = _new_share(
        tenant_id=tenant_id,
        user_id=user_id,
        surface=surface,
        content_type=content_type or infer_file_content_type(display_name, mime),
        payload={
            "kind": "file",
            "filename": display_name,
            "mime": mime or "application/octet-stream",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        annotation=annotation,
        author_is_tenant=author_is_tenant,
        share_id=share_id,
        file_path=stored,
    )
    target.write_bytes(data)
    try:
        db.add(share)
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(share)
    return share


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_share(db: Session, tenant_id: str, share_id: str) -> Share:
    share = (
        db.query(Share)
        .filter(Share.id == share_id, Share.tenant_id == tenant_id)
        .first()
    )
    if share is None:
        raise ShareNotFound(share_id)
    return share


def list_shares(
    db: Session,
    tenant_id: str,
    *,
    state: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    origin: str = "all",
    import_id: str | None = None,
) -> tuple[list[Share], int]:
    """Newest first. ``q`` matches the text, the annotation or the payload
    (a URL, a filename). ``origin`` narrows to shares handed over one at a
    time (``direct``) or written by an export import (``import``, S-3.7.5);
    ``import_id`` lists one import oldest first. Returns ``(page, total)``."""
    if state is not None and state not in PROCESSING_STATES:
        raise InvalidShare(f"unknown processing_state {state!r}")
    query = db.query(Share).filter(Share.tenant_id == tenant_id)
    if state is not None:
        query = query.filter(Share.processing_state == state)
    if import_id is not None:
        query = query.filter(Share.import_id == import_id)
    elif origin == "direct":
        query = query.filter(Share.import_id.is_(None))
    elif origin == "import":
        query = query.filter(Share.import_id.is_not(None))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Share.extracted_text.ilike(like),
                Share.user_annotation.ilike(like),
                Share.raw_payload_json.ilike(like),
            )
        )
    total = query.with_entities(func.count(Share.id)).scalar() or 0
    order = (
        (Share.occurred_at.asc(), Share.id.asc())
        if import_id is not None
        else (Share.received_at.desc(), Share.id.desc())
    )
    page = (
        query.order_by(*order)
        .offset(max(offset, 0))
        .limit(max(limit, 0))
        .all()
    )
    return page, int(total)


def count_shares(db: Session, tenant_id: str) -> int:
    return int(
        db.query(func.count(Share.id)).filter(Share.tenant_id == tenant_id).scalar() or 0
    )


def load_payload(share: Share) -> dict:
    try:
        data = json.loads(share.raw_payload_json or "{}")
    except (TypeError, ValueError):
        logger.warning("echo: corrupt raw_payload_json on share %s", share.id)
        return {}
    return data if isinstance(data, dict) else {}


def _id_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

_UNSET = object()


def update_share(
    db: Session,
    tenant_id: str,
    share_id: str,
    *,
    annotation: str | None | object = _UNSET,
    content_type: str | object = _UNSET,
    author_is_tenant: bool | object = _UNSET,
) -> Share:
    share = get_share(db, tenant_id, share_id)
    if annotation is not _UNSET:
        share.user_annotation = _clean_annotation(annotation)  # type: ignore[arg-type]
    if content_type is not _UNSET:
        share.content_type = _validate_content_type(content_type)  # type: ignore[arg-type]
    if author_is_tenant is not _UNSET:
        share.author_is_tenant = bool(author_is_tenant)
    share.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(share)
    return share


# ---------------------------------------------------------------------------
# Delete (one share, cascading)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShareDeletion:
    share_id: str
    vectors: int
    files: int
    derived_facts: int


def delete_share(db: Session, tenant_id: str, share_id: str) -> ShareDeletion:
    """Remove the share and everything derived from it (``delete_shares``)."""
    share = get_share(db, tenant_id, share_id)
    result = delete_shares(db, tenant_id, [share.id])
    return ShareDeletion(share_id, result.vectors, result.files, result.derived_facts)


_IN_CHUNK = 900


def delete_shares(db: Session, tenant_id: str, share_ids: list[str]) -> ShareDeletion:
    """Remove shares and everything derived from them, in bulk: the one
    cascade every delete path uses (a single share, an undone import,
    S-3.7.5). Vectors first (a Chroma failure raises and nothing else is
    touched), then files, then derived facts and the rows in one commit.
    Ids that are not this tenant's are ignored. ``share_id`` in the result is
    the first id, or "" for an empty list."""
    ids = list(dict.fromkeys(share_ids))
    # Only the columns the cascade needs: an undone import can be 100k+ rows.
    # Look up by primary key and check the tenant here: with the tenant in the
    # WHERE clause SQLite scans the tenant index once per chunk (quadratic).
    shares = []
    for i in range(0, len(ids), _IN_CHUNK):
        shares.extend(
            row
            for row in db.query(
                Share.id, Share.tenant_id, Share.file_path,
                Share.derived_fact_ids_json, Share.derived_signal_ids_json,
            )
            .filter(Share.id.in_(ids[i : i + _IN_CHUNK]))
            .all()
            if row.tenant_id == tenant_id
        )
    if not shares:
        return ShareDeletion(ids[0] if ids else "", 0, 0, 0)

    vectors = echo_vectors.delete_share_vectors(tenant_id, [s.id for s in shares])

    files = 0
    for share in shares:
        if not share.file_path:
            continue
        try:
            path = resolve_share_file(share.file_path, tenant_id)
        except InvalidShare:
            # A row whose path points outside this tenant's directory was
            # tampered with or corrupted. Never follow it; drop the row.
            logger.warning("echo: share %s has a file path outside its tenant dir", share.id)
            continue
        if path.exists():
            path.unlink()
            files += 1

    fact_ids = [fid for share in shares for fid in _id_list(share.derived_fact_ids_json)]
    facts = 0
    for i in range(0, len(fact_ids), _IN_CHUNK):
        facts += (
            db.query(PersonalContext)
            .filter(
                PersonalContext.id.in_(fact_ids[i : i + _IN_CHUNK]),
                PersonalContext.tenant_id == tenant_id,
            )
            .delete(synchronize_session=False)
        )
    # S-3.3.1: each share stops counting as evidence. Its examples leave the
    # signals it fed (listed in `derived_signal_ids_json`); a signal with no
    # source left is tombstoned as `source_deleted`.
    from app.models.activity_event import ActivityEvent
    from app.models.voice_signal_input import VoiceSignalInput
    from app.services import activity_event_service, echo_signal_service

    for share in shares:
        signal_ids = _id_list(share.derived_signal_ids_json)
        if signal_ids:
            echo_signal_service.withdraw_source(db, tenant_id, f"share:{share.id}", signal_ids=signal_ids)
    found = [s.id for s in shares]  # every one checked to be this tenant's above
    # The rows go by bulk statements, so detach any of them this session has
    # loaded, as db.delete() would: a caller holding one must not refresh it.
    gone = set(found)
    for obj in list(db.identity_map.values()):
        if isinstance(obj, Share):
            identity = sa_inspect(obj).identity
            if identity and identity[0] in gone:
                db.expunge(obj)
    for i in range(0, len(found), _IN_CHUNK):
        chunk = found[i : i + _IN_CHUNK]
        # S-3.2.1: and their "shared to Pratidhvani" events go with them (the
        # bulk form of activity_event_service.delete_share_event).
        db.query(ActivityEvent).filter(
            ActivityEvent.tenant_id == tenant_id,
            ActivityEvent.connector == activity_event_service.INTERNAL,
            ActivityEvent.external_id.in_([activity_event_service.share_external_id(sid) for sid in chunk]),
        ).delete(synchronize_session=False)
        # S-3.3.2: and out of the extraction ledger, with its style profile.
        db.query(VoiceSignalInput).filter(
            VoiceSignalInput.tenant_id == tenant_id,
            VoiceSignalInput.source_ref.in_([f"share:{sid}" for sid in chunk]),
        ).delete(synchronize_session=False)
        db.query(Share).filter(Share.id.in_(chunk)).delete(synchronize_session=False)
    db.commit()
    from app.services import echo_personal_vectors

    echo_personal_vectors.sync_soft(db, tenant_id)
    logger.info(
        "echo: tenant %s deleted %d share(s) (vectors=%d files=%d facts=%d)",
        tenant_id[:8], len(found), vectors, files, facts,
    )
    return ShareDeletion(found[0], vectors, files, facts)

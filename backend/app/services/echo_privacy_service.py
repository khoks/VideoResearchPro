"""Echo privacy: the full export and the full delete (S-3.10.1, S-3.10.2).

Both ship with the first new Echo table, so nothing Echo stores is ever
un-exportable or un-deletable (`personal-brain.md` § Privacy model).

**What "the brain" is.** Every table registered in ``ECHO_TABLES``, the
tenant's file directory under ``ECHO_SHARES_DIR``, and the tenant's vectors in
every Echo Chroma collection (``echo_vectors.echo_collection_names``). A new
Echo table, directory or collection must be registered here, or the export
will miss it and the delete will leave it behind; ``footprint`` is what the
tests and the endpoint use to prove nothing is left.

Not the brain, and untouched by both: the user's library (jobs, documents,
Q&A, notes — notes have their own export at ``/exports/notes.*``), their
account, their BYOK provider keys, and the audit log. The audit log records
that an export or a delete happened, with counts only, never content.

**The archive** is a zip:

- ``manifest.json`` — format, version, export time, tenant, row counts per
  table, every file with size and SHA-256, and any file a row points at that
  was missing on disk;
- ``<table>.jsonl`` — one row per line, every column, datetimes as ISO-8601
  with an explicit UTC offset, JSON-text columns kept as the stored text;
- ``files/<stored path>`` — the bytes, exactly.

``read_archive`` is its exact inverse; the round-trip test holds every column
of every row and every file's bytes to it. The archive includes third-party
share content: it is the user's own copy of what they handed over, the thing
Article 20 portability covers. "Never exported" for context-only content
applies to dataset and derived exports, not to this.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from sqlalchemy import DateTime, func, or_
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.echo_connector import (
    EchoConnectorCredential,
    EchoConnectorGrant,
    EchoConnectorOAuthState,
)
from app.models.personal_context import PersonalContext
from app.models.share import Share
from app.models.voice_signal import VoiceSignal
from app.services import echo_intake_service, echo_vectors

logger = logging.getLogger(__name__)

ARCHIVE_FORMAT = "pratidhvani-echo-archive"
ARCHIVE_VERSION = 1

# Every Echo table, in export order. (table name, model). Each has a
# `tenant_id` column; a new Echo table is added here or it is neither
# exported nor deleted.
ECHO_TABLES: tuple[tuple[str, Any], ...] = (
    ("personal_context", PersonalContext),
    ("shares_inbox", Share),
    # S-3.3.1: voice and personality signals, tombstones included.
    ("voice_signals", VoiceSignal),
    # S-3.2.1: what the user did, from connectors; and the grants themselves.
    ("activity_events", ActivityEvent),
    ("echo_connector_grants", EchoConnectorGrant),
)

# Echo tables that hold secrets: OAuth tokens (encrypted, D-043) and the PKCE
# verifiers of connects in flight (S-3.2.1). Counted in the footprint and
# erased by the full delete like every Echo table, but never written into an
# export, encrypted or not: the manifest says how many rows were withheld and
# why. A new secret store is registered here, not in ECHO_TABLES.
ECHO_SECRET_TABLES: tuple[tuple[str, Any], ...] = (
    ("echo_connector_credentials", EchoConnectorCredential),
    ("echo_connector_oauth_states", EchoConnectorOAuthState),
)
WITHHELD_REASON = (
    "Connector access tokens and pending sign-in state are secrets: they are "
    "erased with your brain but never leave the server, encrypted or not. "
    "Reconnect the connector to grant access again."
)

_BATCH = 200


class EchoPrivacyError(RuntimeError):
    """The delete could not finish; nothing past the failing store was touched."""


# ---------------------------------------------------------------------------
# Row <-> record
# ---------------------------------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def row_to_record(row: Any) -> dict[str, Any]:
    """Every column of ``row``, JSON-safe. Datetimes become ISO strings with
    an offset; everything else is stored as-is."""
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        value = getattr(row, col.key)
        if isinstance(value, datetime):
            value = _aware(value).isoformat()  # type: ignore[union-attr]
        out[col.name] = value
    return out


def row_columns(row: Any) -> dict[str, Any]:
    """Every column of ``row``, typed (datetimes UTC-aware). What
    ``read_archive`` must give back for the same row."""
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        value = getattr(row, col.key)
        out[col.name] = _aware(value) if isinstance(value, datetime) else value
    return out


def _datetime_columns(model: Any) -> set[str]:
    return {c.name for c in model.__table__.columns if isinstance(c.type, DateTime)}


def record_to_columns(model: Any, record: dict[str, Any]) -> dict[str, Any]:
    dt_cols = _datetime_columns(model)
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key in dt_cols and isinstance(value, str):
            value = datetime.fromisoformat(value)
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _iter_rows(db: Session, model: Any, tenant_id: str):
    query = db.query(model).filter(model.tenant_id == tenant_id)
    order = [model.__table__.primary_key.columns.values()[0]]
    yield from query.order_by(*order).yield_per(_BATCH)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_archive(db: Session, tenant_id: str, out: IO[bytes]) -> dict[str, Any]:
    """Write the tenant's brain to ``out`` as a zip. Returns the manifest."""
    manifest: dict[str, Any] = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "tables": {},
        "files": [],
        "missing_files": [],
        "scope": (
            "Echo only: facts, shares with their files, activity events and "
            "connector grants. Connector tokens are withheld (see withheld). "
            "Notes export separately (/api/v1/exports/notes.jsonl); the "
            "research library is not part of Echo."
        ),
    }
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        file_paths: list[str] = []
        for name, model in ECHO_TABLES:
            count = 0
            with zf.open(f"{name}.jsonl", "w", force_zip64=True) as fh:
                for row in _iter_rows(db, model, tenant_id):
                    fh.write((json.dumps(row_to_record(row), ensure_ascii=False) + "\n").encode("utf-8"))
                    count += 1
                    if model is Share and row.file_path:
                        file_paths.append(row.file_path)
            manifest["tables"][name] = {"file": f"{name}.jsonl", "rows": count}

        withheld = {
            name: int(
                db.query(func.count()).select_from(model).filter(model.tenant_id == tenant_id).scalar() or 0
            )
            for name, model in ECHO_SECRET_TABLES
        }
        manifest["withheld"] = {"tables": withheld, "reason": WITHHELD_REASON}

        for stored in file_paths:
            try:
                path = echo_intake_service.resolve_share_file(stored, tenant_id)
            except echo_intake_service.InvalidShare:
                manifest["missing_files"].append(stored)
                continue
            if not path.is_file():
                manifest["missing_files"].append(stored)
                continue
            zf.write(path, arcname=f"files/{stored}")
            manifest["files"].append(
                {"path": stored, "size": path.stat().st_size, "sha256": _sha256_file(path)}
            )

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def build_archive_file(db: Session, tenant_id: str) -> tuple[str, dict[str, Any]]:
    """Write the archive to a temporary file (constant memory) and return
    ``(path, manifest)``. The caller removes the file."""
    fd, path = tempfile.mkstemp(prefix="echo-export-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as fh:
            manifest = write_archive(db, tenant_id, fh)
    except Exception:
        os.unlink(path)
        raise
    return path, manifest


@dataclass
class EchoArchive:
    manifest: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)


def read_archive(src: str | os.PathLike | IO[bytes]) -> EchoArchive:
    """Inverse of ``write_archive``: typed rows per table and file bytes by
    stored path. Raises ``ValueError`` on anything that is not our archive or
    whose files do not match their recorded hashes."""
    with zipfile.ZipFile(src) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != ARCHIVE_FORMAT:
            raise ValueError("not a Pratidhvani Echo archive")
        if manifest.get("version") != ARCHIVE_VERSION:
            raise ValueError(f"unsupported archive version {manifest.get('version')!r}")
        archive = EchoArchive(manifest=manifest)
        models = dict(ECHO_TABLES)
        for name, meta in manifest["tables"].items():
            model = models.get(name)
            if model is None:
                raise ValueError(f"unknown table {name!r} in archive")
            rows = [
                record_to_columns(model, json.loads(line))
                for line in zf.read(meta["file"]).decode("utf-8").splitlines()
                if line.strip()
            ]
            if len(rows) != meta["rows"]:
                raise ValueError(f"{name}: manifest says {meta['rows']} rows, found {len(rows)}")
            archive.tables[name] = rows
        for entry in manifest["files"]:
            data = zf.read(f"files/{entry['path']}")
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"file {entry['path']} does not match its recorded hash")
            archive.files[entry["path"]] = data
    return archive


# ---------------------------------------------------------------------------
# Footprint and delete
# ---------------------------------------------------------------------------


def _files_on_disk(tenant_id: str) -> int:
    directory = echo_intake_service.tenant_dir(tenant_id)
    if not directory.exists():
        return 0
    return sum(1 for p in directory.rglob("*") if p.is_file())


def _tenant_filter(model: Any, tenant_id: str):
    # personal_context rows written before the tenant_id backfill keyed on
    # user_id only; on self-host they are the same value. Catch both.
    if model is PersonalContext:
        return or_(PersonalContext.tenant_id == tenant_id, PersonalContext.user_id == tenant_id)
    return model.tenant_id == tenant_id


def footprint(db: Session, tenant_id: str) -> dict[str, Any]:
    """Everything Echo holds for ``tenant_id``, counted in every store."""
    rows = {
        name: int(
            db.query(func.count()).select_from(model).filter(_tenant_filter(model, tenant_id)).scalar()
            or 0
        )
        for name, model in ECHO_TABLES + ECHO_SECRET_TABLES
    }
    return {
        "rows": rows,
        "files": _files_on_disk(tenant_id),
        "vectors": echo_vectors.count_tenant_vectors(tenant_id),
    }


def footprint_is_empty(fp: dict[str, Any]) -> bool:
    return (
        not any(fp["rows"].values())
        and fp["files"] == 0
        and not any(fp["vectors"].values())
    )


def delete_brain(db: Session, tenant_id: str) -> dict[str, Any]:
    """Remove everything Echo holds for ``tenant_id``.

    Order matters for retries: vectors, then files, then rows in one commit.
    A failure in an earlier store raises ``EchoPrivacyError`` before the rows
    go, so the rows that point at what is left still exist and a retry finds
    and removes it. Returns what was removed and the footprint afterwards,
    which must be empty.
    """
    # S-3.2.1: revoke every connector grant at its provider and drop its
    # schedule first. Best effort and never fatal: the tokens themselves are
    # erased below with the rows whatever the provider says.
    try:
        from app.services import echo_connector_service

        echo_connector_service.revoke_all_for_brain_delete(db, tenant_id)
    except Exception:
        logger.exception("echo: provider revocation before the full delete failed")

    try:
        vectors = echo_vectors.delete_tenant_vectors(tenant_id)
    except Exception as e:
        raise EchoPrivacyError(f"could not delete Echo vectors: {e}") from e

    directory = echo_intake_service.tenant_dir(tenant_id)
    files = _files_on_disk(tenant_id)
    if directory.exists():
        try:
            shutil.rmtree(directory)
        except OSError as e:
            raise EchoPrivacyError(f"could not delete Echo files: {e}") from e

    removed_rows: dict[str, int] = {}
    try:
        for name, model in ECHO_TABLES + ECHO_SECRET_TABLES:
            removed_rows[name] = (
                db.query(model)
                .filter(_tenant_filter(model, tenant_id))
                .delete(synchronize_session=False)
            )
        db.commit()
    except Exception as e:
        db.rollback()
        raise EchoPrivacyError(f"could not delete Echo rows: {e}") from e

    after = footprint(db, tenant_id)
    if not footprint_is_empty(after):
        logger.error("echo: delete_brain left data behind for %s: %s", tenant_id[:8], after)
        raise EchoPrivacyError(f"data left behind after delete: {after}")
    logger.info(
        "echo: tenant %s deleted the brain (rows=%s files=%d vectors=%s)",
        tenant_id[:8], removed_rows, files, vectors,
    )
    return {
        "removed": {"rows": removed_rows, "files": files, "vectors": vectors},
        "footprint_after": after,
    }

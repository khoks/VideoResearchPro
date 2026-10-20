"""Running export-file imports for Echo (S-3.7.5).

Three steps, the first two in the request:

1. **Preview** — detect the format and report what an import would produce
   (counts, participants, date range, warnings). Writes nothing.
2. **Run** — parse again with the user's options and write one share per item
   (``surface=file_import``, ``import_id`` set, ``occurred_at`` = when the
   message or note was written), in batches. The upload is never stored:
   only what the options allow reaches the database, so "redact the other
   party" means the other side of a chat is never written anywhere.
3. **Embed** — one batch pass over the import's shares into ``shares_global``
   (``echo.embed_import``, or inline, or off like share processing), with the
   same vector id and metadata as a single share, plus ``import_id``.

Undo deletes every share an import wrote through ``delete_shares``, the
same cascade a single delete uses, then the import row.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import IO, Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.echo_import import EchoImport
from app.models.share import Share
from app.connectors import registry
from app.connectors.archive import ExportUnreadable, ImportPreview, ImportSource
from app.connectors.base import ImportedShare
from app.services import echo_intake_service, echo_processing_service, echo_vectors

logger = logging.getLogger(__name__)

_BATCH = 1000
_EMBED_BATCH = 256
_SUPPORTED = "WhatsApp chat exports (.txt or .zip) and Google Keep notes from Google Takeout"


class ImportNotFound(LookupError):
    """No import with that id belongs to this tenant."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source(fileobj: IO[bytes], filename: str) -> ImportSource:
    source = ImportSource(fileobj, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES)
    source.check()
    return source


def _importer(source: ImportSource, name: str | None):
    """The registered ``ArchiveImporter`` for this upload: the one named, or
    the first whose ``sniff`` recognises the content, or the first whose
    ``accepts`` recognises the filename (S-3.2.1's registry)."""
    registry.load_builtin()
    if name:
        importer = registry.get_importer(name)
        if importer is None:
            raise ExportUnreadable(f"Unknown importer {name!r}.")
        return importer
    for candidate in registry.list_importers():
        importer = registry.get_importer(candidate)
        sniff = getattr(importer, "sniff", None)
        if sniff is None:
            continue
        try:
            if sniff(source):
                return importer
        except ExportUnreadable:
            raise
        except Exception:
            logger.exception("echo: importer %s failed to sniff %r", candidate, source.filename)
    importer = registry.importer_for(source.filename)
    if importer is None:
        raise ExportUnreadable(f"This file is not an export Echo can read yet. Supported: {_SUPPORTED}.")
    return importer


def _parse(importer, source: ImportSource, options: dict[str, Any], stats: dict[str, int], tenant_id: str):
    """Call ``parse`` with the extras when the importer takes them, else with
    the contract's arguments only."""
    try:
        return importer.parse(source, tenant_id=tenant_id, options=options, filename=source.filename, stats=stats)
    except TypeError:
        source.fileobj.seek(0)
        return importer.parse(source.fileobj, tenant_id=tenant_id)


def _preview(importer, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    """The importer's own preview, or a count of what ``parse`` yields."""
    own = getattr(importer, "preview", None)
    if own is not None:
        return own(source, options)
    counts = {"shares": 0, "events": 0, "facts": 0}
    for item in _parse(importer, source, {}, {}, tenant_id="preview"):
        counts["shares" if isinstance(item, ImportedShare) else "events" if hasattr(item, "event_type") else "facts"] += 1
    return ImportPreview(importer=importer.name, label=getattr(importer, "display_name", importer.name), summary=counts)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview(fileobj: IO[bytes], filename: str, *, importer: str | None = None,
            options: dict[str, Any] | None = None) -> ImportPreview:
    source = _source(fileobj, filename)
    return _preview(_importer(source, importer), source, dict(options or {}))


def _validated(importer_name: str, pv: ImportPreview, options: dict[str, Any]) -> dict[str, Any]:
    """Keep only options the importer declares, and check the ones that can
    be wrong (a WhatsApp ``self_name`` that is not in the chat)."""
    opts = {k: v for k, v in options.items() if k in pv.options}
    if importer_name == "whatsapp":
        names = {p["name"] for p in pv.participants}
        me = opts.get("self_name") or None
        if me is not None and me not in names:
            raise ExportUnreadable(f"{me!r} does not appear in this chat. Choose one of its participants.")
        if opts.get("redact_other_party") and me is None:
            raise ExportUnreadable("To keep only your own side of the chat, say which participant is you.")
        opts["self_name"] = me
        # Parse with the order the preview settled, so both passes agree.
        opts["date_order"] = opts.get("date_order") or pv.summary.get("date_order")
    return opts


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run_import(db: Session, user: Any, fileobj: IO[bytes], filename: str, *,
               importer: str | None = None, options: dict[str, Any] | None = None) -> EchoImport:
    source = _source(fileobj, filename)
    module = _importer(source, importer)
    raw_options = dict(options or {})
    pv = _preview(module, source, raw_options)
    opts = _validated(module.name, pv, raw_options)

    record = EchoImport(
        tenant_id=user.id,
        user_id=user.id,
        importer=module.name,
        filename=(filename or "upload")[-255:],
        status="importing",
        options_json=json.dumps(opts, ensure_ascii=False),
        summary_json=json.dumps(pv.summary, ensure_ascii=False, default=str),
    )
    db.add(record)
    db.commit()

    counts = {"shares": 0, "own_words": 0, "context_only": 0}
    stats: dict[str, int] = {}
    batch: list[dict[str, Any]] = []
    checked: set[str] = set()
    surface = echo_intake_service._validate_surface("file_import")
    try:
        for item in _parse(module, source, opts, stats, tenant_id=user.id):
            if not isinstance(item, ImportedShare):
                # Events and facts are stored by the importers that yield
                # them (S-3.7.5 part 2); none does yet.
                stats["not_stored"] = stats.get("not_stored", 0) + 1
                continue
            meta = dict(item.metadata or {})
            content_type = meta.pop("content_type", None) or getattr(module, "content_type", None) or "imported_text"
            text = item.text or item.title or item.url or ""
            if not text.strip():
                stats["skipped_empty"] = stats.get("skipped_empty", 0) + 1
                continue
            if content_type not in checked:
                checked.add(echo_intake_service._validate_content_type(content_type))
            provenance = {
                "importer": module.name,
                "import_id": record.id,
                "external_id": item.external_id,
                **{k: v for k, v in (("title", item.title), ("author", item.author), ("url", item.url)) if v},
                **meta,
            }
            now = _now()
            # Plain rows through one executemany per batch: an import can be
            # 100k+ shares, and ORM objects cost ten times as much to insert.
            batch.append({
                "id": str(uuid.uuid4()),
                "tenant_id": user.id,
                "user_id": user.id,
                "received_at": now,
                "updated_at": now,
                "surface": surface,
                "content_type": content_type,
                "raw_payload_json": json.dumps(
                    {"kind": "text", "import": provenance},
                    ensure_ascii=False, separators=(",", ":"), default=str,
                ),
                "extracted_text": text,
                "user_annotation": None,
                "author_is_tenant": bool(item.author_is_tenant),
                "processing_state": "pending",
                "import_id": record.id,
                "occurred_at": item.occurred_at,
            })
            counts["shares"] += 1
            counts["own_words" if item.author_is_tenant else "context_only"] += 1
            if len(batch) >= _BATCH:
                db.execute(insert(Share), batch)
                db.commit()
                batch = []
        if batch:
            db.execute(insert(Share), batch)
            db.commit()
    except Exception as e:
        db.rollback()
        record = db.get(EchoImport, record.id)
        record.status = "failed"
        record.error = str(e) if isinstance(e, ExportUnreadable) else f"Import stopped: {type(e).__name__}"
        record.counts_json = json.dumps({**counts, **stats})
        record.finished_at = _now()
        db.commit()
        logger.exception("echo: import %s failed after %d shares", record.id[:8], counts["shares"])
        raise

    record.counts_json = json.dumps({**counts, **stats, "embedded": 0})
    record.status = "embedding" if counts["shares"] else "done"
    if not counts["shares"]:
        record.finished_at = _now()
    db.commit()
    logger.info("echo: tenant %s imported %d %s shares (%s)", user.id[:8], counts["shares"], module.name, record.id[:8])
    if counts["shares"]:
        enqueue_embedding(db, record, user)
        db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------


def enqueue_embedding(db: Session, record: EchoImport, user: Any) -> str:
    """Same modes as share processing (``ECHO_SHARE_PROCESSING``); inline
    runs in the caller's session."""
    mode = (settings.ECHO_SHARE_PROCESSING or "off").lower()
    if mode == "off":
        return "off"
    if mode == "inline":
        embed_import(db, record.id)
        return "processed"
    try:
        from app.services import task_routing_service
        from app.tasks.echo_tasks import embed_import_task

        task_routing_service.dispatch_for_user(embed_import_task, user, record.id)
        return "queued"
    except Exception:
        logger.exception("echo: could not queue embedding for import %s", record.id)
        return "queue_failed"


def embed_import(db: Session, import_id: str) -> str:
    """Embed every pending share of an import, a batch at a time. Idempotent
    and resumable: only ``pending`` shares are picked up. Returns the status."""
    record = db.get(EchoImport, import_id)
    if record is None:
        return "missing"
    embedded = 0
    while True:
        db.refresh(record)
        if record.status == "deleting":
            return "deleting"
        rows = (
            db.query(Share)
            .filter(Share.tenant_id == record.tenant_id, Share.import_id == record.id,
                    Share.processing_state == "pending")
            .order_by(Share.id)
            .limit(_EMBED_BATCH)
            .all()
        )
        if not rows:
            break
        items = [
            (s.id, echo_processing_service.embed_text(s, None), echo_processing_service.vector_metadata(s))
            for s in rows
        ]
        try:
            ids = echo_vectors.upsert_share_vectors(items)
        except Exception as e:
            logger.exception("echo: embedding import %s failed", record.id[:8])
            record.status = "failed"
            record.error = f"Embedding failed: {type(e).__name__}. Retry picks up where it stopped."
            db.commit()
            return "failed"
        stamp = _now().isoformat()
        processing = json.dumps({"extractor": f"import:{record.importer}", "embedded": True, "processed_at": stamp})
        for share, vid in zip(rows, ids):
            share.embedding_id = vid
            share.processing_state = "processed"
            share.processing_json = processing
        embedded += len(rows)
        db.commit()
    counts = json.loads(record.counts_json or "{}")
    counts["embedded"] = counts.get("embedded", 0) + embedded
    record.counts_json = json.dumps(counts)
    record.status = "done"
    record.error = None
    record.finished_at = _now()
    db.commit()
    return "done"


# ---------------------------------------------------------------------------
# Read and undo
# ---------------------------------------------------------------------------


def list_imports(db: Session, tenant_id: str) -> list[EchoImport]:
    return (
        db.query(EchoImport)
        .filter(EchoImport.tenant_id == tenant_id)
        .order_by(EchoImport.created_at.desc(), EchoImport.id.desc())
        .all()
    )


def get_import(db: Session, tenant_id: str, import_id: str) -> EchoImport:
    record = db.get(EchoImport, import_id)
    if record is None or record.tenant_id != tenant_id:
        raise ImportNotFound(import_id)
    return record


def delete_import(db: Session, tenant_id: str, import_id: str) -> dict[str, int]:
    """Undo an import: every share it wrote, their vectors and whatever was
    derived from them, then the import row."""
    record = get_import(db, tenant_id, import_id)
    record.status = "deleting"
    db.commit()
    vectors = echo_vectors.delete_import_vectors(tenant_id, import_id)
    share_ids = [
        sid for (sid,) in db.query(Share.id).filter(Share.tenant_id == tenant_id, Share.import_id == import_id)
    ]
    # The same cascade as deleting one share, in bulk.
    result = echo_intake_service.delete_shares(db, tenant_id, share_ids)
    vectors += result.vectors
    facts = result.derived_facts
    db.delete(db.get(EchoImport, import_id))
    db.commit()
    logger.info("echo: tenant %s undid import %s (%d shares)", tenant_id[:8], import_id[:8], len(share_ids))
    return {"shares": len(share_ids), "vectors": vectors, "facts": facts}

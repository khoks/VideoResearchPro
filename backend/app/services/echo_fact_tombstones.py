"""Deleted derived facts stay deleted (T-3.2.4.4, accepted by D-110).

A connector's sync and an export importer write their derived facts with
``echo_service.record_context``, an upsert by ``(kind, key)``. Without a
record of the user's delete, the next sync re-created the fact. This module
owns that record (``echo_fact_tombstones``):

* ``record_for_fact`` is called by the user's delete paths
  (``echo_service.delete_context`` and ``revoke_source``) before the row
  goes. It records a tombstone only when the fact came from a connector
  (source ``connector:<name>``) or an importer (source ``import:<id>``,
  resolved to the importer's name); a fact the user typed has nothing that
  could bring it back.
* ``blocked_keys`` is what the sync and the importer ask before writing.
* ``list_for_tenant`` and ``clear`` back the Echo page's "Kept deleted" list.

Not recorded: disconnecting a connector, undoing an import or deleting a
share. Those remove what a source brought in; they are not the user saying a
particular fact is wrong, and the source is gone anyway.

Nothing here commits: the caller's delete and the tombstone land together.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.echo_fact_tombstone import EchoFactTombstone

logger = logging.getLogger(__name__)

CONNECTOR_SOURCE = "connector:"
IMPORT_SOURCE = "import:"


def connector_of_source(db: Session, tenant_id: str, source: str | None) -> str | None:
    """The connector or importer that would write a fact with ``source``
    again, or None for a fact nothing re-creates (typed by the user)."""
    if not source:
        return None
    if source.startswith(CONNECTOR_SOURCE):
        return source[len(CONNECTOR_SOURCE):] or None
    if source.startswith(IMPORT_SOURCE):
        from app.models.echo_import import EchoImport

        record = db.get(EchoImport, source[len(IMPORT_SOURCE):])
        if record is not None and record.tenant_id == tenant_id:
            return record.importer
    return None


def record(db: Session, tenant_id: str, connector: str, kind: str, key: str) -> EchoFactTombstone:
    """Idempotent. Does not commit."""
    row = (
        db.query(EchoFactTombstone)
        .filter(
            EchoFactTombstone.tenant_id == tenant_id,
            EchoFactTombstone.connector == connector,
            EchoFactTombstone.kind == kind,
            EchoFactTombstone.key == key,
        )
        .first()
    )
    if row is None:
        row = EchoFactTombstone(tenant_id=tenant_id, connector=connector, kind=kind, key=key)
        db.add(row)
        db.flush()
    return row


def record_for_fact(db: Session, fact: Any) -> EchoFactTombstone | None:
    """Tombstone ``fact`` (a ``PersonalContext`` row about to be deleted by
    the user) when a connector or importer derived it. Does not commit."""
    tenant_id = fact.tenant_id or fact.user_id
    connector = connector_of_source(db, tenant_id, fact.source)
    if connector is None:
        return None
    return record(db, tenant_id, connector, fact.kind, fact.key)


def blocked_keys(db: Session, tenant_id: str, connector: str) -> set[tuple[str, str]]:
    """``(kind, key)`` pairs ``connector`` must not write for ``tenant_id``."""
    return {
        (kind, key)
        for kind, key in db.query(EchoFactTombstone.kind, EchoFactTombstone.key).filter(
            EchoFactTombstone.tenant_id == tenant_id, EchoFactTombstone.connector == connector
        )
    }


def list_for_tenant(db: Session, tenant_id: str) -> list[EchoFactTombstone]:
    return (
        db.query(EchoFactTombstone)
        .filter(EchoFactTombstone.tenant_id == tenant_id)
        .order_by(EchoFactTombstone.created_at.desc(), EchoFactTombstone.id)
        .all()
    )


def clear(db: Session, tenant_id: str, tombstone_id: str) -> bool:
    """Let the connector write this fact again (at its next sync). Commits.
    False when the tombstone is not the tenant's."""
    row = db.get(EchoFactTombstone, tombstone_id)
    if row is None or row.tenant_id != tenant_id:
        return False
    db.delete(row)
    db.commit()
    logger.info("echo: tenant %s cleared a %s fact tombstone", tenant_id[:8], row.connector)
    return True


def connector_label(name: str) -> str:
    """The connector's or importer's display name, for the Echo page."""
    from app.connectors import registry

    registry.load_builtin()
    found = registry.get_connector(name) or registry.get_importer(name)
    return getattr(found, "display_name", None) or name

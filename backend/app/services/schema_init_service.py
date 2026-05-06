"""Schema initialisation — E-4.10 fix.

Replaces the historical ``Base.metadata.create_all`` lifespan hook
with an Alembic-managed schema-init that handles three cases cleanly:

1. **Fresh install** (no DB / empty DB, no alembic_version table) —
   run ``alembic upgrade head``. Equivalent to the old create_all
   behaviour but goes through the proper migration path.

2. **Up-to-date install** (alembic_version == head) — no-op. Most
   common case after the first boot.

3. **Existing install at intermediate revision** (alembic_version <
   head) — try ``alembic upgrade head``. If the upgrade fails because
   `Base.metadata.create_all` from a previous version already created
   the new tables (the E-4.10 conflict), detect that the live schema
   already matches ORM metadata and auto-stamp head as a recovery.
   Otherwise propagate the real failure.

The auto-stamp path closes the upgrade-path bug for operators who
installed before this session's migrations: their tables exist (via
the old lifespan create_all) but ``alembic_version`` is stale, so
plain ``alembic upgrade head`` fails. The detection is conservative —
auto-stamp only when **every ORM table exists in the DB AND every DB
table is in the ORM** (no drift in either direction). Mismatches log
loudly and require manual operator intervention rather than silent
papering-over.

Tests in ``tests/test_services/test_schema_init.py`` exercise all
three cases plus the conflict-recovery path.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import MetaData, create_engine, inspect

logger = logging.getLogger(__name__)


def _alembic_config():
    """Build an Alembic Config pointed at this package's alembic.ini.
    Lazy import so tests can patch around it cleanly."""
    import os

    from alembic.config import Config

    # alembic.ini lives at backend/alembic.ini next to this service.
    # We resolve relative to the app package so the path holds when
    # the lifespan runs from any cwd.
    here = os.path.abspath(os.path.dirname(__file__))
    backend_root = os.path.abspath(os.path.join(here, "..", ".."))
    return Config(os.path.join(backend_root, "alembic.ini"))


def _current_db_revision(engine) -> str | None:
    """Read the current alembic_version from the live DB. Returns
    None if the table doesn't exist yet (fresh install)."""
    insp = inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        return None
    with engine.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        return row[0] if row else None


def _head_revision(cfg) -> str:
    """Resolve the alembic head revision from the migration scripts.
    Single-head only — branching is not used in this project."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no migration scripts to resolve head from")
    return head


def _live_table_names(engine) -> set[str]:
    """Names of every table currently in the DB (excluding alembic_version)."""
    insp = inspect(engine)
    return {t for t in insp.get_table_names() if t != "alembic_version"}


def _orm_table_names(orm_metadata: MetaData) -> set[str]:
    return set(orm_metadata.tables.keys())


def _schema_matches_orm(engine, orm_metadata: MetaData) -> bool:
    """True iff every ORM table exists in the DB AND every DB table is
    in the ORM. Strict bidirectional match — a DB-only table (orphan
    migration) or an ORM-only table (missing migration) returns False."""
    return _live_table_names(engine) == _orm_table_names(orm_metadata)


def ensure_schema_at_head(
    db_url: str,
    orm_metadata: MetaData,
    *,
    cfg=None,
    upgrade_fn=None,
    stamp_fn=None,
) -> str:
    """Bring the DB schema to alembic head. Returns one of:
    ``"already_at_head"`` / ``"upgraded"`` / ``"stamped_recovery"`` /
    ``"fresh_install"`` so callers (and tests) can verify the path
    taken. Raises if the schema is in a state we can't safely recover.

    Hooks: ``cfg``, ``upgrade_fn``, ``stamp_fn`` are injection points
    used by tests to avoid touching real Alembic from unit tests.
    Production callers pass nothing.
    """
    from alembic import command

    cfg = cfg or _alembic_config()
    cfg.set_main_option("sqlalchemy.url", db_url)
    upgrade_fn = upgrade_fn or command.upgrade
    stamp_fn = stamp_fn or command.stamp

    engine = create_engine(db_url)
    try:
        head = _head_revision(cfg)
        current = _current_db_revision(engine)

        if current is None and not _live_table_names(engine):
            # Case 1: truly fresh — no tables, no alembic_version.
            logger.info("schema_init: fresh install detected; running alembic upgrade head")
            upgrade_fn(cfg, "head")
            return "fresh_install"

        if current == head:
            # Case 2: already at head, skip everything.
            logger.debug("schema_init: alembic at head (%s); no-op", head)
            return "already_at_head"

        if current is None and _live_table_names(engine):
            # Edge case: tables exist but no alembic_version. Either
            # the operator manually stamped or a tool wiped the version
            # table. Trust the schema; stamp head if it matches ORM.
            if _schema_matches_orm(engine, orm_metadata):
                logger.warning(
                    "schema_init: tables present but alembic_version is missing. "
                    "Schema matches ORM at head — stamping head to recover."
                )
                stamp_fn(cfg, "head")
                return "stamped_recovery"
            raise RuntimeError(
                "schema_init: tables exist but alembic_version is missing AND the "
                "schema does NOT match the ORM. Manual operator intervention required: "
                "inspect the DB and `alembic stamp <revision>` to the matching state."
            )

        # Case 3: alembic_version is set but < head. Try the normal upgrade.
        try:
            upgrade_fn(cfg, "head")
            logger.info("schema_init: upgraded from %s to %s", current, head)
            return "upgraded"
        except Exception as e:
            # Detect the create_all conflict signature: the upgrade
            # tried to CREATE TABLE for a table that already exists.
            msg = str(e).lower()
            if "already exists" in msg and _schema_matches_orm(engine, orm_metadata):
                logger.warning(
                    "schema_init: alembic upgrade failed because tables already "
                    "exist (likely created by a pre-E-4.10 lifespan create_all "
                    "call), but the schema matches ORM at head. Auto-stamping "
                    "head to recover. Original error: %s",
                    e,
                )
                stamp_fn(cfg, "head")
                return "stamped_recovery"
            # Real failure — propagate.
            raise
    finally:
        engine.dispose()

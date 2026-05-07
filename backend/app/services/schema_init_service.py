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


def _live_columns(engine, table: str) -> set[str]:
    """Names of every column on ``table`` in the live DB."""
    insp = inspect(engine)
    return {col["name"] for col in insp.get_columns(table)}


def _orm_columns(orm_metadata: MetaData, table: str) -> set[str]:
    """Names of every column on ``table`` in the ORM."""
    if table not in orm_metadata.tables:
        return set()
    return {c.name for c in orm_metadata.tables[table].columns}


def _column_drift(engine, orm_metadata: MetaData) -> dict[str, dict[str, set[str]]]:
    """For every table common to both ORM and DB, return
    ``{table: {"missing_in_db": {col1, ...}, "extra_in_db": {col2, ...}}}``.

    Tables only exist in the result dict when there's a mismatch. Empty
    dict means columns match across the board.

    Used by the auto-recovery path in ``ensure_schema_at_head``. Only
    ``missing_in_db`` is auto-fixable (we ADD COLUMN); ``extra_in_db``
    requires manual operator intervention because columns being in the
    DB but not the ORM means real schema drift we can't safely guess at.
    """
    common = _live_table_names(engine) & _orm_table_names(orm_metadata)
    drift: dict[str, dict[str, set[str]]] = {}
    for table in common:
        live = _live_columns(engine, table)
        orm = _orm_columns(orm_metadata, table)
        missing = orm - live
        extra = live - orm
        if missing or extra:
            drift[table] = {"missing_in_db": missing, "extra_in_db": extra}
    return drift


def _add_missing_columns(
    engine, orm_metadata: MetaData, drift: dict[str, dict[str, set[str]]]
) -> int:
    """Apply ``ALTER TABLE <t> ADD COLUMN <c> ...`` for every missing
    column in the drift dict. Uses the ORM column's compiled DDL so
    the column type, NOT NULL, default value, and server_default match
    what an Alembic ``op.add_column`` would have produced.

    Returns the number of columns added.

    Caller is responsible for ensuring this is safe — typically only
    runs after ``_schema_matches_orm()`` has already confirmed the
    table set matches and the only diffs are additive columns.
    """
    from sqlalchemy import text
    from sqlalchemy.schema import CreateColumn

    added = 0
    with engine.begin() as conn:
        for table_name, diff in drift.items():
            missing = diff.get("missing_in_db", set())
            if not missing:
                continue
            orm_table = orm_metadata.tables[table_name]
            for col_name in missing:
                col = orm_table.columns[col_name]
                # CompileColumn DDL via the dialect so we get the right type
                # syntax, NOT NULL, server_default, etc. for SQLite vs Postgres.
                col_ddl = str(
                    CreateColumn(col).compile(dialect=conn.engine.dialect)
                )
                # SQLite ALTER TABLE syntax accepts the column DDL fragment
                # directly. For columns that are NOT NULL with no default,
                # SQLite will refuse on a non-empty table — server_default
                # on the column is what makes those work cleanly.
                stmt = f'ALTER TABLE "{table_name}" ADD COLUMN {col_ddl}'
                logger.info("schema_init: adding missing column: %s", stmt)
                conn.execute(text(stmt))
                added += 1
    return added


def _attempt_recovery(
    engine,
    orm_metadata: MetaData,
    cfg,
    stamp_fn,
    *,
    reason: str,
) -> str:
    """Shared recovery path used by both the no-alembic-version edge case
    and the upgrade-failed-with-already-exists case.

    Recovery sequence:
    1. Confirm the table set matches ORM bidirectionally. If not → raise
       (drift requires manual intervention).
    2. Detect column drift. If only ``missing_in_db`` columns exist (purely
       additive drift), apply ALTER TABLE ADD COLUMN for each one and
       continue.
    3. If ``extra_in_db`` columns exist (DB has columns ORM doesn't), refuse
       — that's destructive drift we can't safely guess at.
    4. Stamp head.
    """
    if not _schema_matches_orm(engine, orm_metadata):
        live = _live_table_names(engine)
        orm = _orm_table_names(orm_metadata)
        raise RuntimeError(
            f"schema_init: {reason}. Schema does NOT match the ORM "
            f"(ORM-only tables: {sorted(orm - live)}; DB-only tables: "
            f"{sorted(live - orm)}). Manual operator intervention required: "
            f"inspect the DB and `alembic stamp <revision>` or run the "
            f"missing migrations manually."
        )

    drift = _column_drift(engine, orm_metadata)
    if drift:
        # If any table has DB-only columns, refuse — that's destructive drift.
        for table, diff in drift.items():
            if diff.get("extra_in_db"):
                raise RuntimeError(
                    f"schema_init: {reason}. Tables match but column drift is "
                    f"non-additive — table '{table}' has DB-only columns "
                    f"{sorted(diff['extra_in_db'])} that aren't in the ORM. "
                    f"Manual operator intervention required."
                )
        # Pure additive drift — auto-fix by ALTER TABLE ADD COLUMN.
        added = _add_missing_columns(engine, orm_metadata, drift)
        logger.warning(
            "schema_init: %s. Tables matched but %d additive columns were "
            "missing in the DB; added them via ALTER TABLE before stamping.",
            reason,
            added,
        )

    logger.warning(
        "schema_init: %s. Stamping head as recovery.", reason
    )
    stamp_fn(cfg, "head")
    return "stamped_recovery"


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
            # table. Trust the schema if tables match + we can heal
            # additive column drift; refuse otherwise.
            return _attempt_recovery(
                engine, orm_metadata, cfg, stamp_fn,
                reason="tables present but alembic_version is missing",
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
            if "already exists" in msg:
                return _attempt_recovery(
                    engine, orm_metadata, cfg, stamp_fn,
                    reason=f"alembic upgrade failed (likely pre-E-4.10 create_all): {e}",
                )
            # Real failure — propagate.
            raise
    finally:
        engine.dispose()

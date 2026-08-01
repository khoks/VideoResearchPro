"""Tests for E-4.10 schema_init_service — Alembic-managed schema init.

Covers all four code paths:

- ``fresh_install`` — empty DB, no alembic_version table.
- ``already_at_head`` — DB at head, no-op.
- ``upgraded`` — DB at intermediate revision, normal upgrade succeeds.
- ``stamped_recovery`` — DB has all the tables (via pre-E-4.10
  ``create_all``) but alembic_version is stale; upgrade fails on
  "table already exists"; the service detects the schema matches ORM
  and auto-stamps head.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.orm import declarative_base


@pytest.fixture
def temp_db():
    """A throwaway SQLite file we can put through every code path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # service expects to create the file via sqlite
    url = f"sqlite:///{path}"
    yield url, path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def fake_orm_metadata():
    """A minimal ORM metadata with two tables for the schema-match check."""
    base = declarative_base()
    md = base.metadata
    from sqlalchemy import Column, Integer, String, Table

    Table("foo", md, Column("id", Integer, primary_key=True))
    Table("bar", md, Column("id", Integer, primary_key=True), Column("v", String(32)))
    return md


def _create_tables_via_metadata(url: str, metadata: MetaData) -> None:
    eng = create_engine(url)
    metadata.create_all(bind=eng)
    eng.dispose()


def _set_alembic_version(url: str, rev: str) -> None:
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
            {"r": rev},
        )
    eng.dispose()


def _read_alembic_version(url: str) -> str | None:
    eng = create_engine(url)
    insp = inspect(eng)
    if "alembic_version" not in insp.get_table_names():
        eng.dispose()
        return None
    with eng.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    eng.dispose()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Case 1: fresh_install
# ---------------------------------------------------------------------------


def test_fresh_install_runs_upgrade(temp_db, fake_orm_metadata, monkeypatch):
    from app.services import schema_init_service as svc

    url, _ = temp_db
    upgrade_calls: list = []
    fake_cfg = MagicMock()

    def fake_upgrade(cfg, target):
        upgrade_calls.append((cfg, target))
        # Simulate the upgrade by creating the ORM tables.
        _create_tables_via_metadata(url, fake_orm_metadata)
        _set_alembic_version(url, "head_revision_x")

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    result = svc.ensure_schema_at_head(
        url,
        fake_orm_metadata,
        cfg=fake_cfg,
        upgrade_fn=fake_upgrade,
        stamp_fn=MagicMock(),
    )
    assert result == "fresh_install"
    assert upgrade_calls == [(fake_cfg, "head")]
    assert _read_alembic_version(url) == "head_revision_x"


# ---------------------------------------------------------------------------
# Case 2: already_at_head
# ---------------------------------------------------------------------------


def test_already_at_head_is_noop(temp_db, fake_orm_metadata, monkeypatch):
    from app.services import schema_init_service as svc

    url, _ = temp_db
    _create_tables_via_metadata(url, fake_orm_metadata)
    _set_alembic_version(url, "head_revision_x")

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    upgrade_fn = MagicMock()
    stamp_fn = MagicMock()
    result = svc.ensure_schema_at_head(
        url,
        fake_orm_metadata,
        cfg=MagicMock(),
        upgrade_fn=upgrade_fn,
        stamp_fn=stamp_fn,
    )
    assert result == "already_at_head"
    upgrade_fn.assert_not_called()
    stamp_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Case 3: upgraded — DB at intermediate revision, normal upgrade succeeds
# ---------------------------------------------------------------------------


def test_upgraded_when_at_intermediate_revision(temp_db, fake_orm_metadata, monkeypatch):
    from app.services import schema_init_service as svc

    url, _ = temp_db
    # Existing DB at older revision; tables not yet created.
    _set_alembic_version(url, "older_rev")

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    def fake_upgrade(cfg, target):
        _create_tables_via_metadata(url, fake_orm_metadata)
        _set_alembic_version(url, "head_revision_x")

    result = svc.ensure_schema_at_head(
        url,
        fake_orm_metadata,
        cfg=MagicMock(),
        upgrade_fn=fake_upgrade,
        stamp_fn=MagicMock(),
    )
    assert result == "upgraded"
    assert _read_alembic_version(url) == "head_revision_x"


# ---------------------------------------------------------------------------
# Case 4: stamped_recovery — the E-4.10 conflict
# ---------------------------------------------------------------------------


def test_stamped_recovery_when_create_all_already_made_tables(
    temp_db, fake_orm_metadata, monkeypatch
):
    """The bug case: pre-E-4.10 lifespan ran create_all + advanced
    alembic_version up to some revision; new tables were added by
    later migrations + create_all, but alembic_version stayed at the
    older revision. `alembic upgrade head` would fail with "table
    already exists"; service auto-stamps head when the schema matches
    the ORM."""
    from app.services import schema_init_service as svc

    url, _ = temp_db
    # Simulate the conflict: tables exist (via "create_all"), version stale.
    _create_tables_via_metadata(url, fake_orm_metadata)
    _set_alembic_version(url, "older_rev")

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    def fake_upgrade(cfg, target):
        # Simulate Alembic's "table already exists" error.
        raise RuntimeError("(sqlite3.OperationalError) table foo already exists")

    stamp_calls: list = []

    def fake_stamp(cfg, target):
        stamp_calls.append((cfg, target))
        _set_alembic_version(url, "head_revision_x")

    result = svc.ensure_schema_at_head(
        url,
        fake_orm_metadata,
        cfg=MagicMock(),
        upgrade_fn=fake_upgrade,
        stamp_fn=fake_stamp,
    )
    assert result == "stamped_recovery"
    assert stamp_calls == [(stamp_calls[0][0], "head")]
    assert _read_alembic_version(url) == "head_revision_x"


def test_stamp_NOT_attempted_when_schema_drifts(temp_db, fake_orm_metadata, monkeypatch):
    """If tables exist but DON'T match the ORM, auto-stamping would
    paper over real schema drift. Service must propagate the original
    error rather than recover."""
    from app.services import schema_init_service as svc

    url, _ = temp_db
    # Create only ONE of the ORM's tables — schema drift.
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE foo (id INTEGER PRIMARY KEY)"))
    eng.dispose()
    _set_alembic_version(url, "older_rev")

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    def fake_upgrade(cfg, target):
        raise RuntimeError("(sqlite3.OperationalError) table foo already exists")

    stamp_fn = MagicMock()
    with pytest.raises(RuntimeError, match="already exists"):
        svc.ensure_schema_at_head(
            url,
            fake_orm_metadata,
            cfg=MagicMock(),
            upgrade_fn=fake_upgrade,
            stamp_fn=stamp_fn,
        )
    stamp_fn.assert_not_called()


def test_no_alembic_version_but_schema_matches_recovers(
    temp_db, fake_orm_metadata, monkeypatch
):
    """A weirder edge case: tables exist but alembic_version table is
    missing entirely (e.g. operator wiped it). If the schema matches,
    recover by stamping head."""
    from app.services import schema_init_service as svc

    url, _ = temp_db
    _create_tables_via_metadata(url, fake_orm_metadata)
    # Don't create alembic_version at all.

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    stamp_calls: list = []

    def fake_stamp(cfg, target):
        stamp_calls.append((cfg, target))
        _set_alembic_version(url, "head_revision_x")

    result = svc.ensure_schema_at_head(
        url,
        fake_orm_metadata,
        cfg=MagicMock(),
        upgrade_fn=MagicMock(),
        stamp_fn=fake_stamp,
    )
    assert result == "stamped_recovery"
    assert _read_alembic_version(url) == "head_revision_x"


def test_no_alembic_version_AND_schema_drifts_raises(temp_db, fake_orm_metadata, monkeypatch):
    """Tables exist + alembic_version missing + drift from ORM →
    operator must intervene; service refuses to guess."""
    from app.services import schema_init_service as svc

    url, _ = temp_db
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE foo (id INTEGER PRIMARY KEY)"))
    eng.dispose()

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    with pytest.raises(RuntimeError, match="(?i)manual operator intervention"):
        svc.ensure_schema_at_head(
            url,
            fake_orm_metadata,
            cfg=MagicMock(),
            upgrade_fn=MagicMock(),
            stamp_fn=MagicMock(),
        )


# ---------------------------------------------------------------------------
# End-to-end: real Alembic against a real fresh SQLite + the project's ORM
# ---------------------------------------------------------------------------


def test_real_alembic_fresh_install_reaches_head(tmp_path):
    """Smoke test against the project's actual migrations + ORM.
    Validates that the service works end-to-end with no mocking."""
    from app.database import Base
    from app.services.schema_init_service import ensure_schema_at_head
    # Touch all model imports so Base.metadata is populated.
    import app.models  # noqa: F401  (registers all tables on Base.metadata)

    db_path = tmp_path / "test_real.db"
    url = f"sqlite:///{db_path}"

    result = ensure_schema_at_head(url, Base.metadata)
    assert result == "fresh_install"

    # Re-running is idempotent: now at head, second call is no-op.
    result2 = ensure_schema_at_head(url, Base.metadata)
    assert result2 == "already_at_head"

    # Schema matches ORM bidirectionally.
    eng = create_engine(url)
    insp = inspect(eng)
    db_tables = set(insp.get_table_names()) - {"alembic_version"}
    orm_tables = set(Base.metadata.tables.keys())
    eng.dispose()
    assert db_tables == orm_tables


def test_recovery_adds_missing_columns_for_additive_drift(temp_db, monkeypatch):
    """T-4.10.6: when create_all ran with an OLDER ORM (no
    failed_login_attempts col on users) and the new ORM has it,
    recovery should ADD COLUMN, not just stamp head."""
    from sqlalchemy import Column, Integer, MetaData, String, Table

    from app.services import schema_init_service as svc

    url, _ = temp_db

    # Build the OLD ORM (no failed_login_attempts).
    old_md = MetaData()
    Table("users", old_md, Column("id", Integer, primary_key=True), Column("email", String(64)))

    # Create tables matching the OLD ORM (simulate pre-E-5.4 create_all).
    eng = create_engine(url)
    old_md.create_all(bind=eng)
    eng.dispose()
    _set_alembic_version(url, "older_rev")

    # Now construct the NEW ORM with the additive column.
    new_md = MetaData()
    Table(
        "users", new_md,
        Column("id", Integer, primary_key=True),
        Column("email", String(64)),
        Column("failed_login_attempts", Integer, nullable=False, server_default="0"),
    )

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    def fake_upgrade(cfg, target):
        raise RuntimeError("(sqlite3.OperationalError) table users already exists")

    stamp_calls: list = []

    def fake_stamp(cfg, target):
        stamp_calls.append((cfg, target))
        _set_alembic_version(url, "head_revision_x")

    result = svc.ensure_schema_at_head(
        url, new_md,
        cfg=MagicMock(),
        upgrade_fn=fake_upgrade,
        stamp_fn=fake_stamp,
    )
    assert result == "stamped_recovery"

    # Verify the column was actually added.
    eng = create_engine(url)
    insp = inspect(eng)
    cols = {c["name"] for c in insp.get_columns("users")}
    eng.dispose()
    assert "failed_login_attempts" in cols


def test_recovery_refuses_when_db_has_extra_columns(temp_db, monkeypatch):
    """T-4.10.6: if the DB has a column the ORM doesn't, that's
    destructive drift — refuse to recover (can't safely DROP COLUMN)."""
    from sqlalchemy import Column, Integer, MetaData, String, Table

    from app.services import schema_init_service as svc

    url, _ = temp_db

    # DB has an extra `legacy_field` column.
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(64), legacy_field VARCHAR(32))"
        ))
    eng.dispose()
    _set_alembic_version(url, "older_rev")

    # ORM doesn't have legacy_field.
    new_md = MetaData()
    Table("users", new_md, Column("id", Integer, primary_key=True), Column("email", String(64)))

    monkeypatch.setattr(svc, "_head_revision", lambda cfg: "head_revision_x")

    def fake_upgrade(cfg, target):
        raise RuntimeError("(sqlite3.OperationalError) table users already exists")

    with pytest.raises(RuntimeError, match="non-additive"):
        svc.ensure_schema_at_head(
            url, new_md,
            cfg=MagicMock(),
            upgrade_fn=fake_upgrade,
            stamp_fn=MagicMock(),
        )


def test_real_alembic_recovers_from_column_drift(tmp_path):
    """End-to-end: simulate the actual production scenario where
    create_all ran with the pre-E-5.4 ORM (users table without
    failed_login_attempts), then we upgrade the code and run
    ensure_schema_at_head. Verify it auto-recovers + the column
    is now present."""
    from sqlalchemy import Column, Integer, MetaData, String, Table

    from app.database import Base
    from app.services.schema_init_service import ensure_schema_at_head
    import app.models  # noqa: F401  (registers all tables on Base.metadata)

    db_path = tmp_path / "test_column_drift.db"
    url = f"sqlite:///{db_path}"

    # Step 1: create the schema with an OLD-ORM users table (no
    # failed_login_attempts / locked_until columns).
    old_md = MetaData()
    # Mirror the rest of the schema from the real ORM but rebuild
    # `users` minus the new columns.
    for tname, t in Base.metadata.tables.items():
        if tname == "users":
            Table(
                tname, old_md,
                Column("id", String(36), primary_key=True),
                Column("email", String(255), unique=True, nullable=False),
                Column("password_hash", String(255), nullable=False),
                Column("created_at", String(64), nullable=False),
                Column("tier", String(16), nullable=False, server_default="free"),
            )
        else:
            t.to_metadata(old_md)
    eng = create_engine(url)
    old_md.create_all(bind=eng)
    eng.dispose()

    # Step 2: stamp at the pre-E-5.4 revision.
    _set_alembic_version(url, "f7a8b9c0d1e2")

    # Step 3: ensure_schema_at_head should detect the drift, ADD the
    # missing columns, then stamp head.
    result = ensure_schema_at_head(url, Base.metadata)
    assert result == "stamped_recovery"

    # Step 4: the missing columns are now present.
    eng = create_engine(url)
    insp = inspect(eng)
    user_cols = {c["name"] for c in insp.get_columns("users")}
    eng.dispose()
    assert "failed_login_attempts" in user_cols
    assert "locked_until" in user_cols


def test_real_alembic_recovers_from_create_all_conflict(tmp_path):
    """End-to-end E-4.10 conflict reproduction: simulate the operator
    state where tables exist (via create_all-like construction) but
    alembic_version is at an older revision."""
    from app.database import Base
    from app.services.schema_init_service import ensure_schema_at_head
    import app.models  # noqa: F401  (registers all tables on Base.metadata)

    db_path = tmp_path / "test_conflict.db"
    url = f"sqlite:///{db_path}"

    # Step 1: create all tables directly from the ORM (simulates the
    # pre-E-4.10 lifespan create_all).
    eng = create_engine(url)
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    # Step 2: force alembic_version to a stale older revision (a real
    # mid-migrations revision so that "upgrade head" tries to do real work).
    _set_alembic_version(url, "f7a8b9c0d1e2")

    # Step 3: ensure_schema_at_head should auto-stamp head and recover.
    result = ensure_schema_at_head(url, Base.metadata)
    assert result == "stamped_recovery"

    # alembic_version is now at head.
    final_rev = _read_alembic_version(url)
    assert final_rev is not None
    assert final_rev != "f7a8b9c0d1e2"  # advanced


# ---------------------------------------------------------------------------
# In-process migrations must not silence application logging
# ---------------------------------------------------------------------------
def test_startup_migration_does_not_disable_app_loggers(temp_db):
    """`alembic/env.py` calls `fileConfig`, whose `disable_existing_loggers`
    defaults to True — it sets `.disabled` on every logger not named in
    `alembic.ini`, which is all of `app.*`.

    That only bites when a migration runs IN-PROCESS with the app already
    imported, which is exactly what `app/main.py`'s lifespan does on a fresh
    install. The result was a process whose entire application log went
    silent for its lifetime — including the very next line,
    `logger.info(f"schema_init: {result}")`, so even the message reporting
    the migration was swallowed. A standalone `alembic upgrade` is
    unaffected, which is why it went unnoticed.

    A disabled logger reports `propagate=True` and a sane effective level
    and drops records anyway, so nothing looks wrong from the outside. Found
    via a caplog assertion that passed alone and captured zero records in
    the full suite — see docs/testing.md §3.5.
    """
    import logging

    from app.database import Base
    from app.services.schema_init_service import ensure_schema_at_head

    url, _path = temp_db

    logging.getLogger("app").setLevel(logging.INFO)
    app_logger = logging.getLogger("app")
    child = logging.getLogger("app.tasks.job_tasks")
    assert not app_logger.disabled and not child.disabled, "precondition"

    result = ensure_schema_at_head(url, Base.metadata)
    assert result == "fresh_install", (
        f"expected the migration to actually run (got {result!r}); a no-op "
        "would not exercise env.py and the test would pass vacuously"
    )

    assert not app_logger.disabled, "alembic disabled the 'app' logger"
    assert not child.disabled, "alembic disabled 'app.tasks.job_tasks'"
    assert child.isEnabledFor(logging.WARNING)

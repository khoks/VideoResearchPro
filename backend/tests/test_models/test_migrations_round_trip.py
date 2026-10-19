"""Alembic round trip for the migrations this lane adds.

`alembic upgrade head` on an empty database, then downgrade to just below
the migration under test, then upgrade again. Pins that each revision's
`downgrade()` really undoes its `upgrade()` (a `drop_table` forgotten in
`downgrade` is invisible until an operator rolls back) and that the chain
from `base` stays runnable with the new revision in it.

Each entry names the revision and the tables it owns. Add a row per schema
change rather than a new test file.
"""
import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.services.schema_init_service import _alembic_config

def _has_fts5_trigram() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


LANE_MIGRATIONS = [
    ("c7d8e9f0a1b2", {"scheduled_runs"}),
    ("c2d3e4f5a6b7", {"notes"}),
    ("d8e9f0a1b2c3", {"shelves", "shelf_jobs"}),
    # S-8.2.1: the search index is created only when SQLite has FTS5 with the
    # trigram tokenizer; elsewhere the migration deliberately creates nothing.
    pytest.param(
        "a9f3c1e7b5d2",
        {"fts_documents", "fts_jobs", "fts_channels", "fts_qa", "fts_knowledge"},
        marks=pytest.mark.skipif(not _has_fts5_trigram(), reason="SQLite without FTS5 trigram"),
        id="a9f3c1e7b5d2-search-index",
    ),
]


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision,tables", LANE_MIGRATIONS)
def test_upgrade_downgrade_upgrade_round_trip(tmp_path, revision, tables):
    url = "sqlite:///" + (tmp_path / "round_trip.db").as_posix()
    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    assert tables <= _tables(url), f"{revision} did not create {tables}"

    below = ScriptDirectory.from_config(cfg).get_revision(revision).down_revision
    assert isinstance(below, str), "lane migrations are linear, never merge points"
    command.downgrade(cfg, below)
    assert not (tables & _tables(url)), f"{revision}.downgrade left {tables & _tables(url)}"

    command.upgrade(cfg, "head")
    assert tables <= _tables(url)

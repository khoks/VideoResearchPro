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
    ("e9f0a1b2c3d4", {"tags", "taggings"}),
    ("f0a1b2c3d4e5", {"job_templates", "job_template_versions"}),
    ("b4c5d6e7f8a0", {"channel_intelligence_cache"}),
    ("e5773663cb2d", {"activity_events", "echo_connector_grants", "echo_connector_credentials", "echo_connector_oauth_states"}),
    ("c5ee7a568ef8", {"output_citations"}),
    ("3e03de05cc5f", {"newsletter_subscriptions", "newsletter_sends"}),
    ("007c708bb890", {"shares_inbox"}),
    ("3f8a1c2d9b7e", {"suggestion_cache"}),
    ("5d2e8b1f4a60", {"saved_searches"}),
    ("7c1d9e3a5b42", {"saved_search_runs", "notifications"}),
    ("8e2f4a6c1d93", {"voice_signals"}),
    ("9a1c5e7b3f20", {"voice_signal_inputs"}),
    ("b7e2c4a9d1f6", {"echo_drafts", "echo_voice_gates"}),
    ("5029fce5d1ac", {"echo_card_state"}),
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


def _columns(url: str, table: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {c["name"] for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_onboarding_columns_round_trip(tmp_path):
    """S-8.10.1 adds columns, not tables, so it gets its own check."""
    url = "sqlite:///" + (tmp_path / "round_trip.db").as_posix()
    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)
    cols = {"onboarded_at", "onboarding_state_json"}

    command.upgrade(cfg, "head")
    assert cols <= _columns(url, "users")
    below = ScriptDirectory.from_config(cfg).get_revision("e8667092c208").down_revision
    command.downgrade(cfg, below)
    assert not (cols & _columns(url, "users"))
    command.upgrade(cfg, "head")
    assert cols <= _columns(url, "users")


def test_echo_draft_written_words_round_trip(tmp_path):
    """S-3.4.2 adds a column, not a table, so it gets its own check."""
    url = "sqlite:///" + (tmp_path / "round_trip.db").as_posix()
    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    assert "written_words" in _columns(url, "echo_drafts")
    below = ScriptDirectory.from_config(cfg).get_revision("e5a9c3d7b2f4").down_revision
    command.downgrade(cfg, below)
    assert "written_words" not in _columns(url, "echo_drafts")
    command.upgrade(cfg, "head")
    assert "written_words" in _columns(url, "echo_drafts")


def test_oauth_identity_email_verified_at_round_trip(tmp_path):
    """T-5.4.10 adds a column, not a table, so it gets its own check."""
    url = "sqlite:///" + (tmp_path / "round_trip.db").as_posix()
    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    assert "email_verified_at" in _columns(url, "oauth_identities")
    below = ScriptDirectory.from_config(cfg).get_revision("066d3f4b4d4d").down_revision
    command.downgrade(cfg, below)
    assert "email_verified_at" not in _columns(url, "oauth_identities")
    command.upgrade(cfg, "head")
    assert "email_verified_at" in _columns(url, "oauth_identities")


def test_library_qa_scope_column_round_trip(tmp_path):
    """S-8.1.4 adds a column, not a table, so it gets its own check."""
    url = "sqlite:///" + (tmp_path / "round_trip.db").as_posix()
    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    assert "scope_json" in _columns(url, "library_qa_exchanges")
    below = ScriptDirectory.from_config(cfg).get_revision("cd4c5467506d").down_revision
    command.downgrade(cfg, below)
    assert "scope_json" not in _columns(url, "library_qa_exchanges")
    command.upgrade(cfg, "head")
    assert "scope_json" in _columns(url, "library_qa_exchanges")

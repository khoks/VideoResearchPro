"""``007c708bb890`` (S-3.7.1) against the real migration chain: existing
``personal_context`` rows gain ``tenant_id = user_id`` and the column becomes
NOT NULL; ``shares_inbox`` appears; downgrade removes both cleanly.
"""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS = "72d7e46ef057"
THIS = "007c708bb890"

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'echo_shares.db'}"
    cfg = Config(os.path.join(_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    eng = create_engine(url)
    try:
        yield cfg, eng
    finally:
        eng.dispose()


def _exec(eng, sql, **params):
    with eng.begin() as conn:
        result = conn.execute(text(sql), params)
        return result.fetchall() if result.returns_rows else None


def test_backfill_sets_tenant_from_user_and_enforces_not_null(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, PREVIOUS)
    assert "tenant_id" not in {c["name"] for c in inspect(eng).get_columns("personal_context")}
    for rid, uid in (("pc-1", "user-a"), ("pc-2", "user-b")):
        _exec(
            eng,
            "INSERT INTO personal_context (id, user_id, kind, key, value, source, confidence, captured_at) "
            "VALUES (:id, :u, 'interest', :id, 'v', 'manual', 1.0, CURRENT_TIMESTAMP)",
            id=rid, u=uid,
        )

    command.upgrade(cfg, THIS)
    inspector = inspect(eng)
    assert "shares_inbox" in inspector.get_table_names()
    cols = {c["name"]: c for c in inspector.get_columns("personal_context")}
    assert cols["tenant_id"]["nullable"] is False
    assert sorted(_exec(eng, "SELECT id, tenant_id FROM personal_context ORDER BY id")) == [
        ("pc-1", "user-a"),
        ("pc-2", "user-b"),
    ]
    with pytest.raises(IntegrityError):
        _exec(
            eng,
            "INSERT INTO personal_context (id, user_id, kind, key, value, source, confidence, captured_at) "
            "VALUES ('pc-3', 'user-c', 'interest', 'k', 'v', 'manual', 1.0, CURRENT_TIMESTAMP)",
        )

    command.downgrade(cfg, PREVIOUS)
    inspector = inspect(eng)
    assert "shares_inbox" not in inspector.get_table_names()
    assert "tenant_id" not in {c["name"] for c in inspector.get_columns("personal_context")}
    assert len(_exec(eng, "SELECT id FROM personal_context")) == 2, "downgrade keeps the facts"


def test_processing_column_round_trips(migrated):
    """65ce471f8571 (S-3.7.2) adds shares_inbox.processing_json and removes it."""
    cfg, eng = migrated
    command.upgrade(cfg, "65ce471f8571")
    assert "processing_json" in {c["name"] for c in inspect(eng).get_columns("shares_inbox")}
    command.downgrade(cfg, "1a6e09517250")
    assert "processing_json" not in {c["name"] for c in inspect(eng).get_columns("shares_inbox")}
    command.upgrade(cfg, "head")
    assert "processing_json" in {c["name"] for c in inspect(eng).get_columns("shares_inbox")}


def test_imports_table_and_share_columns_round_trip(migrated):
    """509a4efd9319 (S-3.7.5) adds echo_imports and shares_inbox.import_id /
    occurred_at, and removes them; existing shares keep their rows."""
    cfg, eng = migrated
    command.upgrade(cfg, "9a1c5e7b3f20")
    _exec(
        eng,
        "INSERT INTO shares_inbox (id, tenant_id, user_id, received_at, updated_at, surface, content_type, "
        "raw_payload_json, author_is_tenant, processing_state) VALUES ('s-1', 't', 't', CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, 'manual_quick_share', 'text_snippet', '{\"kind\":\"text\"}', 0, 'pending')",
    )
    command.upgrade(cfg, "509a4efd9319")
    inspector = inspect(eng)
    assert "echo_imports" in inspector.get_table_names()
    assert {"import_id", "occurred_at"} <= {c["name"] for c in inspector.get_columns("shares_inbox")}
    assert _exec(eng, "SELECT id, import_id, occurred_at FROM shares_inbox") == [("s-1", None, None)]
    command.downgrade(cfg, "9a1c5e7b3f20")
    inspector = inspect(eng)
    assert "echo_imports" not in inspector.get_table_names()
    assert "import_id" not in {c["name"] for c in inspector.get_columns("shares_inbox")}
    assert _exec(eng, "SELECT id FROM shares_inbox") == [("s-1",)]
    command.upgrade(cfg, "head")


def test_share_tokens_table_round_trips(migrated):
    """d3bc5b91fcce (S-3.7.3) adds echo_share_tokens with a unique hash, and
    removes it."""
    cfg, eng = migrated
    command.upgrade(cfg, "d3bc5b91fcce")
    assert "echo_share_tokens" in inspect(eng).get_table_names()
    row = "INSERT INTO echo_share_tokens (id, tenant_id, label, token_hash, prefix, created_at) VALUES (:id, 't', 'x', 'h', 'pec_', CURRENT_TIMESTAMP)"
    _exec(eng, row, id="t-1")
    with pytest.raises(IntegrityError):
        _exec(eng, row, id="t-2")
    command.downgrade(cfg, "509a4efd9319")
    assert "echo_share_tokens" not in inspect(eng).get_table_names()
    command.upgrade(cfg, "head")


def test_card_state_table_round_trips(migrated):
    """5029fce5d1ac (S-3.8.2) adds echo_card_state, one row per tenant and
    card key, and removes it."""
    cfg, eng = migrated
    command.upgrade(cfg, "5029fce5d1ac")
    assert "echo_card_state" in inspect(eng).get_table_names()
    row = (
        "INSERT INTO echo_card_state (id, tenant_id, key, kind, created_at, updated_at) "
        "VALUES (:id, 't', 'questions:library', 'questions', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    _exec(eng, row, id="c-1")
    assert _exec(eng, "SELECT shown_days FROM echo_card_state") == [(0,)]
    with pytest.raises(IntegrityError):
        _exec(eng, row, id="c-2")
    command.downgrade(cfg, "b7e2c4a9d1f6")
    assert "echo_card_state" not in inspect(eng).get_table_names()
    command.upgrade(cfg, "head")

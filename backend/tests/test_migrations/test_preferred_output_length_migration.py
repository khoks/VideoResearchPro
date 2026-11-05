"""``869754146393`` (T-1.15.3.9) against the real migration chain: the column is
nullable with no default, so every existing account reads as Auto, and a
downgrade removes it."""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS = "c62da1d081c6"
THIS = "869754146393"

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'preferred_output_length.db'}"
    cfg = Config(os.path.join(_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    eng = create_engine(url)
    try:
        yield cfg, eng
    finally:
        eng.dispose()


def _columns(eng) -> dict:
    return {c["name"]: c for c in inspect(eng).get_columns("users")}


def test_an_existing_account_reads_as_auto_and_a_downgrade_removes_the_column(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, PREVIOUS)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, created_at) "
                "VALUES ('u1', 'u1@x.com', 'x', '2026-10-01 10:00:00.000000')"
            )
        )
    assert "preferred_output_length" not in _columns(eng)

    command.upgrade(cfg, THIS)
    column = _columns(eng)["preferred_output_length"]
    assert column["nullable"] is True
    assert column["default"] is None
    with eng.begin() as conn:
        assert conn.execute(text("SELECT preferred_output_length FROM users")).scalar_one() is None

    command.downgrade(cfg, PREVIOUS)
    assert "preferred_output_length" not in _columns(eng)
    with eng.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1

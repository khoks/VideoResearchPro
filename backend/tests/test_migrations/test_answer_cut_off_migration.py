"""``7bc07679d355`` (T-1.15.4.8) against the real migration chain: each exchange
table gains one nullable boolean with no default, an old row reads as unknown
rather than "not cut", and a downgrade removes the column and keeps the answer."""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS = "869754146393"
THIS = "7bc07679d355"
TABLES = ("qa_exchanges", "library_qa_exchanges", "qa_history_exchanges")

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CREATED = "2026-10-01 10:00:00.000000"


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'answer_cut_off.db'}"
    cfg = Config(os.path.join(_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    eng = create_engine(url)
    try:
        yield cfg, eng
    finally:
        eng.dispose()


def _columns(eng, table: str) -> dict:
    return {c["name"]: c for c in inspect(eng).get_columns(table)}


def _triggers(eng) -> set[str]:
    with eng.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))}


def test_an_old_answer_reads_as_unknown_and_a_downgrade_keeps_the_answer(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, PREVIOUS)
    with eng.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO qa_exchanges (id, job_id, tenant_id, question, answer, "references", created_at) '
                "VALUES ('q1', 'j1', 't1', 'q', 'a', '[]', :created)"
            ),
            {"created": _CREATED},
        )
        for table in TABLES[1:]:
            conn.execute(
                text(
                    f"INSERT INTO {table} (id, tenant_id, question, answer, references_json, answer_language, created_at) "
                    "VALUES ('q1', 't1', 'q', 'a', '[]', 'en', :created)"
                ),
                {"created": _CREATED},
            )
    for table in TABLES:
        assert "answer_cut_off" not in _columns(eng, table)
    search_triggers = _triggers(eng)

    command.upgrade(cfg, THIS)
    assert _triggers(eng) == search_triggers, "adding a column must not rebuild these tables"
    for table in TABLES:
        column = _columns(eng, table)["answer_cut_off"]
        assert column["nullable"] is True
        assert column["default"] is None
        with eng.begin() as conn:
            assert conn.execute(text(f"SELECT answer_cut_off FROM {table}")).scalar_one() is None

    command.downgrade(cfg, PREVIOUS)
    for table in TABLES:
        assert "answer_cut_off" not in _columns(eng, table)
        with eng.begin() as conn:
            assert conn.execute(text(f"SELECT answer FROM {table}")).scalar_one() == "a"

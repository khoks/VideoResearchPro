"""Round trip of ``1a6e09517250`` (S-5.10.3): the global subscription columns
on ``channels`` are dropped, and a downgrade rebuilds them from
``channel_subscriptions`` — any tenant subscribed means subscribed, the latest
sync wins, the weight returns neutral.
"""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS = "5d2e8b1f4a60"  # S-8.3.2 saved searches, merged first
THIS = "1a6e09517250"
LEGACY = {"subscribed", "last_synced_at", "source_weight"}

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 's5103.db'}"
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


def _columns(eng, table):
    return {c["name"] for c in inspect(eng).get_columns(table)}


def _seed(eng):
    for cid, name in (("UCboth", "Both"), ("UConeoff", "One off"), ("UCnobody", "Nobody")):
        _exec(eng, "INSERT INTO channels (channel_id, name, source_type, creator_external_id, created_at,"
                   " subscribed, source_weight) VALUES (:c, :n, 'video', :c, CURRENT_TIMESTAMP, 0, 1.0)",
              c=cid, n=name)
    rows = [
        ("s1", "UCboth", "tenant-a", 1, 2.0, "2026-10-01 10:00:00"),
        ("s2", "UCboth", "tenant-b", 0, 0.5, "2026-10-05 10:00:00"),
        ("s3", "UConeoff", "tenant-a", 0, 1.0, None),
    ]
    for sid, cid, tenant, sub, w, synced in rows:
        _exec(eng, "INSERT INTO channel_subscriptions (id, channel_id, tenant_id, subscribed, source_weight,"
                   " last_synced_at, created_at) VALUES (:i, :c, :t, :s, :w, :l, CURRENT_TIMESTAMP)",
              i=sid, c=cid, t=tenant, s=sub, w=w, l=synced)


def test_upgrade_drops_and_downgrade_restores_from_subscriptions(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, PREVIOUS)
    assert LEGACY <= _columns(eng, "channels")
    _seed(eng)

    command.upgrade(cfg, THIS)
    assert not (LEGACY & _columns(eng, "channels"))
    # Shared facts and per-tenant state both survive the table rebuild.
    assert _exec(eng, "SELECT channel_id, name FROM channels ORDER BY channel_id") == [
        ("UCboth", "Both"), ("UCnobody", "Nobody"), ("UConeoff", "One off")]
    assert _exec(eng, "SELECT COUNT(*) FROM channel_subscriptions") == [(3,)]

    command.downgrade(cfg, PREVIOUS)
    assert LEGACY <= _columns(eng, "channels")
    restored = {r[0]: r[1:] for r in _exec(
        eng, "SELECT channel_id, subscribed, last_synced_at, source_weight FROM channels")}
    assert restored["UCboth"][0] == 1, "any tenant subscribed -> subscribed"
    assert str(restored["UCboth"][1]).startswith("2026-10-05"), "latest sync wins"
    assert restored["UConeoff"][0] == 0 and restored["UConeoff"][1] is None
    assert restored["UCnobody"][0] == 0 and restored["UCnobody"][1] is None
    assert all(r[2] == 1.0 for r in restored.values()), "weights return neutral"

    command.upgrade(cfg, THIS)
    assert not (LEGACY & _columns(eng, "channels"))


def test_orm_matches_the_table_at_head(migrated):
    from app.database import Base
    import app.models  # noqa: F401

    cfg, eng = migrated
    command.upgrade(cfg, "head")
    orm = {c.name for c in Base.metadata.tables["channels"].columns}
    assert _columns(eng, "channels") == orm
    assert not (LEGACY & orm)

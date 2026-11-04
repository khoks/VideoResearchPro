"""``f748717dcb01`` (T-5.4.14 / T-5.4.13) against the real migration chain.

``users.has_password`` is backfilled false only for an account an OAuth
sign-in created (its first identity linked within a minute of the account)
whose holder never completed a password reset; every other account keeps a
password. ``mfa_step_tickets`` appears; downgrade removes both.
"""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS = "a68953e57c63"
THIS = "f748717dcb01"

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'has_password.db'}"
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


def _user(eng, uid, created):
    _exec(
        eng,
        "INSERT INTO users (id, email, password_hash, created_at) VALUES (:id, :e, 'x', :c)",
        id=uid, e=f"{uid}@x.com", c=created,
    )


def _identity(eng, uid, linked, provider_user_id):
    _exec(
        eng,
        "INSERT INTO oauth_identities (id, user_id, provider, provider_user_id, created_at) "
        "VALUES (:id, :u, 'google', :p, :c)",
        id=f"oi-{provider_user_id}", u=uid, p=provider_user_id, c=linked,
    )


def test_backfill_marks_only_accounts_an_oauth_sign_in_made(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, PREVIOUS)
    # Made by a Google sign-in: the identity was linked in the same request.
    _user(eng, "made-by-google", "2026-10-01 10:00:00.000000")
    _identity(eng, "made-by-google", "2026-10-01 10:00:00.041000", "g1")
    # A password account that linked Google a day later.
    _user(eng, "linked-later", "2026-10-01 10:00:00.000000")
    _identity(eng, "linked-later", "2026-10-02 10:00:00.000000", "g2")
    # Made by Google, then given a password through the reset flow.
    _user(eng, "made-then-reset", "2026-10-01 10:00:00.000000")
    _identity(eng, "made-then-reset", "2026-10-01 10:00:00.030000", "g3")
    _exec(
        eng,
        "INSERT INTO audit_log (id, user_id, event, created_at) "
        "VALUES ('a1', 'made-then-reset', 'password_reset_completed', '2026-10-05 09:00:00')",
    )
    # A plain password account.
    _user(eng, "plain", "2026-10-01 10:00:00.000000")
    # Made by GitHub, Google linked later: the first link decides.
    _user(eng, "two-links", "2026-10-01 10:00:00.000000")
    _identity(eng, "two-links", "2026-10-03 10:00:00.000000", "g5")
    _identity(eng, "two-links", "2026-10-01 10:00:00.020000", "gh5")

    command.upgrade(cfg, THIS)

    rows = dict(_exec(eng, "SELECT id, has_password FROM users"))
    assert rows == {
        "made-by-google": 0,
        "linked-later": 1,
        "made-then-reset": 1,
        "plain": 1,
        "two-links": 0,
    }
    assert "mfa_step_tickets" in inspect(eng).get_table_names()


def test_a_new_account_defaults_to_having_a_password(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, THIS)
    _user(eng, "after", "2026-11-04 10:00:00.000000")
    assert _exec(eng, "SELECT has_password FROM users WHERE id = 'after'") == [(1,)]


def test_downgrade_removes_the_column_and_the_table(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, THIS)
    _user(eng, "kept", "2026-11-04 10:00:00.000000")
    command.downgrade(cfg, PREVIOUS)
    inspector = inspect(eng)
    assert "has_password" not in {c["name"] for c in inspector.get_columns("users")}
    assert "mfa_step_tickets" not in inspector.get_table_names()
    assert _exec(eng, "SELECT id FROM users") == [("kept",)], "downgrade keeps the accounts"

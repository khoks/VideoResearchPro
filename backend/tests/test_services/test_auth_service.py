"""T-5.2.8 / D-111 — who operates this install.

Operators are the accounts named in ``ADMIN_EMAILS`` (comma-separated,
case-insensitive); when it is empty, the earliest-registered account is the
operator. The routers that use the rule are tested at the routers
(``test_routers/test_operator_gate.py``).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.config import settings
from app.services import auth_service


def _user(db, email: str, created_at: datetime, user_id: str | None = None):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    # Explicit timestamps: two accounts created in one test can share a clock
    # tick, and the rule must not depend on that.
    user.created_at = created_at
    if user_id is not None:
        user.id = user_id
    db.commit()
    return user


@pytest.fixture
def no_allow_list(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")


def test_without_an_allow_list_the_earliest_account_is_the_operator(db, no_allow_list):
    later = _user(db, "later@example.com", datetime(2026, 5, 2))
    first = _user(db, "first@example.com", datetime(2026, 5, 1))
    assert auth_service.is_operator(db, first)
    assert not auth_service.is_operator(db, later)


def test_accounts_registered_in_the_same_instant_resolve_by_id(db, no_allow_list):
    same = datetime(2026, 5, 1, 9, 0)
    b = _user(db, "b@example.com", same, user_id="00000000-0000-0000-0000-00000000000b")
    a = _user(db, "a@example.com", same, user_id="00000000-0000-0000-0000-00000000000a")
    assert auth_service.is_operator(db, a)
    assert not auth_service.is_operator(db, b), "exactly one operator, never two"


def test_an_allow_list_is_the_whole_rule(db, monkeypatch):
    first = _user(db, "first@example.com", datetime(2026, 5, 1))
    named = _user(db, "boss@example.com", datetime(2026, 5, 3))
    other = _user(db, "other@example.com", datetime(2026, 5, 2))
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@example.com")
    assert auth_service.is_operator(db, named)
    assert not auth_service.is_operator(db, first), "the earliest account is not an operator once a list is set"
    assert not auth_service.is_operator(db, other)


def test_the_allow_list_ignores_case_spaces_and_empty_entries(db, monkeypatch):
    ops = _user(db, "ops@example.com", datetime(2026, 5, 2))
    boss = _user(db, "boss@example.com", datetime(2026, 5, 3))
    _user(db, "first@example.com", datetime(2026, 5, 1))
    monkeypatch.setattr(settings, "ADMIN_EMAILS", " Boss@Example.COM , ,OPS@example.com,")
    assert auth_service.operator_emails() == frozenset({"boss@example.com", "ops@example.com"})
    assert auth_service.is_operator(db, boss) and auth_service.is_operator(db, ops)
    # An address stored with capitals (an OAuth sign-up, an old row) still matches.
    boss.email = "BOSS@example.com"
    db.commit()
    assert auth_service.is_operator(db, boss)


def test_a_list_of_only_separators_counts_as_unset(db, monkeypatch):
    first = _user(db, "first@example.com", datetime(2026, 5, 1))
    monkeypatch.setattr(settings, "ADMIN_EMAILS", " , ")
    assert auth_service.operator_emails() == frozenset()
    assert auth_service.is_operator(db, first)

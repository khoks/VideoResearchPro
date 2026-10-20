"""Anticipation cards (S-3.8.2): the pre-registered frequency cap and
dismissal rule (docs/notes/2026-10-20-anticipation-cards-preregistration.md)
held at the route.

- At most three cards per view, one per kind, in a fixed order.
- A key is shown on at most three distinct days; repeat views on one day
  count once.
- x retires a key. Three dismissals of a kind within 30 days turn the kind
  off, said once; acting retires a key without counting.
- Settings turn kinds off and back on, and turning one back on restarts its
  count.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

import pytest

from app.models.echo_card_state import EchoCardState
from app.models.notification import Notification
from app.models.share import Share
from app.services import auth_service, echo_card_service, notification_service

CARDS = "/api/v1/echo/cards"


def _user(db, email, tier="studio"):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = tier
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two(db):
    a, ha = _user(db, "cards-a@example.com")
    b, hb = _user(db, "cards-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


@pytest.fixture
def clock(monkeypatch):
    """Move the service's clock: `clock.day(n)` is n days after 2026-10-20."""

    class Clock:
        base = datetime(2026, 10, 20, 9, 0)

        def day(self, n: int) -> None:
            now = self.base + timedelta(days=n)
            monkeypatch.setattr(echo_card_service, "_now", lambda: now)
            monkeypatch.setattr(echo_card_service, "_today", lambda: now.date())

    c = Clock()
    c.day(0)
    return c


def _changed(db, tenant_id, title="Your saved search changed"):
    return notification_service.create(
        db, tenant_id, kind=notification_service.KIND_SAVED_SEARCH_CHANGED, title=title, body="New sources.", href="/saved-searches/1",
    )


def _share(db, tenant_id, state="processed", at=datetime(2026, 10, 20, 8, 0), import_id=None):
    s = Share(
        id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=tenant_id, surface="manual_quick_share", content_type="image",
        raw_payload_json=json.dumps({"kind": "text"}), processing_state=state, received_at=at, updated_at=at, import_id=import_id,
    )
    db.add(s)
    db.commit()
    return s


def _get(client, headers, context=None):
    r = client.get(CARDS, headers=headers, params={"context": context} if context else None)
    assert r.status_code == 200, r.text
    return r.json()


def test_cards_need_echo(unauthenticated_client, db):
    _, free = _user(db, "cards-free@example.com", tier="free")
    assert unauthenticated_client.get(CARDS, headers=free).status_code == 403
    assert unauthenticated_client.get(CARDS).status_code == 401


def test_one_card_per_kind_in_order_and_nothing_without_content(unauthenticated_client, db, two, clock):
    assert _get(unauthenticated_client, two["ha"]) == {"cards": [], "muted_kinds": [], "notice": None, "notice_kind": None}
    _changed(db, two["a"].id, "Older change")
    newest = _changed(db, two["a"].id, "Newest change")
    _share(db, two["a"].id)
    _share(db, two["a"].id, state="failed")
    body = _get(unauthenticated_client, two["ha"], context="job:j-1")
    assert [c["kind"] for c in body["cards"]] == ["saved_search", "shares", "questions"]
    saved, shares, questions = body["cards"]
    assert saved["key"] == f"saved_search:{newest.id}" and saved["href"] == "/saved-searches/1"
    assert shares["body"] == "1 share was read and 1 needs a retry since you last looked." and shares["href"] == "/echo/inbox"
    assert questions == {**questions, "key": "questions:job:j-1", "context": "job:j-1"}


def test_a_key_shows_on_at_most_three_days_and_a_day_counts_once(unauthenticated_client, db, two, clock):
    _share(db, two["a"].id)
    key = _get(unauthenticated_client, two["ha"])["cards"][0]["key"]
    for _ in range(3):  # repeat views on one day
        assert [c["key"] for c in _get(unauthenticated_client, two["ha"])["cards"]] == [key]
    row = db.query(EchoCardState).filter_by(tenant_id=two["a"].id, key=key).one()
    assert (row.shown_days, row.last_shown_on) == (1, date(2026, 10, 20))
    clock.day(1)
    _get(unauthenticated_client, two["ha"])
    clock.day(5)
    assert len(_get(unauthenticated_client, two["ha"])["cards"]) == 1, "the third day"
    assert len(_get(unauthenticated_client, two["ha"])["cards"]) == 1, "the third day, again"
    clock.day(6)
    assert _get(unauthenticated_client, two["ha"])["cards"] == [], "a fourth day is over the cap"


def test_a_questions_card_counts_only_when_the_panel_shows_a_question(unauthenticated_client, db, two, clock):
    """An empty suggestions list renders nothing, so a view is counted by
    the panel (POST /shown), not by the read."""
    for n in range(5):
        clock.day(n)
        assert len(_get(unauthenticated_client, two["ha"], "library")["cards"]) == 1
    assert db.query(EchoCardState).filter_by(tenant_id=two["a"].id, key="questions:library").count() == 0
    for n in (5, 6, 7):
        clock.day(n)
        assert len(_get(unauthenticated_client, two["ha"], "library")["cards"]) == 1
        for _ in range(2):  # twice a day still counts once
            assert unauthenticated_client.post(f"{CARDS}/shown", headers=two["ha"], params={"key": "questions:library"}).status_code == 204
    clock.day(8)
    assert _get(unauthenticated_client, two["ha"], "library")["cards"] == [], "three days shown"
    assert len(_get(unauthenticated_client, two["ha"], "job:other")["cards"]) == 1, "another page is another key"


def test_dismiss_retires_a_key_and_three_in_thirty_days_turn_the_kind_off(unauthenticated_client, db, two, clock):
    def dismiss(key):
        r = unauthenticated_client.post(f"{CARDS}/dismiss", headers=two["ha"], params={"key": key})
        assert r.status_code == 200, r.text
        return r.json()["muted_kind"]

    assert dismiss("questions:job:1") is None
    assert _get(unauthenticated_client, two["ha"], "job:1")["cards"] == []
    clock.day(40)  # the first dismissal is now outside the window
    assert dismiss("questions:job:2") is None
    assert dismiss("questions:job:3") is None
    assert dismiss("questions:job:4") == "questions"
    body = _get(unauthenticated_client, two["ha"], "library")
    assert body["cards"] == [] and body["muted_kinds"] == ["questions"]
    assert "so question cards are off" in body["notice"] and body["notice_kind"] == "questions"
    assert _get(unauthenticated_client, two["ha"], "library")["notice"] is None, "said once"
    # Other kinds are untouched.
    _changed(db, two["a"].id)
    assert [c["kind"] for c in _get(unauthenticated_client, two["ha"], "library")["cards"]] == ["saved_search"]


def test_acting_retires_a_card_reads_its_notice_and_never_mutes(unauthenticated_client, db, two, clock):
    notices = [_changed(db, two["a"].id, f"Change {i}") for i in range(4)]
    for n in reversed(notices):
        key = _get(unauthenticated_client, two["ha"])["cards"][0]["key"]
        assert key == f"saved_search:{n.id}"
        assert unauthenticated_client.post(f"{CARDS}/act", headers=two["ha"], params={"key": key}).status_code == 204
        db.expire_all()
        assert db.get(Notification, n.id).read_at is not None
    body = _get(unauthenticated_client, two["ha"])
    assert body == {"cards": [], "muted_kinds": [], "notice": None, "notice_kind": None}


def test_shares_card_counts_direct_shares_since_the_inbox_was_opened(unauthenticated_client, db, two, clock):
    _share(db, two["a"].id, import_id="imp-1")  # an import never counts
    _share(db, two["a"].id, state="pending")  # not read yet
    assert _get(unauthenticated_client, two["ha"])["cards"] == []
    first = _share(db, two["a"].id)
    card = _get(unauthenticated_client, two["ha"])["cards"][0]
    assert card["key"] == f"shares:{first.id}" and card["body"] == "1 share was read since you last looked."
    assert unauthenticated_client.post(f"{CARDS}/seen/shares", headers=two["ha"]).status_code == 204
    assert _get(unauthenticated_client, two["ha"])["cards"] == [], "opening the inbox made them old news"
    later = _share(db, two["a"].id, at=datetime(2026, 10, 20, 10, 0))
    later2 = _share(db, two["a"].id, at=datetime(2026, 10, 20, 11, 0))
    card = _get(unauthenticated_client, two["ha"])["cards"][0]
    assert card["key"] == f"shares:{later2.id}" and card["body"].startswith("2 shares were read"), later.id


def test_settings_turn_kinds_off_and_back_on_and_restart_the_count(unauthenticated_client, db, two, clock):
    r = unauthenticated_client.put(f"{CARDS}/settings", headers=two["ha"], json={"kinds": {"questions": False}})
    assert r.json()["kinds"] == {"saved_search": True, "shares": True, "questions": False}
    body = _get(unauthenticated_client, two["ha"], "library")
    assert body["cards"] == [] and body["muted_kinds"] == ["questions"] and body["notice"] is None, "the user did it: nothing to say"
    for i in range(3):
        unauthenticated_client.post(f"{CARDS}/dismiss", headers=two["ha"], params={"key": f"questions:job:{i}"})
    clock.day(1)
    r = unauthenticated_client.put(f"{CARDS}/settings", headers=two["ha"], json={"kinds": {"questions": True}})
    assert r.json()["kinds"]["questions"] is True
    assert len(_get(unauthenticated_client, two["ha"], "library")["cards"]) == 1
    # The three dismissals before turning it back on no longer count.
    r = unauthenticated_client.post(f"{CARDS}/dismiss", headers=two["ha"], params={"key": "questions:library"})
    assert r.json()["muted_kind"] is None
    assert unauthenticated_client.get(f"{CARDS}/settings", headers=two["ha"]).json()["kinds"]["questions"] is True
    assert unauthenticated_client.put(f"{CARDS}/settings", headers=two["ha"], json={"kinds": {"weather": False}}).status_code == 422


def test_bad_keys_and_contexts_are_refused(unauthenticated_client, two):
    assert unauthenticated_client.get(CARDS, headers=two["ha"], params={"context": "job:../x"}).status_code == 422
    for key in ("mute:questions", "seen:shares", "weather:1", "questions:"):
        assert unauthenticated_client.post(f"{CARDS}/dismiss", headers=two["ha"], params={"key": key}).status_code == 422


def test_cards_and_their_state_belong_to_their_tenant(unauthenticated_client, db, two, clock):
    _changed(db, two["b"].id)
    _share(db, two["b"].id)
    assert _get(unauthenticated_client, two["ha"])["cards"] == []
    for i in range(3):
        unauthenticated_client.post(f"{CARDS}/dismiss", headers=two["ha"], params={"key": f"questions:job:{i}"})
    assert _get(unauthenticated_client, two["hb"], "library")["muted_kinds"] == []
    assert len(_get(unauthenticated_client, two["hb"], "library")["cards"]) == 3
    # Acting on another tenant's notice id reads nothing of theirs.
    other = db.query(Notification).filter_by(tenant_id=two["b"].id).one()
    unauthenticated_client.post(f"{CARDS}/act", headers=two["ha"], params={"key": f"saved_search:{other.id}"})
    db.expire_all()
    assert db.get(Notification, other.id).read_at is None

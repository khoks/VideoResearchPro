"""T-8.3.3.8 — the bell updates live over ``/ws/jobs``.

A new notification is published on ``notifications:{tenant_id}`` (the way
job progress is published on ``job_progress:{id}``); the WebSocket manager
routes it by that CHANNEL to the sockets that sent
``{"action": "subscribe", "topic": "notifications"}``, and a socket only ever
subscribes as the user its token names. The payload is a doorbell (id and
kind), never the notice's text. The one-minute poll stays as the fallback.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services import auth_service, notification_service, progress_service
from app.websocket.manager import ConnectionManager


class _Socket:
    """A socket stand-in that records what the manager sends it."""

    def __init__(self, fail=False):
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("socket gone")
        self.sent.append(message)


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ the manager

def test_a_notification_reaches_only_its_users_sockets():
    m = ConnectionManager()
    a1, a2, b, job_watcher = _Socket(), _Socket(), _Socket(), _Socket()
    m.subscribe_notifications(a1, "user-a")
    m.subscribe_notifications(a2, "user-a")
    m.subscribe_notifications(b, "user-b")
    m.subscribe(job_watcher, "job-1")

    payload = {"type": "notification", "id": "n1", "kind": "saved_search_changed"}
    _run(m.dispatch("notifications:user-a", json.dumps(payload)))

    assert a1.sent == [payload] and a2.sent == [payload], "every tab of the user hears it"
    assert b.sent == [], "another user's bell never does"
    assert job_watcher.sent == []


def test_the_channel_names_the_user_never_the_payload():
    """A payload that names someone else (or a job) is still delivered by its
    channel: nothing a publisher writes in the body can redirect it."""
    m = ConnectionManager()
    a, b, job_watcher = _Socket(), _Socket(), _Socket()
    m.subscribe_notifications(a, "user-a")
    m.subscribe_notifications(b, "user-b")
    m.subscribe(job_watcher, "job-1")

    sneaky = {"type": "notification", "id": "n2", "tenant_id": "user-b", "job_id": "job-1"}
    _run(m.dispatch("notifications:user-a", json.dumps(sneaky)))

    assert a.sent == [sneaky]
    assert b.sent == [] and job_watcher.sent == []


def test_job_progress_still_routes_by_job_and_never_to_a_bell():
    m = ConnectionManager()
    bell, job_watcher = _Socket(), _Socket()
    m.subscribe_notifications(bell, "user-a")
    m.subscribe(job_watcher, "job-1")

    event = {"type": "job_progress", "job_id": "job-1", "progress_pct": 40}
    _run(m.dispatch("job_progress:job-1", json.dumps(event)))

    assert job_watcher.sent == [event]
    assert bell.sent == []


def test_malformed_payloads_are_skipped():
    m = ConnectionManager()
    bell = _Socket()
    m.subscribe_notifications(bell, "user-a")
    for raw in ("not json", "[1, 2]", '"text"'):
        _run(m.dispatch("notifications:user-a", raw))
    _run(m.dispatch("notifications:", json.dumps({"type": "notification"})))
    assert bell.sent == []


def test_unsubscribe_disconnect_and_a_dead_socket_leave_the_bell():
    m = ConnectionManager()
    left, closed, dead, stays = _Socket(), _Socket(), _Socket(fail=True), _Socket()
    for ws in (left, closed, dead, stays):
        m.subscribe_notifications(ws, "user-a")
    m._global_connections.add(closed)

    m.unsubscribe_notifications(left, "user-a")
    _run(m.disconnect(closed))
    _run(m.dispatch("notifications:user-a", json.dumps({"type": "notification", "id": "n1"})))
    _run(m.dispatch("notifications:user-a", json.dumps({"type": "notification", "id": "n2"})))

    assert left.sent == [] and closed.sent == []
    assert [msg["id"] for msg in stays.sent] == ["n1", "n2"]
    assert dead not in m._user_connections.get("user-a", set()), "a socket that failed once is dropped"

    m.unsubscribe_notifications(stays, "user-a")
    assert "user-a" not in m._user_connections
    m.unsubscribe_notifications(stays, "never-subscribed")  # no error


def test_the_listener_subscribes_to_both_patterns():
    """The pub/sub loop asks Redis for notifications as well as job progress
    and hands every message to ``dispatch``."""
    m = ConnectionManager()
    pubsub = MagicMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    async def listen():
        yield {"type": "psubscribe", "channel": "notifications:*", "data": 1}
        yield {"type": "pmessage", "channel": "notifications:user-a", "data": '{"type": "notification", "id": "n1"}'}

    pubsub.listen = listen
    redis = MagicMock()
    redis.pubsub.return_value = pubsub
    redis.aclose = AsyncMock()
    bell = _Socket()
    m.subscribe_notifications(bell, "user-a")
    with patch("app.websocket.manager.aioredis.from_url", return_value=redis):
        _run(m._run_pubsub())

    patterns = pubsub.psubscribe.call_args.args
    assert "job_progress:*" in patterns and "notifications:*" in patterns
    assert bell.sent == [{"type": "notification", "id": "n1"}]


# ------------------------------------------------------------------ the route

@pytest.fixture
def live_manager(monkeypatch):
    """The real manager with the Redis listener stubbed out: the test plays
    the pub/sub side by calling ``dispatch`` on the app's own event loop."""
    m = ConnectionManager()
    monkeypatch.setattr(m, "_redis_listener", AsyncMock())
    monkeypatch.setattr("app.routers.ws.manager", m)
    return m


def _token(user_id):
    token, _ = auth_service.create_access_token(user_id)
    return token


def _sync(ws):
    """Round-trip a ping, so every message sent before it has been handled."""
    ws.send_text("ping")
    return ws.receive_text()


def test_a_socket_hears_its_own_users_notifications_only(unauthenticated_client, db, test_user, live_manager):
    other = auth_service.create_user(db, email="bell-other@example.com", password="otherpass123")
    me = _token(test_user.id)
    them = _token(other.id)
    with (
        unauthenticated_client.websocket_connect(f"/ws/jobs?token={me}") as mine,
        unauthenticated_client.websocket_connect(f"/ws/jobs?token={them}") as theirs,
    ):
        # Naming another user in the message changes nothing: the token decides.
        mine.send_text(json.dumps({"action": "subscribe", "topic": "notifications", "tenant_id": other.id}))
        theirs.send_text(json.dumps({"action": "subscribe", "topic": "notifications"}))
        assert _sync(mine) == "pong" and _sync(theirs) == "pong"
        assert set(live_manager._user_connections) == {test_user.id, other.id}

        doorbell = {"type": "notification", "id": "n-theirs", "kind": "saved_search_changed"}
        mine.portal.call(live_manager.dispatch, f"notifications:{other.id}", json.dumps(doorbell))
        assert theirs.receive_json() == doorbell
        assert _sync(mine) == "pong", "nothing of theirs was queued for me"

        mine_bell = {"type": "notification", "id": "n-mine", "kind": "saved_search_changed"}
        mine.portal.call(live_manager.dispatch, f"notifications:{test_user.id}", json.dumps(mine_bell))
        assert mine.receive_json() == mine_bell
        assert _sync(theirs) == "pong"

        # Unsubscribing stops it.
        mine.send_text(json.dumps({"action": "unsubscribe", "topic": "notifications"}))
        assert _sync(mine) == "pong"
        mine.portal.call(live_manager.dispatch, f"notifications:{test_user.id}", json.dumps(mine_bell))
        assert _sync(mine) == "pong"
    assert live_manager._user_connections == {}, "closing a socket leaves no subscription behind"


def test_a_socket_that_never_asked_hears_nothing(unauthenticated_client, test_user, live_manager):
    with unauthenticated_client.websocket_connect(f"/ws/jobs?token={_token(test_user.id)}") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "topic": "something-else"}))
        ws.send_text("[1, 2]")
        assert _sync(ws) == "pong"
        ws.portal.call(live_manager.dispatch, f"notifications:{test_user.id}", json.dumps({"type": "notification"}))
        assert _sync(ws) == "pong"
    assert live_manager._user_connections == {}


# ------------------------------------------------------------------ the publisher

def test_creating_a_notification_publishes_a_doorbell_on_the_users_channel(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATIONS_PUSH_ENABLED", True)
    redis = MagicMock()
    with patch.object(progress_service, "_get_redis", return_value=redis):
        row = notification_service.create(
            db, test_user.id, kind="saved_search_changed", title="New answer: rates", body="Secret body", href="/x"
        )
    redis.publish.assert_called_once()
    channel, raw = redis.publish.call_args.args
    assert channel == f"notifications:{test_user.id}"
    assert json.loads(raw) == {"type": "notification", "id": row.id, "kind": "saved_search_changed"}
    assert "rates" not in raw and "Secret" not in raw, "the text is read over HTTP, never pushed"


def test_the_push_is_off_when_disabled_and_never_fails_the_producer(db, test_user, monkeypatch):
    redis = MagicMock()
    monkeypatch.setattr(settings, "NOTIFICATIONS_PUSH_ENABLED", False)
    with patch.object(progress_service, "_get_redis", return_value=redis):
        notification_service.create(db, test_user.id, kind="k", title="t")
    redis.publish.assert_not_called()

    monkeypatch.setattr(settings, "NOTIFICATIONS_PUSH_ENABLED", True)
    redis.publish.side_effect = ConnectionError("redis down")
    with patch.object(progress_service, "_get_redis", return_value=redis):
        row = notification_service.create(db, test_user.id, kind="k", title="still stored")
    assert row.id, "a Redis outage leaves the bell to its poll"
    items, unread = notification_service.list_for(db, test_user.id)
    assert unread == 2 and items[0].title == "still stored"

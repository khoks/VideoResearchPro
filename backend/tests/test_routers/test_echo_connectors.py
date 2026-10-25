"""S-3.2.1 — the connector runtime against a fake connector.

Consent before redirect; a single-use, reader-bound OAuth state; tokens stored
encrypted; backfill once, then incremental and idempotent; derived facts
below 1.0; a provider failure recorded, not raised; revoke deletes every row
the connector brought in, in one request; nothing crosses readers.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.connectors import registry
from app.connectors.base import ActivityEvent as EventIn, ConnectorError, ConnectorTokens, DerivedFact
from app.models.activity_event import ActivityEvent
from app.models.echo_connector import EchoConnectorCredential, EchoConnectorGrant, EchoConnectorOAuthState
from app.models.personal_context import PersonalContext
from app.models.scheduled_run import ScheduledRun
from app.services import auth_service, byok_service, echo_connector_service

BASE = "/api/v1/echo/connectors"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


class FakeConnector:
    name = "fake"
    display_name = "Fake service"
    privacy_weight = "low"
    consent_disclosure = "We read your fake activity: what you did and when. Nothing is posted."
    consent_version = "2026-10-19"
    schedule = {"cadence": "daily", "hour": 3}

    def __init__(self):
        self.configured = True
        self.calls: list[tuple] = []
        self.fail: ConnectorError | None = None
        self.revoke_fails = False
        self.backfill_events = [
            EventIn(f"bf-{i}", "did_a_thing", T0 + timedelta(hours=i), {"i": i}, text_content=f"my words {i}")
            for i in range(3)
        ]
        self.incremental_events = [EventIn("bf-2", "did_a_thing", T0, {"i": 2}), EventIn("new-1", "did_a_thing", T0)]

    def event_types(self):
        return ["did_a_thing"]

    def is_configured(self):
        return self.configured

    def authorize_url(self, *, redirect_uri, state, code_challenge):
        self.calls.append(("authorize", redirect_uri))
        return "https://fake.example/authorize?" + urllib.parse.urlencode(
            {"state": state, "redirect_uri": redirect_uri, "code_challenge": code_challenge}
        )

    def handle_callback(self, *, code, redirect_uri, code_verifier):
        self.calls.append(("callback", code, redirect_uri, bool(code_verifier)))
        if code == "bad":
            raise ConnectorError("bad code")
        return ConnectorTokens(access_token=f"tok-{code}", scopes="read", account_label="me-on-fake")

    def revoke(self, tokens):
        self.calls.append(("revoke", tokens.access_token))
        if self.revoke_fails:
            raise RuntimeError("provider down")

    def initial_backfill(self, ctx):
        self.calls.append(("backfill", ctx.tokens.access_token))
        if self.fail:
            raise self.fail
        ctx.cursor["seen"] = "bf-2"
        ctx.facts.append(DerivedFact(kind="skill", key="python", value={"repos": 3}, confidence=0.99))
        yield from self.backfill_events

    def incremental_sync(self, ctx, since):
        self.calls.append(("incremental", since, dict(ctx.cursor)))
        if self.fail:
            raise self.fail
        yield from self.incremental_events


@pytest.fixture
def fake(monkeypatch):
    conn = FakeConnector()
    registry.register_connector(conn)
    monkeypatch.setattr(settings, "ECHO_CONNECTOR_SYNC", "inline")
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.example")
    yield conn
    registry.unregister_connector("fake")


@pytest.fixture
def inline_db(db, monkeypatch):
    """`inline` syncs open their own session; point it at the test session."""
    import app.database as database

    class _Same:
        def __call__(self):
            return db

    monkeypatch.setattr(database, "SessionLocal", _Same())
    monkeypatch.setattr(db, "close", lambda: None)
    return db


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two(db):
    a, ha = _studio(db, "conn-a@example.com")
    b, hb = _studio(db, "conn-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


def _connect(client, headers, code="abc"):
    r = client.post(f"{BASE}/fake/authorize", json={"consent_version": FakeConnector.consent_version}, headers=headers)
    assert r.status_code == 200, r.text
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["authorize_url"]).query)
    return client.post(f"{BASE}/fake/callback", json={"code": code, "state": q["state"][0]}, headers=headers), q


def _item(client, headers):
    return next(i for i in client.get(BASE, headers=headers).json()["items"] if i["name"] == "fake")


# ------------------------------------------------------------------ consent and connect

def test_the_list_carries_what_the_consent_screen_must_show(unauthenticated_client, fake, two):
    item = _item(unauthenticated_client, two["ha"])
    assert item["consent_disclosure"].startswith("We read your fake activity")
    assert item["privacy_weight"] == "low" and item["event_types"] == ["did_a_thing"]
    assert item["connected"] is False and item["grant"] is None and item["configured"] is True


def test_authorize_needs_the_disclosure_the_user_saw(unauthenticated_client, fake, two):
    r = unauthenticated_client.post(f"{BASE}/fake/authorize", json={"consent_version": "old"}, headers=two["ha"])
    assert r.status_code == 409
    assert unauthenticated_client.post(f"{BASE}/nope/authorize", json={"consent_version": "x"}, headers=two["ha"]).status_code == 404
    fake.configured = False
    r = unauthenticated_client.post(f"{BASE}/fake/authorize", json={"consent_version": fake.consent_version}, headers=two["ha"])
    assert r.status_code == 503


def test_connecting_stores_an_encrypted_token_schedules_and_backfills(unauthenticated_client, db, inline_db, fake, two):
    r, q = _connect(unauthenticated_client, two["ha"])
    assert r.status_code == 200, r.text
    assert q["redirect_uri"] == ["https://app.example/echo/connectors/fake/callback"], "built on the server"
    assert q["code_challenge"][0], "PKCE"
    a = two["a"].id

    cred = db.query(EchoConnectorCredential).filter_by(tenant_id=a, connector="fake").one()
    assert "tok-abc" not in cred.access_token_encrypted
    assert byok_service.decrypt_secret(cred.access_token_encrypted) == "tok-abc"
    assert db.query(EchoConnectorOAuthState).filter_by(tenant_id=a).count() == 0, "state is single use"

    grant = r.json()["grant"]
    assert grant["account_label"] == "me-on-fake" and grant["status"] == "idle"
    assert grant["events"] == 3 and grant["last_counts"] == {"added": 3, "updated": 0, "facts": 1}
    run = db.query(ScheduledRun).filter_by(kind="echo_sync").one()
    assert run.tenant_id == a and run.target_id == db.query(EchoConnectorGrant).one().id

    fact = db.query(PersonalContext).filter_by(user_id=a, source="connector:fake").one()
    assert fact.kind == "skill" and fact.confidence == 0.9, "derived facts stay below the user's own"


def test_a_state_is_bound_to_the_reader_who_started(unauthenticated_client, db, inline_db, fake, two):
    r = unauthenticated_client.post(f"{BASE}/fake/authorize", json={"consent_version": fake.consent_version}, headers=two["ha"])
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["authorize_url"]).query)["state"][0]
    stolen = unauthenticated_client.post(f"{BASE}/fake/callback", json={"code": "x", "state": state}, headers=two["hb"])
    assert stolen.status_code == 400
    assert db.query(EchoConnectorGrant).count() == 0
    mine = unauthenticated_client.post(f"{BASE}/fake/callback", json={"code": "x", "state": state}, headers=two["ha"])
    assert mine.status_code == 200, "B's attempt did not burn A's state"
    again = unauthenticated_client.post(f"{BASE}/fake/callback", json={"code": "x", "state": state}, headers=two["ha"])
    assert again.status_code == 400, "single use"


def test_an_expired_state_or_a_refused_code_connects_nothing(unauthenticated_client, db, inline_db, fake, two):
    r = unauthenticated_client.post(f"{BASE}/fake/authorize", json={"consent_version": fake.consent_version}, headers=two["ha"])
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["authorize_url"]).query)["state"][0]
    row = db.get(EchoConnectorOAuthState, state)
    row.expires_at = datetime(2020, 1, 1)
    db.commit()
    assert unauthenticated_client.post(f"{BASE}/fake/callback", json={"code": "x", "state": state}, headers=two["ha"]).status_code == 400
    bad, _ = _connect(unauthenticated_client, two["ha"], code="bad")
    assert bad.status_code == 400 and "Connecting failed" in bad.json()["detail"]
    assert db.query(EchoConnectorGrant).count() == 0 and db.query(EchoConnectorCredential).count() == 0


# ------------------------------------------------------------------ sync

def test_after_the_backfill_syncs_are_incremental_and_idempotent(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.status_code == 200 and r.json()["dispatched"] == "ran"
    inc = [c for c in fake.calls if c[0] == "incremental"]
    assert len(inc) == 1 and inc[0][1] is not None and inc[0][2] == {"seen": "bf-2"}, "since the last sync, cursor kept"
    assert r.json()["connector"]["grant"]["last_counts"] == {"added": 1, "updated": 1, "facts": 0}
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert db.query(ActivityEvent).filter_by(tenant_id=two["a"].id, connector="fake").count() == 4
    assert [c[0] for c in fake.calls].count("backfill") == 1


def test_a_provider_failure_is_recorded_not_raised(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    fake.fail = ConnectorError("token revoked on the provider", auth=True)
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.status_code == 200
    grant = r.json()["connector"]["grant"]
    assert grant["status"] == "error" and grant["last_error"].startswith("Reconnect to sync")
    assert grant["events"] == 3, "what was stored stays"
    fake.fail = None
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.json()["connector"]["grant"]["status"] == "idle" and r.json()["connector"]["grant"]["last_error"] is None


def _foreign_ciphertext(plaintext: str = "tok-abc") -> str:
    """What a token stored under another BYOK_ENCRYPTION_KEY looks like to
    this install: valid Fernet, a key it does not hold."""
    return Fernet(Fernet.generate_key()).encrypt(plaintext.encode()).decode("ascii")


def _break_stored_token(db, tenant_id: str, ciphertext: str) -> None:
    cred = db.query(EchoConnectorCredential).filter_by(tenant_id=tenant_id, connector="fake").one()
    cred.access_token_encrypted = ciphertext
    db.commit()


def test_a_token_this_install_cannot_decrypt_asks_to_reconnect(unauthenticated_client, db, inline_db, fake, two, monkeypatch):
    _connect(unauthenticated_client, two["ha"])
    foreign = _foreign_ciphertext()
    _break_stored_token(db, two["a"].id, foreign)
    log = MagicMock()
    monkeypatch.setattr(echo_connector_service, "logger", log)

    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.status_code == 200, r.text
    grant = r.json()["connector"]["grant"]
    assert grant["status"] == "error"
    assert grant["last_error"].startswith(echo_connector_service.RECONNECT_PREFIX), "the panel shows Reconnect"
    assert grant["events"] == 3, "what was stored stays"
    assert [c[0] for c in fake.calls].count("incremental") == 0, "the provider was never called"

    logged = " ".join(str(a) for call in log.mock_calls for a in call.args)
    assert "could not be decrypted" in logged
    assert foreign not in logged and "tok-abc" not in logged, "neither the ciphertext nor the secret is logged"

    # Reconnecting stores a token this key reads and clears the state.
    r, _ = _connect(unauthenticated_client, two["ha"], code="fresh")
    assert r.json()["grant"]["status"] == "idle" and r.json()["grant"]["last_error"] is None


def test_a_corrupted_token_row_asks_to_reconnect(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    _break_stored_token(db, two["a"].id, "gAAAAé-not-ascii")
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    grant = r.json()["connector"]["grant"]
    assert grant["status"] == "error" and grant["last_error"].startswith("Reconnect to sync")


def test_the_worker_task_records_an_undecryptable_token_instead_of_crashing(db, inline_db, fake, two, monkeypatch):
    """The scheduled path: ``echo.sync_connector`` in Celery, where the
    exception used to escape and leave the grant looking healthy."""
    import app.tasks.echo_connector_tasks as tasks

    a = two["a"].id
    echo_connector_service._store_tokens(db, a, "fake", ConnectorTokens(access_token="tok-abc"))
    grant = EchoConnectorGrant(tenant_id=a, connector="fake", consent_version=FakeConnector.consent_version)
    db.add(grant)
    db.commit()
    _break_stored_token(db, a, _foreign_ciphertext())
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    assert tasks.sync_echo_connector(grant.id) == "auth_error"
    db.refresh(grant)
    assert grant.status == "error" and grant.last_error.startswith("Reconnect to sync")


def test_a_malformed_install_key_is_an_operator_error_not_a_reconnect(unauthenticated_client, db, inline_db, fake, two, monkeypatch):
    _connect(unauthenticated_client, two["ha"])
    try:
        with monkeypatch.context() as m:
            m.setattr(settings, "BYOK_ENCRYPTION_KEY", "not-a-fernet-key")
            byok_service._get_fernet.cache_clear()
            r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    finally:
        byok_service._get_fernet.cache_clear()
    grant = r.json()["connector"]["grant"]
    assert grant["status"] == "error"
    assert not grant["last_error"].startswith("Reconnect"), "a new token could not be stored either"
    assert "encryption key" in grant["last_error"]


def test_sync_needs_a_connection(unauthenticated_client, fake, two):
    assert unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"]).status_code == 404


# ------------------------------------------------------------------ revoke and isolation

def test_revoke_deletes_everything_the_connector_brought_in(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"], code="aaa")
    _connect(unauthenticated_client, two["hb"], code="bbb")
    a, b = two["a"].id, two["b"].id
    fake.revoke_fails = True  # the provider is down: local data goes anyway
    r = unauthenticated_client.delete(f"{BASE}/fake", headers=two["ha"])
    assert r.status_code == 200, r.text
    assert r.json() == {"connector": "fake", "events": 3, "facts": 1, "provider_revoked": False}
    assert ("revoke", "tok-aaa") in fake.calls
    for model in (ActivityEvent, EchoConnectorCredential, EchoConnectorGrant, EchoConnectorOAuthState):
        assert db.query(model).filter_by(tenant_id=a).count() == 0, model.__tablename__
    assert db.query(PersonalContext).filter_by(user_id=a, source="connector:fake").count() == 0
    assert db.query(ScheduledRun).filter_by(tenant_id=a).count() == 0
    # B keeps everything.
    assert db.query(ActivityEvent).filter_by(tenant_id=b).count() == 3
    assert db.query(EchoConnectorGrant).filter_by(tenant_id=b).count() == 1
    assert db.query(ScheduledRun).filter_by(tenant_id=b).count() == 1


def test_the_timeline_is_mine_and_newest_first(unauthenticated_client, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    r = unauthenticated_client.get("/api/v1/echo/activity", params={"limit": 2}, headers=two["ha"])
    items = r.json()["items"]
    assert [i["payload"]["i"] for i in items] == [2, 1] and items[0]["text_content"] == "my words 2"
    nxt = unauthenticated_client.get("/api/v1/echo/activity", params={"before": r.json()["next_before"]}, headers=two["ha"])
    assert [i["payload"]["i"] for i in nxt.json()["items"]] == [0]
    assert unauthenticated_client.get("/api/v1/echo/activity", headers=two["hb"]).json()["items"] == []


def test_the_full_delete_revokes_at_the_provider_and_drops_the_schedule(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"], code="zzz")
    r = unauthenticated_client.delete("/api/v1/echo/brain", params={"confirm": "delete-everything"}, headers=two["ha"])
    assert r.status_code == 200, r.text
    assert ("revoke", "tok-zzz") in fake.calls
    assert db.query(ScheduledRun).filter_by(kind="echo_sync").count() == 0
    assert db.query(EchoConnectorCredential).count() == 0


def test_connectors_are_gated_like_the_rest_of_echo(unauthenticated_client, db, fake):
    user = auth_service.create_user(db, email="conn-free@example.com", password="pw" * 6)
    token, _ = auth_service.create_access_token(user.id)
    assert unauthenticated_client.get(BASE, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_the_sync_kind_is_registered_for_the_scheduler():
    import app.tasks.echo_connector_tasks  # noqa: F401  (what celery_app autodiscovers)
    from app.services import scheduler_service

    assert "echo_sync" in scheduler_service.registered_kinds()

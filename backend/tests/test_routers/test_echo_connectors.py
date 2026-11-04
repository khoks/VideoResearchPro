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


# ------------------------------------------------------------------ T-3.2.2.5: token refresh

PAST = datetime(2020, 1, 1)


class RefreshingConnector(FakeConnector):
    """A provider whose access tokens expire (Google's last an hour)."""

    name = "fake"

    def __init__(self):
        super().__init__()
        self.refresh_error: Exception | None = None
        self.rotate = False
        self.minted = 0

    def handle_callback(self, *, code, redirect_uri, code_verifier):
        self.calls.append(("callback", code, redirect_uri, bool(code_verifier)))
        return ConnectorTokens(
            access_token=f"tok-{code}", refresh_token=f"refresh-{code}",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1), scopes="read", account_label="me-on-fake",
        )

    def refresh_tokens(self, tokens):
        self.calls.append(("refresh", tokens.refresh_token))
        if self.refresh_error:
            raise self.refresh_error
        self.minted += 1
        return ConnectorTokens(
            access_token=f"fresh-{self.minted}",
            refresh_token=f"refresh-rotated-{self.minted}" if self.rotate else None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def incremental_sync(self, ctx, since):
        self.calls.append(("incremental-token", ctx.tokens.access_token))
        yield from super().incremental_sync(ctx, since)


@pytest.fixture
def refreshing(monkeypatch):
    conn = RefreshingConnector()
    registry.register_connector(conn)
    monkeypatch.setattr(settings, "ECHO_CONNECTOR_SYNC", "inline")
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.example")
    yield conn
    registry.unregister_connector("fake")


def _cred(db, tenant_id):
    db.expire_all()
    return db.query(EchoConnectorCredential).filter_by(tenant_id=tenant_id, connector="fake").one()


def _expire(db, tenant_id, when=PAST):
    cred = _cred(db, tenant_id)
    cred.expires_at = when
    db.commit()


def test_an_expired_token_is_renewed_before_the_sync_and_stored_encrypted(
    unauthenticated_client, db, inline_db, refreshing, two, monkeypatch
):
    _connect(unauthenticated_client, two["ha"], code="abc")
    a = two["a"].id
    _expire(db, a)
    log = MagicMock()
    monkeypatch.setattr(echo_connector_service, "logger", log)

    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.status_code == 200, r.text
    assert r.json()["connector"]["grant"]["status"] == "idle"
    assert ("refresh", "refresh-abc") in refreshing.calls
    # Mutation-style: the provider saw the renewed token, not the expired one.
    assert ("incremental-token", "fresh-1") in refreshing.calls
    assert ("incremental-token", "tok-abc") not in refreshing.calls

    cred = _cred(db, a)
    assert "fresh-1" not in cred.access_token_encrypted, "stored encrypted"
    assert byok_service.decrypt_secret(cred.access_token_encrypted) == "fresh-1"
    assert byok_service.decrypt_secret(cred.refresh_token_encrypted) == "refresh-abc", "an unrotated refresh token is kept"
    assert cred.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)

    logged = " ".join(str(x) for call in log.mock_calls for x in call.args)
    assert "renewed" in logged
    assert not any(t in logged for t in ("fresh-1", "refresh-abc", "tok-abc")), "no token is logged"

    # Not expired any more: the next sync does not refresh again.
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert [c[0] for c in refreshing.calls].count("refresh") == 1


def test_a_rotated_refresh_token_replaces_the_stored_one(unauthenticated_client, db, inline_db, refreshing, two):
    _connect(unauthenticated_client, two["ha"], code="abc")
    refreshing.rotate = True
    _expire(db, two["a"].id)
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert byok_service.decrypt_secret(_cred(db, two["a"].id).refresh_token_encrypted) == "refresh-rotated-1"


def test_a_token_that_has_not_expired_or_never_expires_is_not_renewed(unauthenticated_client, db, inline_db, refreshing, two):
    _connect(unauthenticated_client, two["ha"], code="abc")
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    _expire(db, two["a"].id, when=None)  # GitHub's tokens carry no expiry
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert "refresh" not in [c[0] for c in refreshing.calls]
    assert [c[1] for c in refreshing.calls if c[0] == "incremental-token"] == ["tok-abc", "tok-abc"]


def test_a_token_about_to_expire_is_renewed_early():
    soon = ConnectorTokens(access_token="x", expires_at=datetime.now(timezone.utc) + timedelta(seconds=30))
    later = ConnectorTokens(access_token="x", expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    assert echo_connector_service.needs_refresh(soon)
    assert not echo_connector_service.needs_refresh(later)
    assert not echo_connector_service.needs_refresh(ConnectorTokens(access_token="x"))


def test_a_refused_refresh_asks_to_reconnect_and_never_calls_the_provider(
    unauthenticated_client, db, inline_db, refreshing, two
):
    _connect(unauthenticated_client, two["ha"], code="abc")
    a = two["a"].id
    _expire(db, a)
    refreshing.refresh_error = ConnectorError("invalid_grant", auth=True)

    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.status_code == 200, r.text
    grant = r.json()["connector"]["grant"]
    assert grant["status"] == "error"
    assert grant["last_error"].startswith(echo_connector_service.RECONNECT_PREFIX), "the panel shows Reconnect"
    assert grant["events"] == 3, "what was stored stays"
    assert "incremental-token" not in [c[0] for c in refreshing.calls], "the provider was never called"
    assert byok_service.decrypt_secret(_cred(db, a).access_token_encrypted) == "tok-abc", "nothing overwritten"

    # Reconnecting stores fresh tokens and clears the state.
    refreshing.refresh_error = None
    r, _ = _connect(unauthenticated_client, two["ha"], code="again")
    assert r.json()["grant"]["status"] == "idle" and r.json()["grant"]["last_error"] is None


def test_an_expired_token_with_no_way_to_renew_it_asks_to_reconnect(unauthenticated_client, db, inline_db, fake, two):
    """No refresh token stored, or a connector without ``refresh_tokens``."""
    _connect(unauthenticated_client, two["ha"])
    a = two["a"].id
    _expire(db, a)
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    grant = r.json()["connector"]["grant"]
    assert grant["status"] == "error" and grant["last_error"].startswith(echo_connector_service.RECONNECT_PREFIX)
    assert "no refresh token" in grant["last_error"]
    assert [c[0] for c in fake.calls].count("incremental") == 0

    cred = _cred(db, a)
    cred.refresh_token_encrypted = byok_service.encrypt_secret("refresh-x")
    db.commit()
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    grant = r.json()["connector"]["grant"]
    assert grant["last_error"].startswith(echo_connector_service.RECONNECT_PREFIX)
    assert "cannot renew" in grant["last_error"]


def test_a_transient_refresh_failure_is_retried_not_a_reconnect(unauthenticated_client, db, inline_db, refreshing, two):
    _connect(unauthenticated_client, two["ha"], code="abc")
    _expire(db, two["a"].id)
    refreshing.refresh_error = ConnectorError("token endpoint returned 503")
    grant = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"]).json()["connector"]["grant"]
    assert grant["status"] == "error"
    assert not grant["last_error"].startswith("Reconnect"), "the refresh token may still be good"
    assert "next sync tries again" in grant["last_error"]

    refreshing.refresh_error = RuntimeError("connection reset")
    grant = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"]).json()["connector"]["grant"]
    assert grant["status"] == "error" and "RuntimeError" in grant["last_error"]

    refreshing.refresh_error = None
    grant = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"]).json()["connector"]["grant"]
    assert grant["status"] == "idle" and grant["last_error"] is None


def test_the_worker_task_renews_or_records_a_refused_refresh(db, inline_db, refreshing, two, monkeypatch):
    """The scheduled path: ``echo.sync_connector`` in Celery never raises."""
    import app.tasks.echo_connector_tasks as tasks

    a = two["a"].id
    echo_connector_service._store_tokens(
        db, a, "fake", ConnectorTokens(access_token="tok-old", refresh_token="refresh-old", expires_at=PAST)
    )
    grant = EchoConnectorGrant(tenant_id=a, connector="fake", consent_version=FakeConnector.consent_version)
    db.add(grant)
    db.commit()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    refreshing.refresh_error = ConnectorError("invalid_grant", auth=True)
    assert tasks.sync_echo_connector(grant.id) == "auth_error"
    db.refresh(grant)
    assert grant.status == "error" and grant.last_error.startswith("Reconnect to sync")

    refreshing.refresh_error = None
    assert tasks.sync_echo_connector(grant.id) == "ok"
    assert byok_service.decrypt_secret(_cred(db, a).access_token_encrypted) == "fresh-1"
    assert ("backfill", "fresh-1") in refreshing.calls, "the backfill used the renewed token"


# ------------------------------------------------------------------ T-3.2.4.4: deleted derived facts stay deleted

TOMBSTONES = "/api/v1/echo/fact-tombstones"


def _facts_every_sync(fake):
    """Make every incremental sync re-derive the backfill's fact, like
    GitHub's nightly language facts."""
    original = fake.incremental_sync

    def incremental(ctx, since):
        ctx.facts.append(DerivedFact(kind="skill", key="python", value={"repos": 4}, confidence=0.8))
        yield from original(ctx, since)

    fake.incremental_sync = incremental


def _python(db, tenant_id):
    db.expire_all()
    return db.query(PersonalContext).filter_by(user_id=tenant_id, kind="skill", key="python").first()


def test_a_deleted_derived_fact_stays_deleted_until_the_user_clears_it(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    _facts_every_sync(fake)
    a = two["a"].id
    assert _python(db, a) is not None

    r = unauthenticated_client.delete("/api/v1/echo/context/skill/python", headers=two["ha"])
    assert r.status_code == 200, r.text
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.json()["connector"]["grant"]["last_counts"]["facts"] == 0
    assert _python(db, a) is None, "the nightly sync did not bring it back"

    listed = unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"]
    assert [(t["connector"], t["connector_display_name"], t["kind"], t["key"]) for t in listed] == [
        ("fake", "Fake service", "skill", "python")
    ]
    assert listed[0]["created_at"].endswith(("Z", "+00:00"))

    # Mutation-style: clearing the tombstone is all it takes for the same
    # sync to write the fact again, so the skip above was the tombstone's.
    assert unauthenticated_client.delete(f"{TOMBSTONES}/{listed[0]['id']}", headers=two["ha"]).json() == {"cleared": True}
    assert _python(db, a) is None, "clearing re-creates nothing by itself"
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert r.json()["connector"]["grant"]["last_counts"]["facts"] == 1
    assert _python(db, a).source == "connector:fake"
    assert unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"] == []


# ------------------------------------------------------------------ T-3.2.1.11: a fact the user edited stays theirs

MINE = "Only for scripts; I would not call it a skill."


def _edit_python(client, headers):
    r = client.post(
        "/api/v1/echo/context", json={"kind": "skill", "key": "python", "value": MINE}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_fact_the_user_edited_survives_the_next_sync(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    _facts_every_sync(fake)
    a = two["a"].id
    assert _edit_python(unauthenticated_client, two["ha"])["source"] == "manual"

    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])

    grant = r.json()["connector"]["grant"]
    assert grant["last_counts"]["facts"] == 0
    assert grant["last_counts"]["facts_kept_manual"] == 1, "the run summary says so"
    fact = _python(db, a)
    assert (fact.value, fact.source, fact.confidence) == (MINE, "manual", 1.0)


def test_the_scheduled_sync_keeps_an_edited_fact_too(db, inline_db, unauthenticated_client, fake, two, monkeypatch):
    import app.tasks.echo_connector_tasks as tasks

    _connect(unauthenticated_client, two["ha"])
    _facts_every_sync(fake)
    _edit_python(unauthenticated_client, two["ha"])
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    grant = db.query(EchoConnectorGrant).filter_by(tenant_id=two["a"].id).one()

    assert tasks.sync_echo_connector(grant.id) == "ok"
    assert _python(db, two["a"].id).value == MINE


def test_a_fact_nobody_edited_still_follows_the_connector(unauthenticated_client, db, inline_db, fake, two):
    """The skip is for the user's rows, not for every row that exists."""
    _connect(unauthenticated_client, two["ha"])
    _facts_every_sync(fake)
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    counts = r.json()["connector"]["grant"]["last_counts"]
    assert counts["facts"] == 1 and "facts_kept_manual" not in counts
    fact = _python(db, two["a"].id)
    assert fact.value == '{"repos": 4}' and fact.source == "connector:fake" and fact.confidence == 0.8


def test_a_fact_the_user_typed_first_is_not_taken_over(unauthenticated_client, db, inline_db, fake, two):
    _edit_python(unauthenticated_client, two["ha"])
    r, _ = _connect(unauthenticated_client, two["ha"])
    assert r.json()["grant"]["last_counts"] == {"added": 3, "updated": 0, "facts": 0, "facts_kept_manual": 1}
    assert _python(db, two["a"].id).value == MINE


def test_an_edit_made_during_a_sync_is_not_written_over(unauthenticated_client, db, inline_db, fake, two):
    """A sync can run for minutes, so the check is per fact at write time."""
    _connect(unauthenticated_client, two["ha"])
    original = fake.incremental_sync

    def edited_while_fetching(ctx, since):
        ctx.facts.append(DerivedFact(kind="skill", key="python", value={"repos": 4}, confidence=0.8))
        yield from original(ctx, since)
        _edit_python(unauthenticated_client, two["ha"])

    fake.incremental_sync = edited_while_fetching
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert _python(db, two["a"].id).value == MINE


def test_an_edited_fact_the_user_then_deletes_stays_deleted(unauthenticated_client, db, inline_db, fake, two):
    """Editing makes the row manual, and a manual row gets no tombstone by
    itself: without ``edited_from`` the next sync would bring it back."""
    _connect(unauthenticated_client, two["ha"])
    _facts_every_sync(fake)
    a = two["a"].id
    _edit_python(unauthenticated_client, two["ha"])
    _edit_python(unauthenticated_client, two["ha"])  # a second edit keeps the origin
    assert _python(db, a).edited_from == "connector:fake"

    assert unauthenticated_client.delete("/api/v1/echo/context/skill/python", headers=two["ha"]).status_code == 200
    r = unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])

    assert _python(db, a) is None, "the deleted fact stayed deleted"
    assert "facts_kept_manual" not in r.json()["connector"]["grant"]["last_counts"]
    listed = unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"]
    assert [(t["connector"], t["key"]) for t in listed] == [("fake", "python")]


def test_an_edited_fact_is_the_users_when_the_connector_goes(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"])
    _edit_python(unauthenticated_client, two["ha"])
    assert unauthenticated_client.delete(f"{BASE}/fake", headers=two["ha"]).json()["facts"] == 0
    assert _python(db, two["a"].id).value == MINE


def test_one_readers_edit_does_not_stop_anothers_sync(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"], code="aaa")
    _connect(unauthenticated_client, two["hb"], code="bbb")
    _facts_every_sync(fake)
    _edit_python(unauthenticated_client, two["ha"])
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["hb"])
    assert _python(db, two["b"].id).source == "connector:fake"


def test_tombstones_are_the_callers_own(unauthenticated_client, db, inline_db, fake, two):
    _connect(unauthenticated_client, two["ha"], code="aaa")
    _connect(unauthenticated_client, two["hb"], code="bbb")
    _facts_every_sync(fake)
    unauthenticated_client.delete("/api/v1/echo/context/skill/python", headers=two["ha"])
    tid = unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"][0]["id"]

    assert unauthenticated_client.get(TOMBSTONES, headers=two["hb"]).json()["items"] == []
    assert unauthenticated_client.delete(f"{TOMBSTONES}/{tid}", headers=two["hb"]).status_code == 404
    assert len(unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"]) == 1
    # A's tombstone does not stop B's sync.
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["hb"])
    assert _python(db, two["b"].id) is not None


def test_only_derived_facts_are_tombstoned(unauthenticated_client, db, inline_db, fake, two):
    unauthenticated_client.post(
        "/api/v1/echo/context", json={"kind": "hobby", "key": "chess", "value": "weekends"}, headers=two["ha"]
    )
    assert unauthenticated_client.delete("/api/v1/echo/context/hobby/chess", headers=two["ha"]).status_code == 200
    assert unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"] == []


def test_deleting_a_whole_source_keeps_every_fact_deleted(unauthenticated_client, db, inline_db, fake, two):
    """``DELETE /echo/sources/connector:fake`` deletes facts but leaves the
    connection, so its next sync must not bring them back."""
    _connect(unauthenticated_client, two["ha"])
    _facts_every_sync(fake)
    r = unauthenticated_client.delete("/api/v1/echo/sources/connector:fake", headers=two["ha"])
    assert r.json()["deleted_count"] == 1
    unauthenticated_client.post(f"{BASE}/fake/sync", headers=two["ha"])
    assert _python(db, two["a"].id) is None
    assert [t["key"] for t in unauthenticated_client.get(TOMBSTONES, headers=two["ha"]).json()["items"]] == ["python"]


def test_disconnecting_records_no_tombstone_and_keeps_the_users(unauthenticated_client, db, inline_db, fake, two):
    from app.models.echo_fact_tombstone import EchoFactTombstone

    _connect(unauthenticated_client, two["ha"])
    echo_connector_service.echo_fact_tombstones.record(db, two["a"].id, "fake", "skill", "rust")
    db.commit()
    unauthenticated_client.delete(f"{BASE}/fake", headers=two["ha"])
    assert [t.key for t in db.query(EchoFactTombstone).filter_by(tenant_id=two["a"].id)] == ["rust"]


def test_the_full_delete_erases_tombstones(unauthenticated_client, db, inline_db, fake, two):
    from app.models.echo_fact_tombstone import EchoFactTombstone

    _connect(unauthenticated_client, two["ha"], code="aaa")
    _connect(unauthenticated_client, two["hb"], code="bbb")
    for headers in (two["ha"], two["hb"]):
        unauthenticated_client.delete("/api/v1/echo/context/skill/python", headers=headers)
    r = unauthenticated_client.delete("/api/v1/echo/brain", params={"confirm": "delete-everything"}, headers=two["ha"])
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["rows"]["echo_fact_tombstones"] == 1
    assert db.query(EchoFactTombstone).filter_by(tenant_id=two["a"].id).count() == 0
    assert db.query(EchoFactTombstone).filter_by(tenant_id=two["b"].id).count() == 1, "B keeps theirs"


def test_tombstones_are_gated_like_the_rest_of_echo(unauthenticated_client, db):
    user = auth_service.create_user(db, email="tomb-free@example.com", password="pw" * 6)
    token, _ = auth_service.create_access_token(user.id)
    h = {"Authorization": f"Bearer {token}"}
    assert unauthenticated_client.get(TOMBSTONES, headers=h).status_code == 403
    assert unauthenticated_client.delete(f"{TOMBSTONES}/x", headers=h).status_code == 403

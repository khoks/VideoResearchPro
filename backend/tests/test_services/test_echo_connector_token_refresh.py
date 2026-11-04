"""T-3.2.1.12 — token refresh at the edges, against a provider that rotates.

Each refresh token works once. Reusing a spent one is ``invalid_grant``, as on
a real rotating provider, and a spurious ``invalid_grant`` was what a scheduled
sync racing "Sync now" could have earned. Everything runs through
``run_sync``, the worker task or ``enqueue_sync``: the production callers.

* A 401 in the middle of a sync renews once and retries that call once, not
  the calls before it.
* Only what a sync cannot get past asks for a reconnect.
* Two readers spend one refresh token once, the second using the first's
  result, including with real threads and two database connections.
* No token reaches a log line or ``last_error``.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.config import settings
from app.connectors import registry
from app.connectors.base import (
    ActivityEvent as EventIn,
    ConnectorError,
    ConnectorTokens,
    SyncContext,
    TokenRenewalFailed,
)
from app.connectors.github.connector import GitHubConnector, HttpResponse
from app.database import Base
from app.models.activity_event import ActivityEvent
from app.models.echo_connector import EchoConnectorCredential, EchoConnectorGrant
from app.services import byok_service, echo_connector_service as svc

NAME = "rotating"
TENANT = "11111111-1111-1111-1111-111111111111"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
PAST = datetime(2020, 1, 1)


class RotatingProvider:
    """Each refresh token works once; each refresh issues a new pair."""

    def __init__(self):
        self.lock = threading.Lock()
        self.refresh_valid: str | None = "refresh-0"
        self.access_valid = {"access-0"}
        self.spent: list[str] = []
        self.reused = 0
        self.minted = 0
        self.pages: list[tuple[int, str]] = []
        # Page -> what happens just before that page is served.
        self.before_page: dict[int, object] = {}
        self.before_refresh = None
        self.refresh_error: Exception | None = None
        self.refuses_every_token = False
        # Two readers storing one event at once can collide on its unique key,
        # a separate matter from the token, so the concurrent test keeps them apart.
        self.distinct_events = False

    def refresh(self, refresh_token: str) -> ConnectorTokens:
        if self.before_refresh:
            self.before_refresh()
        if self.refresh_error:
            raise self.refresh_error
        with self.lock:
            self.spent.append(refresh_token)
            if refresh_token != self.refresh_valid:
                self.reused += 1
                raise ConnectorError("invalid_grant", auth=True)
            self.minted += 1
            self.refresh_valid = f"refresh-{self.minted}"
            self.access_valid = {f"access-{self.minted}"}
            return ConnectorTokens(
                access_token=f"access-{self.minted}", refresh_token=self.refresh_valid,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )

    def page(self, token: str, i: int) -> EventIn:
        hook = self.before_page.pop(i, None)
        if hook:
            hook()
        self.pages.append((i, token))
        if self.refuses_every_token or token not in self.access_valid:
            raise ConnectorError("the provider answered 401", auth=True)
        external_id = f"e-{i}-{len(self.pages)}" if self.distinct_events else f"e-{i}"
        return EventIn(external_id, "did_a_thing", T0 + timedelta(hours=i), {"i": i})

    def expire_early(self):
        """The access token dies before its ``expires_at`` says so."""
        self.access_valid = set()

    def revoke(self):
        self.access_valid = set()
        self.refresh_valid = None


class RotatingConnector:
    name = NAME
    display_name = "Rotating service"
    privacy_weight = "low"
    consent_disclosure = "We read your activity."
    consent_version = "2026-11-04"
    schedule = None

    def __init__(self, provider: RotatingProvider, pages: int = 3):
        self.provider = provider
        self.total = pages

    def event_types(self):
        return ["did_a_thing"]

    def is_configured(self):
        return True

    def authorize_url(self, *, redirect_uri, state, code_challenge):
        return "https://rotating.example/authorize"

    def handle_callback(self, *, code, redirect_uri, code_verifier):
        return ConnectorTokens(access_token="access-0", refresh_token="refresh-0")

    def revoke(self, tokens):
        pass

    def refresh_tokens(self, tokens):
        return self.provider.refresh(tokens.refresh_token)

    def initial_backfill(self, ctx):
        yield from self.incremental_sync(ctx, None)

    def incremental_sync(self, ctx, since):
        for i in range(self.total):
            yield ctx.call(lambda token, i=i: self.provider.page(token, i))


@pytest.fixture
def provider():
    return RotatingProvider()


@pytest.fixture
def conn(provider):
    connector = RotatingConnector(provider)
    registry.register_connector(connector)
    yield connector
    registry.unregister_connector(NAME)


def _seed(db, *, expires_at=None, refresh="refresh-0") -> str:
    """A connected grant, past its backfill, holding the provider's tokens."""
    svc._store_tokens(db, TENANT, NAME, ConnectorTokens(access_token="access-0", refresh_token=refresh, expires_at=expires_at))
    grant = EchoConnectorGrant(
        tenant_id=TENANT, connector=NAME, consent_version="2026-11-04", backfilled_at=PAST, last_sync_at=PAST,
    )
    db.add(grant)
    db.commit()
    return grant.id


def _stored(db) -> ConnectorTokens:
    db.expire_all()
    return svc.load_tokens(db, TENANT, NAME)


def _claim_columns(db):
    cred = db.query(EchoConnectorCredential).populate_existing().filter_by(tenant_id=TENANT, connector=NAME).one()
    return cred.refresh_claim, cred.refresh_claimed_at


def _grant(db, grant_id):
    db.expire_all()
    return db.get(EchoConnectorGrant, grant_id)


def _events(db):
    return {e.external_id for e in db.query(ActivityEvent).filter_by(tenant_id=TENANT, connector=NAME)}


# ------------------------------------------------------------------ a 401 in the middle of a sync

def test_a_401_mid_sync_renews_once_and_retries_that_call_once(db, provider, conn):
    grant_id = _seed(db)
    provider.before_page[1] = provider.expire_early

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "ok" and outcome.added == 3
    # Page 0 is not fetched again, page 1 is fetched twice, page 2 uses the new token.
    assert provider.pages == [(0, "access-0"), (1, "access-0"), (1, "access-1"), (2, "access-1")]
    assert provider.spent == ["refresh-0"], "one refresh"
    assert _events(db) == {"e-0", "e-1", "e-2"}
    stored = _stored(db)
    assert (stored.access_token, stored.refresh_token) == ("access-1", "refresh-1"), "the rotated pair is kept"
    assert _grant(db, grant_id).last_error is None


def test_the_worker_task_survives_a_401_mid_sync(db, provider, conn, monkeypatch):
    """The scheduled path: ``echo.sync_connector``."""
    import app.tasks.echo_connector_tasks as tasks

    grant_id = _seed(db)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    provider.before_page[0] = provider.expire_early
    assert tasks.sync_echo_connector(grant_id) == "ok"
    assert provider.spent == ["refresh-0"]


def test_a_revoked_grant_asks_to_reconnect_once_the_refresh_is_refused(db, provider, conn):
    grant_id = _seed(db)
    provider.before_page[1] = provider.revoke

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "auth_error"
    grant = _grant(db, grant_id)
    assert grant.status == "error" and grant.last_error.startswith(svc.RECONNECT_PREFIX)
    assert _stored(db).access_token == "access-0", "nothing overwritten"


def test_a_token_endpoint_outage_during_a_401_is_not_a_reconnect(db, provider, conn):
    grant_id = _seed(db)
    provider.before_page[0] = provider.expire_early
    provider.refresh_error = ConnectorError("token endpoint returned 503")

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "error", "the refresh token may still be good"
    assert not _grant(db, grant_id).last_error.startswith("Reconnect")
    assert "next sync tries again" in _grant(db, grant_id).last_error
    assert _claim_columns(db) == (None, None), "the claim was given back"

    provider.refresh_error = None
    assert svc.run_sync(db, grant_id).status == "ok"
    assert _grant(db, grant_id).last_error is None


def test_a_provider_refusing_a_token_it_just_issued_asks_to_reconnect(db, provider, conn):
    """The refresh worked and the retry is still a 401: nothing a sync can do."""
    grant_id = _seed(db)
    provider.refuses_every_token = True

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "auth_error"
    assert provider.pages == [(0, "access-0"), (0, "access-1")], "that call retried once"
    assert provider.spent == ["refresh-0"], "one refresh"
    assert _grant(db, grant_id).last_error.startswith(svc.RECONNECT_PREFIX)


def test_a_later_401_in_the_same_sync_waits_for_the_next_one(db, provider, conn):
    """One refresh per sync. A token that lapsed after a good renewal is not a
    revocation: the next sync's first call renews it."""
    grant_id = _seed(db)
    provider.before_page[0] = provider.expire_early
    provider.before_page[2] = provider.expire_early

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "error"
    assert provider.spent == ["refresh-0"], "the second 401 spent nothing"
    assert not _grant(db, grant_id).last_error.startswith("Reconnect")

    assert svc.run_sync(db, grant_id).status == "ok"
    assert _grant(db, grant_id).last_error is None


def test_a_401_with_nothing_to_renew_with_asks_to_reconnect(db, provider, conn):
    grant_id = _seed(db, refresh=None)
    provider.expire_early()
    outcome = svc.run_sync(db, grant_id)
    assert outcome.status == "auth_error"
    assert provider.pages == [(0, "access-0")], "no retry without a renewal"
    assert _grant(db, grant_id).last_error == svc.RECONNECT_PREFIX + "the provider answered 401"


def test_a_connector_that_skips_failed_calls_cannot_swallow_a_renewal_failure():
    """``GitHubConnector._commits`` skips a repository on an ordinary error."""
    responses = iter([HttpResponse(401, None), HttpResponse(200, [])])
    connector = GitHubConnector(request=lambda *a, **k: next(responses))

    def renew():
        raise TokenRenewalFailed("Sync failed: could not renew")

    ctx = SyncContext(tenant_id=TENANT, tokens=ConnectorTokens(access_token="t"), renew=renew)
    with pytest.raises(TokenRenewalFailed):
        list(connector._commits(ctx, "octo", "octo/repo", since=None))


# ------------------------------------------------------------------ one reader spends the token

def test_a_reader_that_loses_the_race_uses_the_first_readers_result(db, provider, conn, monkeypatch):
    """The second reader read the expired token, then the first finished. It
    must not send the spent refresh token."""
    grant_id = _seed(db, expires_at=PAST)
    real_claim = svc._claim_refresh
    ran = []

    def first_reader_finishes_first(*args):
        if not ran:
            ran.append(1)
            svc._store_tokens(db, TENANT, NAME, provider.refresh("refresh-0"))
        return real_claim(*args)

    monkeypatch.setattr(svc, "_claim_refresh", first_reader_finishes_first)

    assert svc.run_sync(db, grant_id).status == "ok"
    assert provider.spent == ["refresh-0"], "the first reader's refresh, and no other"
    assert provider.reused == 0
    assert {token for _, token in provider.pages} == {"access-1"}, "the second reader used the first's result"
    assert _claim_columns(db) == (None, None)


def test_a_live_claim_makes_a_reader_wait_then_fail_softly(db, provider, conn, monkeypatch):
    """Another reader holds the claim for longer than we wait, and is alive."""
    grant_id = _seed(db, expires_at=PAST)
    assert svc._claim_refresh(db, TENANT, NAME, "someone-else")
    monkeypatch.setattr(svc, "REFRESH_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(svc, "REFRESH_POLL_SECONDS", 0.01)

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "error"
    assert provider.spent == [], "the token stayed unspent"
    assert "next sync tries again" in _grant(db, grant_id).last_error
    assert _claim_columns(db)[0] == "someone-else", "not ours to release"


def test_a_claim_left_by_a_dead_reader_lapses(db, provider, conn):
    grant_id = _seed(db, expires_at=PAST)
    cred = db.query(EchoConnectorCredential).filter_by(tenant_id=TENANT, connector=NAME).one()
    cred.refresh_claim = "dead-reader"
    cred.refresh_claimed_at = datetime.now(timezone.utc).replace(tzinfo=None) - svc.REFRESH_CLAIM_TTL - timedelta(seconds=1)
    db.commit()

    assert svc.run_sync(db, grant_id).status == "ok"
    assert provider.spent == ["refresh-0"]
    assert _claim_columns(db) == (None, None)


def test_a_refusal_of_a_token_someone_else_already_rotated_is_not_a_revocation(db, provider, conn):
    """A reader that outlived its claim: the token it sent is spent, and the
    good result is already stored."""
    grant_id = _seed(db, expires_at=PAST)
    connector_refresh = conn.refresh_tokens

    def rotated_under_us(tokens):
        svc._store_tokens(db, TENANT, NAME, provider.refresh(tokens.refresh_token))
        conn.refresh_tokens = connector_refresh
        return connector_refresh(tokens)  # the same token again: invalid_grant

    conn.refresh_tokens = rotated_under_us

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "ok"
    assert provider.reused == 1
    assert {token for _, token in provider.pages} == {"access-1"}
    assert _grant(db, grant_id).last_error is None


def test_disconnecting_during_a_refresh_does_not_bring_the_token_back(db, provider, conn):
    grant_id = _seed(db, expires_at=PAST)
    provider.before_refresh = lambda: svc.revoke(db, TENANT, NAME)

    outcome = svc.run_sync(db, grant_id)

    assert outcome.status == "missing"
    assert db.query(EchoConnectorCredential).filter_by(tenant_id=TENANT).count() == 0
    assert db.query(EchoConnectorGrant).filter_by(tenant_id=TENANT).count() == 0


@pytest.mark.parametrize("refresh", ["reconnected-r", "refresh-0"], ids=["new refresh token", "same refresh token"])
def test_a_reconnect_during_a_refresh_is_not_written_over(db, provider, conn, refresh):
    """The user reconnects, perhaps as another account, while a sync waits on
    the provider. The renewal comes from the old grant: storing it would leave
    the new account's name on the old account's tokens and lose the new pair.
    A provider that does not rotate can hand back the same refresh token, so
    the check is on the pair."""
    grant_id = _seed(db, expires_at=PAST)
    spend = conn.refresh_tokens

    def reconnected_during_the_call(tokens):
        fresh = spend(tokens)
        svc._store_tokens(db, TENANT, NAME, ConnectorTokens(
            access_token="reconnected", refresh_token=refresh,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        provider.access_valid.add("reconnected")
        return fresh

    conn.refresh_tokens = reconnected_during_the_call

    assert svc.run_sync(db, grant_id).status == "ok"

    stored = _stored(db)
    assert (stored.access_token, stored.refresh_token) == ("reconnected", refresh)
    assert {token for _, token in provider.pages} == {"reconnected"}, "the sync went on with what is stored"
    assert _claim_columns(db) == (None, None)


def test_a_reader_that_outlived_its_claim_still_stores_what_it_renewed(db, provider, conn):
    """Nothing wrote the row while the provider answered, so the rotated token
    is the only live copy. Losing the claim is no reason to drop it."""
    grant_id = _seed(db, expires_at=PAST)

    def a_later_reader_took_the_lapsed_claim():
        cred = db.query(EchoConnectorCredential).filter_by(tenant_id=TENANT, connector=NAME).one()
        cred.refresh_claim = "later-reader"
        db.commit()

    provider.before_refresh = a_later_reader_took_the_lapsed_claim

    assert svc.run_sync(db, grant_id).status == "ok"

    assert _stored(db).refresh_token == "refresh-1"
    assert _claim_columns(db)[0] == "later-reader", "not ours to release"


def test_a_new_connect_clears_a_claim_on_the_old_tokens(db, provider, conn):
    _seed(db)
    assert svc._claim_refresh(db, TENANT, NAME, "old-reader")
    svc._store_tokens(db, TENANT, NAME, ConnectorTokens(access_token="fresh", refresh_token="fresh-r"))
    assert _claim_columns(db) == (None, None)


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """Two real connections: the shared in-memory test database has one."""
    url = "sqlite:///" + (tmp_path / "concurrent.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.mark.parametrize("why", ["expired", "refused_early"])
def test_a_scheduled_sync_and_sync_now_spend_a_rotating_token_once(sessions, provider, conn, monkeypatch, why):
    """Both find the token dead at the same moment, on two connections, and the
    winner stays inside the provider call until the loser has failed to claim.
    Without the claim the second sends a spent token and earns ``invalid_grant``."""
    import app.tasks.echo_connector_tasks as tasks

    monkeypatch.setattr(tasks, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "ECHO_CONNECTOR_SYNC", "inline")
    setup = sessions()
    grant_id = _seed(setup, expires_at=PAST if why == "expired" else None)
    setup.close()
    provider.distinct_events = True
    if why == "refused_early":
        provider.expire_early()

    start = threading.Barrier(2, timeout=10)
    loser_lost = threading.Event()
    real_claim = svc._claim_refresh

    def watched_claim(*args):
        won = real_claim(*args)
        if not won:
            loser_lost.set()
        return won

    monkeypatch.setattr(svc, "_claim_refresh", watched_claim)

    def winner_waits():
        assert loser_lost.wait(10), "the second reader never reached the claim"

    provider.before_refresh = winner_waits
    failures: list[BaseException] = []

    def reader(run):
        try:
            start.wait()
            run()
        except BaseException as e:  # noqa: BLE001 - reported on the main thread
            failures.append(e)

    scheduled = threading.Thread(target=reader, args=(lambda: tasks.sync_echo_connector(grant_id),))
    sync_now = threading.Thread(target=reader, args=(lambda: svc.enqueue_sync(grant_id),))
    scheduled.start()
    sync_now.start()
    scheduled.join(30)
    sync_now.join(30)
    assert not scheduled.is_alive() and not sync_now.is_alive()
    assert not failures, failures

    assert provider.spent == ["refresh-0"], "one refresh between the two readers"
    assert provider.reused == 0, "a spent token was never sent"
    check = sessions()
    try:
        assert byok_service.decrypt_secret(
            check.query(EchoConnectorCredential).filter_by(tenant_id=TENANT).one().refresh_token_encrypted
        ) == "refresh-1"
        grant = check.get(EchoConnectorGrant, grant_id)
        assert grant.status == "idle" and grant.last_error is None
    finally:
        check.close()
    served = [token for _, token in provider.pages]
    assert served.count("access-1") == 6, "both readers finished on the first's result"


# ------------------------------------------------------------------ tokens stay out of logs and errors

class _Logged:
    def __init__(self, monkeypatch):
        self.log = MagicMock()
        monkeypatch.setattr(svc, "logger", self.log)

    def __str__(self):
        return " ".join(str(x) for call in self.log.mock_calls for x in call.args)


TOKENS = ("access-0", "refresh-0", "access-1", "refresh-1")


def _assert_clean(text: str):
    assert not any(t in text for t in TOKENS), text


def test_a_provider_error_echoing_a_token_reaches_neither_the_log_nor_the_grant(db, provider, conn, monkeypatch):
    grant_id = _seed(db)
    logged = _Logged(monkeypatch)

    def echoes(token, i):
        raise ConnectorError(f"bad request: Authorization: Bearer {token}")

    provider.page = echoes
    assert svc.run_sync(db, grant_id).status == "error"

    _assert_clean(str(logged))
    _assert_clean(_grant(db, grant_id).last_error)
    assert "[token]" in _grant(db, grant_id).last_error


def test_a_token_is_scrubbed_before_a_long_message_is_cut(db, provider, conn, monkeypatch):
    """Cut first, and half a token survives past position 500."""
    grant_id = _seed(db)

    def echoes(token, i):
        raise ConnectorError("x" * 490 + f" token={token} " + "y" * 100)

    provider.page = echoes
    svc.run_sync(db, grant_id)
    assert "acc" not in _grant(db, grant_id).last_error


def test_a_refresh_error_echoing_a_token_reaches_neither_the_log_nor_the_grant(db, provider, conn, monkeypatch):
    grant_id = _seed(db, expires_at=PAST)
    logged = _Logged(monkeypatch)
    provider.refresh_error = ConnectorError("400 for refresh_token=refresh-0&access_token=access-0")
    assert svc.run_sync(db, grant_id).status == "error"
    assert "next sync tries again" in _grant(db, grant_id).last_error
    _assert_clean(str(logged))
    _assert_clean(_grant(db, grant_id).last_error)


def test_a_refresh_token_echoed_url_encoded_is_scrubbed_too(db, provider, conn, monkeypatch):
    """A form body carries it encoded, and Google's start ``1//``."""
    grant_id = _seed(db, expires_at=PAST, refresh="1//0g-refresh")
    logged = _Logged(monkeypatch)
    provider.refresh_error = ConnectorError("400 for grant_type=refresh_token&refresh_token=1%2F%2F0g-refresh")
    svc.run_sync(db, grant_id)
    assert "0g-refresh" not in str(logged)
    assert "0g-refresh" not in _grant(db, grant_id).last_error


def test_an_unexpected_crash_keeps_tokens_out_of_the_log(db, provider, conn, monkeypatch):
    grant_id = _seed(db)
    logged = _Logged(monkeypatch)

    def crashes(token, i):
        raise ValueError(f"cannot parse response for {token}")

    provider.page = crashes
    assert svc.run_sync(db, grant_id).status == "error"
    assert "ValueError" in str(logged), "the traceback is still there to read"
    _assert_clean(str(logged))
    _assert_clean(_grant(db, grant_id).last_error)


def test_a_mid_sync_renewal_logs_no_token(db, provider, conn, monkeypatch):
    grant_id = _seed(db)
    logged = _Logged(monkeypatch)
    provider.before_page[1] = provider.expire_early
    assert svc.run_sync(db, grant_id).status == "ok"
    assert "renewed" in str(logged)
    _assert_clean(str(logged))


def test_tokens_stay_out_of_repr():
    tokens = ConnectorTokens(access_token="secret-a", refresh_token="secret-r", account_label="octo")
    ctx = SyncContext(tenant_id=TENANT, tokens=tokens)
    assert "secret" not in repr(tokens) and "secret" not in repr(ctx)
    assert "octo" in repr(tokens)


# ------------------------------------------------------------------ the real connector's calls go through it

class RenewingGitHub(GitHubConnector):
    """GitHub's calls with a token that expires: what a connector that needs
    renewal gets from following GitHub's pattern."""

    name = "github_renewing"
    schedule = None
    minted = 0

    def refresh_tokens(self, tokens):
        self.minted += 1
        return ConnectorTokens(access_token=f"gh-new-{self.minted}", refresh_token=None,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1))


def _scripted(calls, refused="gh-old", refuse_after=1):
    def request(method, url, *, headers, data=None, json=None, auth=None):
        token = headers["Authorization"].removeprefix("Bearer ")
        calls.append((url.split("?")[0], token))
        if token == refused and len(calls) > refuse_after:
            return HttpResponse(401, {"message": "Bad credentials"})
        return HttpResponse(200, [])

    return request


def test_github_calls_renew_and_retry_through_the_runtime(db):
    calls: list[tuple[str, str]] = []
    connector = RenewingGitHub(request=_scripted(calls))
    registry.register_connector(connector)
    try:
        svc._store_tokens(db, TENANT, connector.name, ConnectorTokens(
            access_token="gh-old", refresh_token="gh-refresh", account_label="octo",
        ))
        grant = EchoConnectorGrant(tenant_id=TENANT, connector=connector.name, consent_version="v", backfilled_at=PAST, account_label="octo")
        db.add(grant)
        db.commit()

        assert svc.run_sync(db, grant.id).status == "ok"
    finally:
        registry.unregister_connector(connector.name)
    assert connector.minted == 1
    # The feed succeeds on the old token; the repositories call answers 401 and
    # is the one call retried.
    paths = [c[0].removeprefix("https://api.github.com") for c in calls]
    assert paths == ["/users/octo/events", "/users/octo/repos", "/users/octo/repos"]
    assert [c[1] for c in calls] == ["gh-old", "gh-old", "gh-new-1"]


def test_a_github_401_still_asks_to_reconnect_at_once(db):
    """GitHub's tokens do not expire, so a 401 is the user revoking the grant:
    no refresh token, no renewal, and the message says who refused."""
    calls: list[tuple[str, str]] = []
    connector = GitHubConnector(request=_scripted(calls, refuse_after=0))
    connector.name = "github_plain"
    registry.register_connector(connector)
    try:
        svc._store_tokens(db, TENANT, connector.name, ConnectorTokens(access_token="gh-old", account_label="octo"))
        grant = EchoConnectorGrant(tenant_id=TENANT, connector=connector.name, consent_version="v", backfilled_at=PAST, account_label="octo")
        db.add(grant)
        db.commit()

        outcome = svc.run_sync(db, grant.id)
    finally:
        registry.unregister_connector(connector.name)
    assert outcome.status == "auth_error" and len(calls) == 1
    assert grant.last_error == svc.RECONNECT_PREFIX + "GitHub refused the access token"

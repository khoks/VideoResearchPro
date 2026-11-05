"""T-3.2.1.13 — two syncs of one grant at once, on two real connections.

A scheduled sync and "Sync now" (or connecting, then "Sync now") can both read
an event or a fact as new and both insert it. The second used to fail on the
unique constraint and show "Sync failed: IntegrityError" until the next sync.

Each test holds both syncs just before their first insert into one table, so
both have read "not stored yet" every time: the collision is forced, not hoped
for. They run through the production callers, the worker task and
``enqueue_sync``.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.config import settings
from app.connectors import registry
from app.connectors.base import ActivityEvent as EventIn
from app.connectors.base import ConnectorTokens, DerivedFact
from app.database import Base
from app.models.activity_event import ActivityEvent
from app.models.echo_connector import EchoConnectorGrant
from app.models.personal_context import PersonalContext
from app.services import echo_connector_service as svc
from app.services import echo_service

NAME = "overlapping"
TENANT = "22222222-2222-2222-2222-222222222222"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
EVENTS = 5


class OverlappingConnector:
    name = NAME
    display_name = "Overlapping service"
    privacy_weight = "low"
    consent_disclosure = "We read your activity."
    consent_version = "2026-11-04"
    schedule = None

    def event_types(self):
        return ["did_a_thing"]

    def is_configured(self):
        return True

    def authorize_url(self, *, redirect_uri, state, code_challenge):
        return "https://overlapping.example/authorize"

    def handle_callback(self, *, code, redirect_uri, code_verifier):
        return ConnectorTokens(access_token="access")

    def revoke(self, tokens):
        pass

    def initial_backfill(self, ctx):
        yield from self.incremental_sync(ctx, None)

    def incremental_sync(self, ctx, since):
        ctx.facts.append(DerivedFact(kind="skill", key="rust", value="uses Rust", confidence=0.8))
        for i in range(EVENTS):
            yield EventIn(f"e-{i}", "did_a_thing", T0 + timedelta(hours=i), {"i": i})


@pytest.fixture
def conn():
    connector = OverlappingConnector()
    registry.register_connector(connector)
    yield connector
    registry.unregister_connector(NAME)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Two real connections: the shared in-memory test database has one."""
    url = "sqlite:///" + (tmp_path / "concurrent.db").as_posix()
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=eng)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(autocommit=False, autoflush=False, bind=eng))
    yield eng
    eng.dispose()


def _seed(backfilled: bool = False) -> str:
    db = database.SessionLocal()
    try:
        svc._store_tokens(db, TENANT, NAME, ConnectorTokens(access_token="access"))
        grant = EchoConnectorGrant(
            tenant_id=TENANT, connector=NAME, consent_version="2026-11-04",
            backfilled_at=T0 if backfilled else None, last_sync_at=T0 if backfilled else None,
        )
        db.add(grant)
        db.commit()
        return grant.id
    finally:
        db.close()


def _hold_both_before_the_first_insert(engine, table: str) -> None:
    """Neither sync writes to ``table`` until both are about to: by then each
    has read what is stored, and neither has seen the other's rows."""
    barrier = threading.Barrier(2, timeout=10)
    held = threading.local()

    def meet(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {table}") and not getattr(held, "done", False):
            held.done = True
            barrier.wait()

    event.listen(engine, "before_cursor_execute", meet)


def _sync_twice_at_once(grant_id: str, monkeypatch) -> list[svc.SyncOutcome]:
    import app.tasks.echo_connector_tasks as tasks

    monkeypatch.setattr(tasks, "SessionLocal", database.SessionLocal)
    monkeypatch.setattr(settings, "ECHO_CONNECTOR_SYNC", "inline")
    outcomes: list[svc.SyncOutcome] = []
    real_run = svc.run_sync

    def watched(db, gid):
        outcome = real_run(db, gid)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(svc, "run_sync", watched)
    start = threading.Barrier(2, timeout=10)
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
    return outcomes


def _assert_both_finished_clean(grant_id: str, outcomes: list[svc.SyncOutcome]) -> None:
    assert [o.status for o in outcomes] == ["ok", "ok"], [o.error for o in outcomes]
    assert sum(o.added for o in outcomes) == EVENTS, "each event is counted once, by the sync that stored it"
    check = database.SessionLocal()
    try:
        assert sorted(e.external_id for e in check.query(ActivityEvent).filter_by(tenant_id=TENANT)) == [
            f"e-{i}" for i in range(EVENTS)
        ]
        facts = check.query(PersonalContext).filter_by(user_id=TENANT).all()
        assert [(f.kind, f.key, f.source) for f in facts] == [("skill", "rust", svc.fact_source(NAME))]
        grant = check.get(EchoConnectorGrant, grant_id)
        assert grant.status == "idle" and grant.last_error is None
        assert grant.backfilled_at is not None
    finally:
        check.close()


@pytest.mark.parametrize("table", ["activity_events", "personal_context"])
def test_two_syncs_that_both_read_a_row_as_new_both_finish(engine, conn, monkeypatch, table):
    """``personal_context`` has the same check and the same constraint as the
    events, and a first sync (connecting, then "Sync now") writes both, so
    closing only ``store_events`` would have moved the failure one line down."""
    grant_id = _seed()
    _hold_both_before_the_first_insert(engine, table)
    _assert_both_finished_clean(grant_id, _sync_twice_at_once(grant_id, monkeypatch))


def test_two_incremental_syncs_collide_no_differently(engine, conn, monkeypatch):
    grant_id = _seed(backfilled=True)
    _hold_both_before_the_first_insert(engine, "activity_events")
    _assert_both_finished_clean(grant_id, _sync_twice_at_once(grant_id, monkeypatch))


# ------------------------------------------------------------------ a key stored since the read

def _reads_nothing_at_first(monkeypatch, times: int) -> None:
    """The write's own reads miss a row stored a moment later, as they would
    if another writer got in between them and the insert."""
    real = echo_service.get_context
    left = {"n": times}

    def stale(db, user_id, kind, key):
        if left["n"] > 0:
            left["n"] -= 1
            return None
        return real(db, user_id, kind, key)

    monkeypatch.setattr(echo_service, "get_context", stale)


def test_a_key_stored_since_the_read_is_updated_not_refused(db, monkeypatch):
    echo_service.record_context(db, user_id=TENANT, kind="skill", key="rust", value="old", source=svc.fact_source(NAME), confidence=0.5)
    _reads_nothing_at_first(monkeypatch, 1)

    row = echo_service.record_context(db, user_id=TENANT, kind="skill", key="rust", value="new", source=svc.fact_source(NAME), confidence=0.8)

    assert (row.value, row.confidence) == ("new", 0.8)
    assert db.query(PersonalContext).filter_by(user_id=TENANT).count() == 1


def test_a_fact_the_user_typed_since_the_read_stands(db, monkeypatch):
    """Losing the insert to the user must not become overwriting them: T-3.2.1.11
    holds in the race too. The next sync finds the row and notes ``wanted_by``."""
    echo_service.record_context(db, user_id=TENANT, kind="skill", key="rust", value="mine", source=echo_service.MANUAL_SOURCE)
    _reads_nothing_at_first(monkeypatch, 2)  # record_derived_context's read, then record_context's

    echo_service.record_derived_context(
        db, user_id=TENANT, kind="skill", key="rust", value="derived", source=svc.fact_source(NAME), confidence=0.8,
    )

    row = db.query(PersonalContext).filter_by(user_id=TENANT).one()
    assert (row.value, row.source) == ("mine", echo_service.MANUAL_SOURCE)

"""Usage written part-way through a scope, and Whisper seconds in the ledger
(T-5.2.12, T-5.2.13). This file pins the mechanism and the rules it keeps; the
crash and the Whisper paths at their callers are in
tests/test_tasks/test_usage_whisper_and_crash.py.

The suite's sessions share one connection (``StaticPool``), so a meter that
wrote into an open transaction of the caller's would commit it, and these
tests would see the caller's rolled-back work survive.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.report_agent import _map_in_context
from app.config import settings
from app.models.job import Job
from app.models.quota_usage import QuotaUsage
from app.services import auth_service, llm_service, usage_service
from tests.usage_helpers import call_llm, flush_always_due, metered_llms, usage_rows  # noqa: F401


@pytest.fixture
def clock(monkeypatch):
    time = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(usage_service, "_clock", lambda: time.now)
    return time


def _three(feature, calls=1):
    return {(feature, "llm_calls"): calls, (feature, "llm_tokens_in"): 100 * calls,
            (feature, "llm_tokens_out"): 20 * calls}


def _job(tenant_id):
    return Job(job_type="topic", topic="checkpoint-probe", num_videos=1, tenant_id=tenant_id)


def _jobs(db):
    db.expire_all()
    return db.query(Job).filter(Job.topic == "checkpoint-probe").count()


# ---------------------------------------------------------------- the interval


def test_without_a_scope_a_checkpoint_does_nothing(db):
    assert usage_service.checkpoint() is False


def test_nothing_is_written_until_the_interval_has_passed(db, test_user, metered_llms, clock, monkeypatch):
    monkeypatch.setattr(settings, "USAGE_FLUSH_INTERVAL_SECONDS", 60)
    with usage_service.metered(db, test_user.id):
        call_llm("echo_draft")
        clock.now += 59
        assert usage_service.checkpoint() is False
        assert usage_rows(db, test_user.id) == {}
        clock.now += 1
        assert usage_service.checkpoint() is True
        assert usage_rows(db, test_user.id) == _three("echo_draft")
        call_llm("echo_draft")
        clock.now += 59
        assert usage_service.checkpoint() is False, "the interval restarts at each write"
    assert usage_rows(db, test_user.id) == _three("echo_draft", calls=2)


def test_zero_writes_only_when_the_scope_closes(db, test_user, metered_llms, flush_always_due, monkeypatch):
    monkeypatch.setattr(settings, "USAGE_FLUSH_INTERVAL_SECONDS", 0)
    with usage_service.metered(db, test_user.id):
        call_llm("echo_draft")
        assert usage_service.checkpoint() is False
        assert usage_rows(db, test_user.id) == {}
    assert usage_rows(db, test_user.id) == _three("echo_draft")


def test_concurrent_callers_get_one_write_per_interval(clock):
    ledger = usage_service._Ledger()
    clock.now += 60
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: ledger.claim_flush(60), range(8)))
    assert sum(claims) == 1


# ---------------------------------------------------------------- once, and only once


def test_a_checkpoint_and_the_close_write_each_amount_once(db, test_user, metered_llms, clock):
    with usage_service.metered(db, test_user.id) as scope:
        call_llm("echo_draft")
        clock.now += 3600
        assert usage_service.checkpoint() is True
        assert scope.ledger.snapshot() == {}, "written amounts left the ledger"
        call_llm("echo_draft")
    assert usage_rows(db, test_user.id) == _three("echo_draft", calls=2)


def test_a_checkpoint_with_nothing_counted_writes_nothing(db, test_user, clock):
    with usage_service.metered(db, test_user.id):
        clock.now += 3600
        assert usage_service.checkpoint() is False
    assert usage_rows(db, test_user.id) == {}


def test_every_model_call_tries_a_checkpoint(db, test_user, metered_llms, flush_always_due):
    """A report's map batches have no loop of the task's to checkpoint in, so
    the meter tries after each call."""
    with usage_service.metered(db, test_user.id):
        call_llm("report_map_chunks")
        assert usage_rows(db, test_user.id) == _three("report")
        call_llm("report_map_chunks")
        assert usage_rows(db, test_user.id) == _three("report", calls=2)
    assert usage_rows(db, test_user.id) == _three("report", calls=2)


def test_a_failed_write_keeps_its_amounts_and_nothing_is_written_twice(db, test_user, metered_llms, clock, monkeypatch):
    real = usage_service._write
    attempts = []

    def locked_once(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("database is locked")
        return real(*args)

    monkeypatch.setattr(usage_service, "_write", locked_once)
    with usage_service.metered(db, test_user.id) as scope:
        call_llm("echo_draft")
        clock.now += 3600
        assert usage_service.checkpoint() is False
        assert scope.ledger.snapshot(), "lost with the failed write"
        assert usage_rows(db, test_user.id) == {}
    assert len(attempts) == 2
    assert usage_rows(db, test_user.id) == _three("echo_draft")


def test_a_failed_write_leaves_the_callers_work_alone(db, test_user, metered_llms, clock, monkeypatch):
    def locked(*args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(usage_service, "_write", locked)
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        call_llm("echo_draft")
        clock.now += 3600
        usage_service.checkpoint()
        db.commit()
    assert _jobs(db) == 1


# ---------------------------------------------------------------- the caller's session


def test_a_checkpoint_neither_commits_nor_discards_pending_changes(db, test_user, metered_llms, clock):
    test_user.failed_login_attempts = 4
    with usage_service.metered(db, test_user.id):
        call_llm("echo_draft")
        clock.now += 3600
        assert usage_service.checkpoint() is True
        assert db.is_modified(test_user), "the caller's change is still pending"
    db.rollback()
    db.expire_all()
    assert test_user.failed_login_attempts != 4
    assert usage_rows(db, test_user.id) == _three("echo_draft"), "spent, so recorded"


def test_a_checkpoint_waits_for_a_flushed_write_and_never_commits_it(db, test_user, metered_llms, flush_always_due):
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        db.flush()
        call_llm("echo_draft")
        assert usage_service.checkpoint() is False
        assert usage_rows(db, test_user.id) == {}, "wrote into the caller's open transaction"
    db.rollback()
    assert _jobs(db) == 0, "the meter committed the caller's flushed work"
    assert usage_rows(db, test_user.id) == _three("echo_draft"), "written once the transaction ended"


def test_every_whisper_response_tries_a_checkpoint(db, test_user, flush_always_due):
    """The chunks of a split recording are billed minutes apart, inside one
    iteration of the caller's loop and with no model call among them."""
    with usage_service.metered(db, test_user.id):
        usage_service.record_whisper(30.0)
        assert usage_rows(db, test_user.id) == {("ingest", "whisper_seconds"): 30}
        usage_service.record_whisper(30.0)
        assert usage_rows(db, test_user.id) == {("ingest", "whisper_seconds"): 60}
    assert usage_rows(db, test_user.id) == {("ingest", "whisper_seconds"): 60}


def test_a_whisper_try_waits_for_a_flushed_write_and_never_commits_it(db, test_user, flush_always_due):
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        db.flush()
        usage_service.record_whisper(30.0)
        assert usage_rows(db, test_user.id) == {}, "wrote into the caller's open transaction"
    db.rollback()
    assert _jobs(db) == 0, "the meter committed the caller's flushed work"
    assert usage_rows(db, test_user.id) == {("ingest", "whisper_seconds"): 30}, "written once the transaction ended"


def test_a_try_that_had_to_wait_does_not_use_up_the_interval(db, test_user, metered_llms, clock):
    """A sync's model call can land mid-iteration on a flushed session, every
    time. If that try restarted the interval, the clean checkpoint at the end
    of the iteration would never be due and the run would write nothing."""
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        db.flush()
        clock.now += 3600
        call_llm("echo_draft")
        db.commit()
        assert usage_service.checkpoint() is True
        assert usage_rows(db, test_user.id) == _three("echo_draft")
    assert _jobs(db) == 1
    assert usage_rows(db, test_user.id) == _three("echo_draft")


def test_a_checkpoint_sees_a_write_on_the_raw_connection(db, test_user, metered_llms, flush_always_due):
    with usage_service.metered(db, test_user.id):
        db.connection().exec_driver_sql(
            "UPDATE users SET failed_login_attempts = 9 WHERE id = ?", (test_user.id,)
        )
        call_llm("echo_draft")
        assert usage_service.checkpoint() is False
    db.rollback()
    db.expire_all()
    assert test_user.failed_login_attempts != 9, "the meter committed the caller's raw UPDATE"
    assert usage_rows(db, test_user.id) == _three("echo_draft")


# ---------------------------------------------------------------- threads


def _pool_call(n: int = 1) -> None:
    with ThreadPoolExecutor(max_workers=1) as pool:
        _map_in_context(pool, lambda i: call_llm("report_map_chunks", str(i)), range(n))


def test_a_pool_thread_writes_without_touching_the_callers_session(db, test_user, metered_llms, flush_always_due, monkeypatch):
    """Map batches run on a pool while the task's thread waits. A Session is
    not thread-safe, and those batches read through it for the BYOK key."""
    look = MagicMock(side_effect=AssertionError("touched the session off its thread"))
    monkeypatch.setattr(usage_service, "_caller_has_written", look)
    with usage_service.metered(db, test_user.id):
        _pool_call()
        assert usage_rows(db, test_user.id) == _three("report")
    look.assert_not_called()


def test_a_pool_thread_still_waits_for_a_flushed_write(db, test_user, metered_llms, flush_always_due):
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        db.flush()
        _pool_call()
        assert usage_rows(db, test_user.id) == {}
    db.rollback()
    assert _jobs(db) == 0
    assert usage_rows(db, test_user.id) == _three("report")


# ---------------------------------------------------------------- nesting


def test_a_nested_scope_checkpoints_the_outermost_session(db, test_user, metered_llms, clock):
    from tests.conftest import TestingSessionLocal

    inner_db = TestingSessionLocal()
    try:
        with usage_service.metered(db, test_user.id), llm_service.byok_context(test_user.id, inner_db):
            scope = usage_service.current_scope()
            assert scope.db is db
            call_llm("echo_draft")
            clock.now += 3600
            assert usage_service.checkpoint() is True
            assert usage_rows(db, test_user.id) == _three("echo_draft")
    finally:
        inner_db.close()
    assert usage_rows(db, test_user.id) == _three("echo_draft")


def test_a_checkpoint_writes_only_the_innermost_tenants_ledger(db, test_user, metered_llms, clock):
    other = auth_service.create_user(db, email="checkpoint-other@example.com", password="pw" * 6)
    with usage_service.metered(db, test_user.id):
        call_llm("echo_draft")
        with usage_service.metered(db, other.id):
            call_llm("echo_draft")
            clock.now += 3600
            assert usage_service.checkpoint() is True
            assert usage_rows(db, other.id) == _three("echo_draft")
            assert usage_rows(db, test_user.id) == {}
    assert usage_rows(db, test_user.id) == _three("echo_draft")
    assert usage_rows(db, other.id) == _three("echo_draft")


# ---------------------------------------------------------------- Whisper seconds


def test_whisper_seconds_go_to_the_scopes_feature_else_to_ingest(db, test_user):
    with usage_service.metered(db, test_user.id):
        usage_service.record_whisper(61.4)
    with usage_service.metered(db, test_user.id, feature="echo_shares"):
        usage_service.record_whisper(90.5)
    assert usage_rows(db, test_user.id) == {("ingest", "whisper_seconds"): 61, ("echo_shares", "whisper_seconds"): 90}


def test_a_sent_clip_never_rounds_away_and_no_audio_records_nothing(db, test_user):
    with usage_service.metered(db, test_user.id):
        usage_service.record_whisper(0.3)
        usage_service.record_whisper(0.0)
    assert usage_rows(db, test_user.id) == {("ingest", "whisper_seconds"): 1}


def test_whisper_outside_a_scope_records_nothing(db, test_user):
    usage_service.record_whisper(30.0)
    assert usage_rows(db, test_user.id) == {}


def test_whisper_seconds_stay_out_of_the_daily_quota_totals(db, test_user):
    """``/auth/quota`` reports caps, and Whisper has none (D-111)."""
    with usage_service.metered(db, test_user.id):
        usage_service.record_whisper(30.0)
    assert db.query(QuotaUsage).filter_by(user_id=test_user.id).count() == 0

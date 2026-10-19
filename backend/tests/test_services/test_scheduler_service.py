"""S-8.3.1 — the scheduler tick's service: cadence arithmetic, due selection,
the claim lease, per-tier dispatch, failure handling.

Every assertion here is on behaviour the plan (docs/plans/m3-saved-searches-
alerts.md) names: a duplicate tick is harmless, disabled rows never run, a
stale lease is reclaimable, "09:00 local" survives a DST change, a tick that
fires a little early advances from the scheduled time rather than running
the row twice, dispatch lands on the owning tenant's tier queue.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.models.scheduled_run import ScheduledRun
from app.services import auth_service, scheduler_service as svc
from app.services.scheduler_service import (
    STATUS_DISPATCH_FAILED,
    STATUS_DISPATCHED,
    STATUS_NO_HANDLER,
    CadenceError,
    compute_next_run,
    normalise_cadence,
    run_tick,
    schedule,
)

NOW = datetime(2026, 10, 19, 12, 0, 0)  # naive UTC, a Monday


@pytest.fixture
def fake_kind():
    """Register a kind backed by a MagicMock task; unregister afterwards."""
    task = MagicMock()
    task.name = "fake.run"
    task.apply_async = MagicMock(return_value=MagicMock(id="fake-task-id"))
    svc.register_kind("fake", task)
    try:
        yield task
    finally:
        svc.unregister_kind("fake")


def _every(seconds: int = 3600) -> dict:
    return {"cadence": "every", "seconds": seconds}


# ---------------------------------------------------------------------------
# Cadence validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"cadence": "hourly"},
        {"cadence": "every", "seconds": 5},
        {"cadence": "daily"},  # no hour
        {"cadence": "daily", "hour": 24},
        {"cadence": "daily", "hour": 9, "timezone": "Mars/Olympus"},
        {"cadence": "weekly", "hour": 9, "weekday": 7},
        {"cadence": "monthly", "hour": 9, "day_of_month": 29},
        "daily",
    ],
)
def test_normalise_cadence_rejects(bad):
    with pytest.raises(CadenceError):
        normalise_cadence(bad)


def test_normalise_cadence_canonical_form_drops_unknown_keys_and_defaults():
    out = normalise_cadence({"cadence": "Daily", "hour": "9", "cron": "* * *"})
    assert out == {"cadence": "daily", "hour": 9, "minute": 0, "timezone": "UTC"}


# ---------------------------------------------------------------------------
# compute_next_run
# ---------------------------------------------------------------------------


def test_every_adds_seconds():
    assert compute_next_run(_every(900), NOW) == NOW + timedelta(seconds=900)


def test_daily_in_ist_is_strictly_after():
    # 09:00 IST == 03:30 UTC. At 12:00 UTC today that slot has passed.
    cad = {"cadence": "daily", "hour": 9, "timezone": "Asia/Kolkata"}
    assert compute_next_run(cad, NOW) == datetime(2026, 10, 20, 3, 30)
    # Exactly on the slot → next day, never "now".
    assert compute_next_run(cad, datetime(2026, 10, 20, 3, 30)) == datetime(2026, 10, 21, 3, 30)


def test_weekly_uses_python_weekday_convention():
    # weekday 0 == Monday. NOW is Monday 12:00 UTC, slot 09:00 → next Monday.
    cad = {"cadence": "weekly", "hour": 9, "weekday": 0}
    nxt = compute_next_run(cad, NOW)
    assert nxt == datetime(2026, 10, 26, 9, 0) and nxt.weekday() == 0
    # weekday 6 == Sunday.
    nxt = compute_next_run({"cadence": "weekly", "hour": 9, "weekday": 6}, NOW)
    assert nxt == datetime(2026, 10, 25, 9, 0) and nxt.weekday() == 6


def test_monthly_crosses_year_end():
    cad = {"cadence": "monthly", "hour": 6, "minute": 30, "day_of_month": 1}
    assert compute_next_run(cad, datetime(2026, 12, 15)) == datetime(2027, 1, 1, 6, 30)


def test_daily_stays_at_local_wall_time_across_spring_forward():
    """New York springs forward on 2026-03-08. 09:00 local is 14:00 UTC
    before and 13:00 UTC after. The row must follow the wall clock."""
    cad = {"cadence": "daily", "hour": 9, "timezone": "America/New_York"}
    before = datetime(2026, 3, 7, 15, 0)  # 10:00 EST on the 7th
    assert compute_next_run(cad, before) == datetime(2026, 3, 8, 13, 0)  # 09:00 EDT


def test_daily_stays_at_local_wall_time_across_fall_back():
    """New York falls back on 2026-11-01: 09:00 local goes from 13:00 UTC
    to 14:00 UTC."""
    cad = {"cadence": "daily", "hour": 9, "timezone": "America/New_York"}
    before = datetime(2026, 10, 31, 14, 0)  # 10:00 EDT on the 31st
    assert compute_next_run(cad, before) == datetime(2026, 11, 1, 14, 0)  # 09:00 EST


def test_aware_input_is_normalised_to_utc():
    from datetime import timezone as tz
    from zoneinfo import ZoneInfo

    aware = datetime(2026, 10, 19, 17, 30, tzinfo=ZoneInfo("Asia/Kolkata"))  # 12:00 UTC
    assert compute_next_run(_every(60), aware) == NOW + timedelta(seconds=60)
    assert compute_next_run(_every(60), NOW.replace(tzinfo=tz.utc)) == NOW + timedelta(seconds=60)


# ---------------------------------------------------------------------------
# schedule / unschedule / set_enabled
# ---------------------------------------------------------------------------


def test_schedule_upserts_on_kind_and_target(db):
    a = schedule(db, kind="fake", target_id="t1", cadence=_every(3600), now=NOW)
    b = schedule(db, kind="fake", target_id="t1", cadence=_every(7200), now=NOW)
    assert a.id == b.id
    assert db.query(ScheduledRun).count() == 1
    assert json.loads(b.cadence_json)["seconds"] == 7200
    assert b.next_run_at == NOW + timedelta(seconds=7200)


def test_schedule_rejects_bad_cadence_without_writing(db):
    with pytest.raises(CadenceError):
        schedule(db, kind="fake", target_id="t1", cadence={"cadence": "never"})
    assert db.query(ScheduledRun).count() == 0


def test_set_enabled_resume_skips_slots_missed_while_paused(db):
    row = schedule(db, kind="fake", target_id="t1", cadence=_every(3600), now=NOW, enabled=False)
    # Pretend a long pause: the stored slot is in the past.
    row.next_run_at = NOW - timedelta(days=2)
    db.commit()
    resumed = svc.set_enabled(db, "fake", "t1", True)
    assert resumed.enabled is True
    assert resumed.next_run_at > svc.utcnow()


def test_unschedule(db):
    schedule(db, kind="fake", target_id="t1", cadence=_every(), now=NOW)
    assert svc.unschedule(db, "fake", "t1") is True
    assert svc.unschedule(db, "fake", "t1") is False


# ---------------------------------------------------------------------------
# run_tick — due selection, disabled rows, lease, duplicate tick
# ---------------------------------------------------------------------------


def test_tick_dispatches_only_due_enabled_rows(db, fake_kind):
    due = schedule(db, kind="fake", target_id="due", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))
    schedule(db, kind="fake", target_id="future", cadence=_every(3600), start_at=NOW + timedelta(hours=1))
    schedule(db, kind="fake", target_id="off", cadence=_every(3600), start_at=NOW - timedelta(minutes=1), enabled=False)

    result = run_tick(db, now=NOW)

    assert result["dispatched"] == 1 and result["considered"] == 1
    fake_kind.apply_async.assert_called_once()
    assert fake_kind.apply_async.call_args.kwargs["args"] == ["due"]
    assert fake_kind.apply_async.call_args.kwargs["kwargs"] == {"scheduled_run_id": due.id}

    db.refresh(due)
    assert due.last_status == STATUS_DISPATCHED
    assert due.last_run_at == NOW
    assert due.claimed_at is None
    assert due.next_run_at == NOW + timedelta(hours=1)
    assert due.consecutive_failures == 0


def test_duplicate_tick_is_harmless(db, fake_kind):
    schedule(db, kind="fake", target_id="t1", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))
    first = run_tick(db, now=NOW)
    second = run_tick(db, now=NOW)
    assert first["dispatched"] == 1
    assert second == {"considered": 0, "dispatched": 0, "failed": 0, "no_handler": 0, "bad_cadence": 0, "skipped": 0}
    assert fake_kind.apply_async.call_count == 1


def test_fresh_claim_is_skipped_and_stale_claim_is_reclaimed(db, fake_kind):
    """Two rows past due. One was claimed a moment ago by another tick (still
    being dispatched); one was claimed longer ago than the lease (that tick
    died). Only the stale one may be taken."""
    fresh = schedule(db, kind="fake", target_id="fresh", cadence=_every(3600), start_at=NOW - timedelta(minutes=5))
    stale = schedule(db, kind="fake", target_id="stale", cadence=_every(3600), start_at=NOW - timedelta(minutes=5))
    fresh.claimed_at = NOW - timedelta(seconds=10)
    stale.claimed_at = NOW - timedelta(seconds=settings.SCHEDULER_LEASE_SECONDS + 1)
    db.commit()

    result = run_tick(db, now=NOW)

    assert result["dispatched"] == 1
    assert fake_kind.apply_async.call_args.kwargs["args"] == ["stale"]
    db.refresh(fresh)
    assert fresh.last_status is None and fresh.claimed_at == NOW - timedelta(seconds=10)


def test_lost_claim_race_counts_as_skipped(db, fake_kind, monkeypatch):
    schedule(db, kind="fake", target_id="t1", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))
    monkeypatch.setattr(svc, "_claim", lambda *a, **k: False)
    result = run_tick(db, now=NOW)
    assert result["skipped"] == 1 and result["dispatched"] == 0
    fake_kind.apply_async.assert_not_called()


def test_batch_limit_takes_earliest_first(db, fake_kind):
    for i in range(5):
        schedule(db, kind="fake", target_id=f"t{i}", cadence=_every(3600), start_at=NOW - timedelta(minutes=i + 1))
    result = run_tick(db, now=NOW, limit=2)
    assert result["dispatched"] == 2
    dispatched = [c.kwargs["args"][0] for c in fake_kind.apply_async.call_args_list]
    assert dispatched == ["t4", "t3"]  # most overdue first


# ---------------------------------------------------------------------------
# Clock skew: an early tick
# ---------------------------------------------------------------------------


def test_early_tick_within_grace_runs_and_advances_from_scheduled_time(db, fake_kind):
    """Beat fires 20 s before a daily 09:00 slot. The row runs now (within
    SCHEDULER_GRACE_SECONDS) and advances to TOMORROW's 09:00 — not to
    today's 09:00 twenty seconds later, which would run it twice."""
    slot = datetime(2026, 10, 20, 9, 0)
    early = slot - timedelta(seconds=20)
    row = schedule(db, kind="fake", target_id="t1", cadence={"cadence": "daily", "hour": 9}, start_at=slot)

    result = run_tick(db, now=early)

    assert result["dispatched"] == 1
    db.refresh(row)
    assert row.next_run_at == datetime(2026, 10, 21, 9, 0)


def test_row_beyond_grace_is_not_due(db, fake_kind):
    slot = datetime(2026, 10, 20, 9, 0)
    schedule(db, kind="fake", target_id="t1", cadence={"cadence": "daily", "hour": 9}, start_at=slot)
    result = run_tick(db, now=slot - timedelta(seconds=settings.SCHEDULER_GRACE_SECONDS + 1))
    assert result["considered"] == 0
    fake_kind.apply_async.assert_not_called()


# ---------------------------------------------------------------------------
# Dispatch routing: tier queues
# ---------------------------------------------------------------------------


def test_dispatch_lands_on_the_tenants_tier_queue(db, fake_kind):
    pro = auth_service.create_user(db, email="pro@x.com", password="pw" * 6)
    pro.tier = "pro"
    db.commit()
    schedule(db, kind="fake", target_id="t1", cadence=_every(3600), tenant_id=pro.id, start_at=NOW - timedelta(minutes=1))

    run_tick(db, now=NOW)

    assert fake_kind.apply_async.call_args.kwargs["queue"] == "tier_pro"


def test_system_row_without_tenant_uses_default_queue(db, fake_kind):
    schedule(db, kind="fake", target_id="t1", cadence=_every(3600), tenant_id=None, start_at=NOW - timedelta(minutes=1))
    run_tick(db, now=NOW)
    assert fake_kind.apply_async.call_args.kwargs["queue"] == "default"


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_unknown_kind_is_recorded_and_advanced_not_retried_each_tick(db):
    svc.unregister_kind("ghost")
    row = schedule(db, kind="ghost", target_id="t1", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))

    result = run_tick(db, now=NOW)

    assert result["no_handler"] == 1
    db.refresh(row)
    assert row.last_status == STATUS_NO_HANDLER
    assert "ghost" in (row.last_error or "")
    assert row.next_run_at == NOW + timedelta(hours=1)  # cadence, not next tick
    assert row.enabled is True


def test_dispatch_failure_retries_next_tick_then_falls_back_to_cadence(db, fake_kind):
    fake_kind.apply_async.side_effect = ConnectionError("broker down")
    row = schedule(db, kind="fake", target_id="t1", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))

    tick = timedelta(seconds=settings.SCHEDULER_TICK_SECONDS)
    now = NOW
    for attempt in range(1, settings.SCHEDULER_MAX_RETRY_TICKS + 1):
        result = run_tick(db, now=now)
        assert result["failed"] == 1
        db.refresh(row)
        assert row.last_status == STATUS_DISPATCH_FAILED
        assert row.consecutive_failures == attempt
        assert "broker down" in row.last_error
        assert row.next_run_at == now + tick, f"attempt {attempt} should retry at the next tick"
        assert row.claimed_at is None
        now = row.next_run_at

    # One more failure exhausts the retry budget: wait for the cadence.
    run_tick(db, now=now)
    db.refresh(row)
    assert row.consecutive_failures == settings.SCHEDULER_MAX_RETRY_TICKS + 1
    assert row.next_run_at == now + timedelta(hours=1)

    # Recovery resets the counter.
    fake_kind.apply_async.side_effect = None
    run_tick(db, now=row.next_run_at)
    db.refresh(row)
    assert row.last_status == STATUS_DISPATCHED and row.consecutive_failures == 0 and row.last_error is None


def test_one_failing_row_does_not_block_the_others(db, fake_kind):
    good = schedule(db, kind="fake", target_id="good", cadence=_every(3600), start_at=NOW - timedelta(minutes=2))
    schedule(db, kind="ghost", target_id="bad", cadence=_every(3600), start_at=NOW - timedelta(minutes=3))
    result = run_tick(db, now=NOW)
    assert result["dispatched"] == 1 and result["no_handler"] == 1
    db.refresh(good)
    assert good.last_status == STATUS_DISPATCHED


def test_corrupt_cadence_disables_the_row(db, fake_kind):
    row = schedule(db, kind="fake", target_id="t1", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))
    row.cadence_json = "{not json"
    db.commit()
    result = run_tick(db, now=NOW)
    assert result["bad_cadence"] == 1
    db.refresh(row)
    assert row.enabled is False and row.last_status == "bad_cadence"
    fake_kind.apply_async.assert_not_called()


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


def test_status_counts(db, fake_kind):
    schedule(db, kind="fake", target_id="due", cadence=_every(3600), start_at=NOW - timedelta(minutes=1))
    schedule(db, kind="fake", target_id="later", cadence=_every(3600), start_at=NOW + timedelta(hours=1))
    schedule(db, kind="fake", target_id="off", cadence=_every(3600), start_at=NOW - timedelta(minutes=1), enabled=False)
    s = svc.status(db, now=NOW)
    assert s["rows"] == {"total": 3, "enabled": 2, "due": 1, "claimed": 0}
    assert "fake" in s["kinds"]
    assert s["last_run_at"] is None
    run_tick(db, now=NOW)
    assert svc.status(db, now=NOW)["last_run_at"] == NOW.isoformat() + "Z"

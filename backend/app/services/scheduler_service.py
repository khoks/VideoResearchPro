"""Scheduler tick — the shared "run X for tenant T at cadence C" machinery (S-8.3.1 / M3).

Shape, decided in ``docs/plans/m3-saved-searches-alerts.md``:

* **One static Celery beat entry**, ``scheduler.tick``, every
  ``SCHEDULER_TICK_SECONDS`` (``app/tasks/scheduler_tasks.py``). Beat is a
  separate process started by ``scripts/start.ps1``; exactly one must run.
* **The schedule is rows**, not beat entries: ``scheduled_runs`` holds one
  row per ``(kind, target_id)`` with a human cadence and a UTC
  ``next_run_at``. Users never see cron.
* **The tick claims, then dispatches.** A row is claimed with a single
  ``UPDATE … WHERE claimed_at IS NULL`` so a duplicate tick (two beats, a
  slow tick overlapping the next) is harmless: the second claim affects
  zero rows. The claim is a *lease*: older than ``SCHEDULER_LEASE_SECONDS``
  it is stale and can be taken again, which is what recovers from a crash
  between claim and advance.
* **Per-kind dispatch goes through ``task_routing_service``** so the work
  lands on the owning tenant's tier queue, exactly like user-initiated
  jobs. Kinds register themselves (``register_kind``) from the task module
  that defines their Celery task; a row whose kind is unknown to this
  worker is recorded as ``no_handler`` and advanced, never retried every
  tick.
* **``next_run_at`` is computed by Celery's own ``crontab``** for
  ``daily`` / ``weekly`` / ``monthly`` (in the row's IANA zone, so a 09:00
  local run stays 09:00 local across a DST change) and by plain addition
  for ``every``. The base is ``max(now, next_run_at)``: a tick that fires a
  little early (``SCHEDULER_GRACE_SECONDS``) still advances from the
  *scheduled* time, so a daily run is never dispatched twice.

Every datetime handled here is **naive UTC**. SQLite's ``DateTime`` stores
no tzinfo and hands back naive values, and mixing those with aware values
raises in Python; normalising at the edge (``_naive_utc``) keeps the
comparisons honest everywhere else.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery.schedules import crontab
from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.scheduled_run import ScheduledRun
from app.services import task_routing_service

logger = logging.getLogger(__name__)

CADENCES = ("every", "daily", "weekly", "monthly")

STATUS_DISPATCHED = "dispatched"
STATUS_DISPATCH_FAILED = "dispatch_failed"
STATUS_NO_HANDLER = "no_handler"
STATUS_BAD_CADENCE = "bad_cadence"

# The smallest `every` interval. Anything shorter than the tick itself would
# just run once per tick anyway, and a sub-minute cadence has no use here.
MIN_EVERY_SECONDS = 60


class CadenceError(ValueError):
    """A cadence dict that cannot be scheduled. Raised at write time so a
    bad cadence never reaches the table."""


class NoHandlerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _naive_utc(dt: datetime) -> datetime:
    """Normalise any datetime to naive UTC (see module docstring)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


def _int_in(cadence: dict, key: str, lo: int, hi: int, default: int | None = None) -> int:
    raw = cadence.get(key, default)
    if raw is None:
        raise CadenceError(f"cadence '{cadence.get('cadence')}' needs '{key}'")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise CadenceError(f"'{key}' must be an integer, got {raw!r}") from None
    if not lo <= value <= hi:
        raise CadenceError(f"'{key}' must be between {lo} and {hi}, got {value}")
    return value


def normalise_cadence(cadence: dict[str, Any]) -> dict[str, Any]:
    """Validate a cadence dict and return the canonical form that is stored.

    Accepted shapes (keys beyond these are dropped)::

        {"cadence": "every",   "seconds": N}                       N >= 60
        {"cadence": "daily",   "hour", "minute"?, "timezone"?}
        {"cadence": "weekly",  "hour", "minute"?, "weekday", "timezone"?}
        {"cadence": "monthly", "hour", "minute"?, "day_of_month", "timezone"?}

    ``weekday`` is Python's convention (0 = Monday … 6 = Sunday).
    ``day_of_month`` is capped at 28 so every month has the day; a "last
    day of month" cadence is not offered. ``timezone`` is an IANA name,
    default UTC.
    """
    if not isinstance(cadence, dict):
        raise CadenceError("cadence must be an object")
    kind = str(cadence.get("cadence", "")).strip().lower()
    if kind not in CADENCES:
        raise CadenceError(f"unknown cadence {kind!r}; expected one of {CADENCES}")

    if kind == "every":
        seconds = _int_in(cadence, "seconds", MIN_EVERY_SECONDS, 365 * 24 * 3600)
        return {"cadence": "every", "seconds": seconds}

    tz_name = str(cadence.get("timezone") or "UTC")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise CadenceError(f"unknown timezone {tz_name!r}") from None

    out: dict[str, Any] = {
        "cadence": kind,
        "hour": _int_in(cadence, "hour", 0, 23),
        "minute": _int_in(cadence, "minute", 0, 59, default=0),
        "timezone": tz_name,
    }
    if kind == "weekly":
        out["weekday"] = _int_in(cadence, "weekday", 0, 6)
    elif kind == "monthly":
        out["day_of_month"] = _int_in(cadence, "day_of_month", 1, 28)
    return out


def _crontab_for(cadence: dict[str, Any]) -> crontab:
    kind = cadence["cadence"]
    if kind == "daily":
        return crontab(minute=cadence["minute"], hour=cadence["hour"])
    if kind == "weekly":
        # Celery counts Sunday as 0; Python counts Monday as 0.
        celery_dow = (int(cadence["weekday"]) + 1) % 7
        return crontab(
            minute=cadence["minute"], hour=cadence["hour"], day_of_week=str(celery_dow)
        )
    if kind == "monthly":
        return crontab(
            minute=cadence["minute"],
            hour=cadence["hour"],
            day_of_month=str(cadence["day_of_month"]),
        )
    raise CadenceError(f"cadence {kind!r} has no crontab form")


def compute_next_run(cadence: dict[str, Any], after: datetime) -> datetime:
    """The first run strictly after ``after`` (naive UTC in, naive UTC out).

    For the crontab cadences the arithmetic runs on the row's local wall
    clock: ``after`` is converted into the zone, the tzinfo is dropped, and
    Celery's ``crontab.remaining_delta`` (which does DST-free arithmetic in
    the app's UTC zone) is applied to that naive wall time. Re-attaching
    the zone afterwards is what keeps "09:00 local" at 09:00 local across a
    DST transition instead of drifting an hour.
    """
    cadence = normalise_cadence(cadence)
    after = _naive_utc(after)

    if cadence["cadence"] == "every":
        return after + timedelta(seconds=cadence["seconds"])

    tz = ZoneInfo(cadence["timezone"])
    spec = _crontab_for(cadence)
    wall = after.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)

    # A non-existent local time (the DST gap) can resolve to an instant at
    # or before `after`; step past it. Two rounds are enough in practice,
    # the loop bound is defensive.
    for _ in range(4):
        last, delta, _now = spec.remaining_delta(wall)
        next_wall = (last + delta).replace(tzinfo=None)
        next_utc = _naive_utc(next_wall.replace(tzinfo=tz))
        if next_utc > after:
            return next_utc
        wall = next_wall
    raise CadenceError(f"could not advance cadence {cadence!r} past {after.isoformat()}")


# ---------------------------------------------------------------------------
# Kind registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledKind:
    name: str
    task: Any  # a Celery task (anything with .apply_async and .name)
    args_for: Callable[[ScheduledRun], tuple[list[Any], dict[str, Any]]]


def _default_args(run: ScheduledRun) -> tuple[list[Any], dict[str, Any]]:
    return [run.target_id], {"scheduled_run_id": run.id}


_KINDS: dict[str, ScheduledKind] = {}


def register_kind(
    name: str,
    task: Any,
    *,
    args_for: Callable[[ScheduledRun], tuple[list[Any], dict[str, Any]]] | None = None,
) -> None:
    """Register the Celery task that runs rows of ``kind == name``.

    Call this from the task module that defines the task (so a worker that
    imports the module can dispatch the kind) — ``saved_search`` will
    register from ``tasks/saved_search_tasks.py`` in S-8.3.2. By default the
    task is called as ``task(target_id, scheduled_run_id=…)``; pass
    ``args_for`` to change the call shape. Idempotent; re-registering
    replaces.
    """
    if not name or len(name) > 32:
        raise ValueError("kind name must be 1–32 characters")
    _KINDS[name] = ScheduledKind(name=name, task=task, args_for=args_for or _default_args)


def unregister_kind(name: str) -> None:
    _KINDS.pop(name, None)


def registered_kinds() -> list[str]:
    return sorted(_KINDS)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def schedule(
    db: Session,
    *,
    kind: str,
    target_id: str,
    cadence: dict[str, Any],
    tenant_id: str | None = None,
    enabled: bool = True,
    start_at: datetime | None = None,
    now: datetime | None = None,
) -> ScheduledRun:
    """Create or update the row for ``(kind, target_id)``.

    ``next_run_at`` becomes ``start_at`` when given, otherwise the first
    cadence slot after ``now``. Updating an existing row recomputes
    ``next_run_at`` from the new cadence and clears any stale claim; it
    never touches ``last_*``. Raises ``CadenceError`` on a bad cadence.
    """
    canonical = normalise_cadence(cadence)
    now = _naive_utc(now or utcnow())
    next_run_at = _naive_utc(start_at) if start_at else compute_next_run(canonical, now)

    row = (
        db.query(ScheduledRun)
        .filter(ScheduledRun.kind == kind, ScheduledRun.target_id == target_id)
        .first()
    )
    if row is None:
        row = ScheduledRun(kind=kind, target_id=target_id)
        db.add(row)
    row.tenant_id = tenant_id
    row.cadence_json = json.dumps(canonical)
    row.next_run_at = next_run_at
    row.enabled = enabled
    row.claimed_at = None
    db.commit()
    db.refresh(row)
    return row


def get_run(db: Session, kind: str, target_id: str) -> ScheduledRun | None:
    return (
        db.query(ScheduledRun)
        .filter(ScheduledRun.kind == kind, ScheduledRun.target_id == target_id)
        .first()
    )


def unschedule(db: Session, kind: str, target_id: str) -> bool:
    row = get_run(db, kind, target_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def set_enabled(db: Session, kind: str, target_id: str, enabled: bool) -> ScheduledRun | None:
    """Pause or resume. Resuming a row whose slot passed while paused moves
    it to the next slot rather than firing immediately."""
    row = get_run(db, kind, target_id)
    if row is None:
        return None
    row.enabled = enabled
    if enabled:
        now = utcnow()
        if row.next_run_at <= now:
            row.next_run_at = compute_next_run(json.loads(row.cadence_json), now)
    row.claimed_at = None
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def _due_filter(now: datetime, horizon: datetime, stale_before: datetime):
    return (
        ScheduledRun.enabled.is_(True),
        ScheduledRun.next_run_at <= horizon,
        or_(ScheduledRun.claimed_at.is_(None), ScheduledRun.claimed_at < stale_before),
    )


def _claim(db: Session, run_id: str, now: datetime, horizon: datetime, stale_before: datetime) -> bool:
    """Take the lease on one row. Atomic per row: the UPDATE's WHERE repeats
    the due conditions, so of two concurrent ticks exactly one sees
    rowcount 1."""
    result = db.execute(
        update(ScheduledRun)
        .where(ScheduledRun.id == run_id, *_due_filter(now, horizon, stale_before))
        .values(claimed_at=now)
    )
    db.commit()
    return result.rowcount == 1


def _dispatch_one(db: Session, run: ScheduledRun, now: datetime, result: dict[str, int]) -> None:
    """Dispatch a claimed row and advance it. Always releases the claim."""
    base = max(now, run.next_run_at)
    try:
        cadence = json.loads(run.cadence_json or "")
        cadence = normalise_cadence(cadence)
    except (ValueError, TypeError) as e:
        # Unschedulable rows are disabled, not retried: the writer validated
        # the cadence, so this is corruption, and a loud log is the fix.
        logger.error("scheduler: row %s has an unreadable cadence (%s); disabling", run.id, e)
        run.enabled = False
        run.last_status = STATUS_BAD_CADENCE
        run.last_error = str(e)[:2000]
        run.last_run_at = now
        run.claimed_at = None
        db.commit()
        result["bad_cadence"] += 1
        return

    handler = _KINDS.get(run.kind)
    try:
        if handler is None:
            raise NoHandlerError(
                f"no task registered for kind {run.kind!r} in this worker "
                f"(registered: {registered_kinds()})"
            )
        args, kwargs = handler.args_for(run)
        task_routing_service.dispatch_for_tenant_id(handler.task, db, run.tenant_id, *args, **kwargs)
    except NoHandlerError as e:
        logger.warning("scheduler: %s; advancing row %s without dispatch", e, run.id)
        run.last_status = STATUS_NO_HANDLER
        run.last_error = str(e)[:2000]
        run.consecutive_failures += 1
        run.next_run_at = compute_next_run(cadence, base)
        result["no_handler"] += 1
    except Exception as e:  # noqa: BLE001 — a broker outage must not kill the tick
        logger.exception("scheduler: dispatch failed for row %s kind=%s", run.id, run.kind)
        run.last_status = STATUS_DISPATCH_FAILED
        run.last_error = f"{type(e).__name__}: {e}"[:2000]
        run.consecutive_failures += 1
        if run.consecutive_failures <= settings.SCHEDULER_MAX_RETRY_TICKS:
            # Transient (broker down): try again next tick, not next week.
            run.next_run_at = now + timedelta(seconds=settings.SCHEDULER_TICK_SECONDS)
        else:
            run.next_run_at = compute_next_run(cadence, base)
        result["failed"] += 1
    else:
        run.last_status = STATUS_DISPATCHED
        run.last_error = None
        run.consecutive_failures = 0
        run.next_run_at = compute_next_run(cadence, base)
        result["dispatched"] += 1
    finally:
        run.last_run_at = now
        run.claimed_at = None
        db.commit()


def run_tick(db: Session, now: datetime | None = None, *, limit: int | None = None) -> dict[str, int]:
    """One scheduler tick: claim every due row (up to ``limit``) and dispatch it.

    Returns counts for the log line and the tests:
    ``considered`` (rows that looked due), ``dispatched``, ``failed``,
    ``no_handler``, ``bad_cadence`` and ``skipped`` (lost the claim race).
    Safe to call concurrently with itself.
    """
    now = _naive_utc(now or utcnow())
    limit = limit or settings.SCHEDULER_BATCH_SIZE
    horizon = now + timedelta(seconds=settings.SCHEDULER_GRACE_SECONDS)
    stale_before = now - timedelta(seconds=settings.SCHEDULER_LEASE_SECONDS)

    result = {
        "considered": 0, "dispatched": 0, "failed": 0,
        "no_handler": 0, "bad_cadence": 0, "skipped": 0,
    }
    candidate_ids = [
        row_id
        for (row_id,) in db.query(ScheduledRun.id)
        .filter(*_due_filter(now, horizon, stale_before))
        .order_by(ScheduledRun.next_run_at.asc())
        .limit(limit)
        .all()
    ]
    result["considered"] = len(candidate_ids)

    for run_id in candidate_ids:
        if not _claim(db, run_id, now, horizon, stale_before):
            result["skipped"] += 1
            continue
        run = db.get(ScheduledRun, run_id)
        if run is None:  # deleted between select and claim
            result["skipped"] += 1
            continue
        _dispatch_one(db, run, now, result)

    if result["considered"]:
        logger.info("scheduler: tick %s", result)
    return result


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def status(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """What ``GET /health/scheduler`` reports: configuration, the kinds this
    process can dispatch, and row counts. ``last_run_at`` is the newest
    dispatch across all rows, which is the cheapest liveness signal once
    anything is scheduled."""
    now = _naive_utc(now or utcnow())
    stale_before = now - timedelta(seconds=settings.SCHEDULER_LEASE_SECONDS)
    total = db.query(func.count(ScheduledRun.id)).scalar() or 0
    enabled = (
        db.query(func.count(ScheduledRun.id)).filter(ScheduledRun.enabled.is_(True)).scalar() or 0
    )
    due = (
        db.query(func.count(ScheduledRun.id))
        .filter(*_due_filter(now, now, stale_before))
        .scalar()
        or 0
    )
    claimed = (
        db.query(func.count(ScheduledRun.id))
        .filter(ScheduledRun.claimed_at.isnot(None), ScheduledRun.claimed_at >= stale_before)
        .scalar()
        or 0
    )
    last_run_at = db.query(func.max(ScheduledRun.last_run_at)).scalar()
    return {
        "enabled": bool(settings.SCHEDULER_ENABLED),
        "tick_seconds": settings.SCHEDULER_TICK_SECONDS,
        "lease_seconds": settings.SCHEDULER_LEASE_SECONDS,
        "grace_seconds": settings.SCHEDULER_GRACE_SECONDS,
        "kinds": registered_kinds(),
        "rows": {"total": total, "enabled": enabled, "due": due, "claimed": claimed},
        "last_run_at": last_run_at.isoformat() + "Z" if last_run_at else None,
    }

"""S-8.3.1 — the beat entry and the tick task are WIRED.

The service tests prove the tick logic; these prove the pieces that would
silently make the feature dead if unplugged: the beat schedule names the
task, Celery can resolve that task name, and the task hands a session to
the service only when the scheduler is enabled.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import settings
from app.tasks import scheduler_tasks
from app.tasks.celery_app import _beat_schedule, celery_app


def test_beat_schedule_names_the_tick_task():
    entry = celery_app.conf.beat_schedule["scheduler-tick"]
    assert entry["task"] == scheduler_tasks.TICK_TASK_NAME == "scheduler.tick"
    assert entry["schedule"] == float(settings.SCHEDULER_TICK_SECONDS)
    # System work: never a tenant's tier queue. A tick that sat unconsumed
    # for a full interval expires instead of replaying after a restart.
    assert entry["options"]["queue"] == "default"
    assert entry["options"]["expires"] == settings.SCHEDULER_TICK_SECONDS


def test_beat_schedule_is_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
    assert _beat_schedule() == {}


def test_tick_task_is_registered_under_its_beat_name():
    # Importing the module registers the task; autodiscover does the same
    # in the worker via related_name="scheduler_tasks".
    assert "scheduler.tick" in celery_app.tasks
    # `scheduler_tick` is a Celery Proxy; compare by identity of the target.
    assert celery_app.tasks["scheduler.tick"] == scheduler_tasks.scheduler_tick


def test_tick_task_opens_a_session_and_runs_the_service():
    fake_db = MagicMock()
    with (
        patch.object(scheduler_tasks, "SessionLocal", return_value=fake_db) as session_factory,
        patch.object(scheduler_tasks.scheduler_service, "run_tick", return_value={"dispatched": 2}) as run,
    ):
        out = scheduler_tasks.scheduler_tick.run()
    session_factory.assert_called_once_with()
    run.assert_called_once_with(fake_db)
    fake_db.close.assert_called_once()
    assert out == {"dispatched": 2}


def test_tick_task_noops_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
    with (
        patch.object(scheduler_tasks, "SessionLocal") as session_factory,
        patch.object(scheduler_tasks.scheduler_service, "run_tick") as run,
    ):
        out = scheduler_tasks.scheduler_tick.run()
    session_factory.assert_not_called()
    run.assert_not_called()
    assert out == {"skipped": "disabled"}

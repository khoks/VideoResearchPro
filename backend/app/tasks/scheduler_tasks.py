"""``scheduler.tick`` — the one Celery beat entry (S-8.3.1 / M3).

Beat fires this every ``SCHEDULER_TICK_SECONDS`` on the ``default`` queue
(it is system work, not any tenant's). The task opens a session, hands it
to ``scheduler_service.run_tick`` and closes it. All the logic — due
selection, the claim lease, per-kind dispatch through the tier queues,
``next_run_at`` arithmetic — lives in the service so it is testable
without a broker.

Kinds register from the task module that defines their task, e.g.::

    from app.services import scheduler_service
    @celery_app.task(name="saved_search.run")
    def run_saved_search(target_id, scheduled_run_id=None): ...
    scheduler_service.register_kind("saved_search", run_saved_search)

Celery's ``autodiscover_tasks`` must import that module (see
``celery_app.py``) or this worker reports the kind as ``no_handler``.

Run exactly one beat process: ``scripts/start.ps1`` and
``scripts/restart_services.ps1`` do. A second beat doubles the tick load;
the row lease keeps it from double-dispatching, but it is still wrong.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.database import SessionLocal
from app.services import scheduler_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

TICK_TASK_NAME = "scheduler.tick"


@celery_app.task(name=TICK_TASK_NAME, ignore_result=True)
def scheduler_tick() -> dict:
    """Claim and dispatch every due ``scheduled_runs`` row."""
    if not settings.SCHEDULER_ENABLED:
        logger.debug("scheduler: tick skipped (SCHEDULER_ENABLED is false)")
        return {"skipped": "disabled"}

    db = SessionLocal()
    try:
        return scheduler_service.run_tick(db)
    finally:
        db.close()

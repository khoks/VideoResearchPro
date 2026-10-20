"""``echo.sync_connector`` — one sync of one Echo connector grant (S-3.2.1).

The scheduler tick dispatches it for every due ``scheduled_runs`` row of kind
``echo_sync`` (target: the grant id); connecting and "Sync now" dispatch it
too. The work is ``echo_connector_service.run_sync``, which is idempotent and
fail-soft. Registering the kind here is what lets a worker that imports this
module dispatch it (D-077); ``celery_app`` autodiscovers this module.
"""
from __future__ import annotations

import logging

from app.connectors import registry
from app.database import SessionLocal
from app.services import echo_connector_service, scheduler_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_NAME = "echo.sync_connector"


@celery_app.task(name=TASK_NAME, ignore_result=True)
def sync_echo_connector(target_id: str, scheduled_run_id: str | None = None, trigger: str = "schedule") -> str:
    registry.load_builtin()
    db = SessionLocal()
    try:
        outcome = echo_connector_service.run_sync(db, target_id)
        logger.info("echo sync %s (%s): %s", target_id[:8], trigger, outcome.status)
        return outcome.status
    finally:
        db.close()


scheduler_service.register_kind(echo_connector_service.KIND, sync_echo_connector)

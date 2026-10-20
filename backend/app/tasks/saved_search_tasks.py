"""``saved_search.run`` — one run of a saved search (S-8.3.2 / M3).

The scheduler tick dispatches this for every due ``scheduled_runs`` row of
kind ``saved_search``; "Run now" dispatches it too. The work is in
``saved_search_service.execute``. Registering the kind here is what lets a
worker that imports this module dispatch it: ``celery_app`` autodiscovers
this module, and without that import the tick records ``no_handler``.
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.services import saved_search_service, scheduler_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_NAME = "saved_search.run"


@celery_app.task(name=TASK_NAME, ignore_result=True)
def run_saved_search(target_id: str, scheduled_run_id: str | None = None, trigger: str = "schedule") -> dict:
    db = SessionLocal()
    try:
        result = saved_search_service.execute(db, target_id, trigger=trigger)
        logger.info("saved search %s (%s): %s", target_id, trigger, result.get("status"))
        return result
    finally:
        db.close()


scheduler_service.register_kind(saved_search_service.KIND, run_saved_search)

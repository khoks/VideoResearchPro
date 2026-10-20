"""Echo's Celery tasks.

- ``echo.process_share`` — process one Echo share (S-3.7.2). Queued after
  every share is created and by "Retry" in the inbox. The work is in
  ``echo_processing_service.process_share``; it is idempotent and fail-soft.
- ``echo.extract_signals`` — one signal-extraction run for a tenant
  (S-3.3.2), queued by ``echo_signal_extraction.maybe_queue``.
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.services import echo_processing_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_NAME = "echo.process_share"
EXTRACT_SIGNALS_TASK = "echo.extract_signals"


@celery_app.task(name=TASK_NAME, ignore_result=True)
def process_share_task(share_id: str) -> str:
    db = SessionLocal()
    try:
        return echo_processing_service.process_share(db, share_id).state
    finally:
        db.close()


@celery_app.task(name=EXTRACT_SIGNALS_TASK, ignore_result=True)
def extract_signals_task(tenant_id: str) -> dict:
    """One run; a second run queued while one is going reads what the first
    left pending. Runs are serial per worker (``--pool=solo`` on Windows)."""
    from app.services import echo_signal_extraction

    db = SessionLocal()
    try:
        return echo_signal_extraction.run(db, tenant_id).to_dict()
    finally:
        db.close()

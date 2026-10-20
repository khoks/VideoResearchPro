"""``echo.process_share`` — process one Echo share (S-3.7.2).

Queued after every share is created and by "Retry" in the inbox. The work is
in ``echo_processing_service.process_share``; it is idempotent and fail-soft.
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.services import echo_processing_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_NAME = "echo.process_share"


@celery_app.task(name=TASK_NAME, ignore_result=True)
def process_share_task(share_id: str) -> str:
    db = SessionLocal()
    try:
        return echo_processing_service.process_share(db, share_id).state
    finally:
        db.close()

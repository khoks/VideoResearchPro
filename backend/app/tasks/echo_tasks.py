"""Echo's Celery tasks.

- ``echo.process_share`` — process one Echo share (S-3.7.2). Queued after
  every share is created and by "Retry" in the inbox. The work is in
  ``echo_processing_service.process_share``; it is idempotent and fail-soft.
- ``echo.extract_signals`` — one signal-extraction run for a tenant
  (S-3.3.2), queued by ``echo_signal_extraction.maybe_queue``.
- ``echo.generate_voice_test`` — write the pairs of a voice test the user
  started on the Echo page (T-3.4.1.8): about 40 draft-model calls.
- ``echo.poll_imap`` — one poll of the email inbox (T-3.7.4.1). The scheduler
  tick dispatches it for the ``echo_imap`` row; registering the kind here is
  what lets a worker dispatch it (D-077).
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.services import echo_imap_service, echo_processing_service, scheduler_service
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


EMBED_IMPORT_TASK_NAME = "echo.embed_import"


@celery_app.task(name=EMBED_IMPORT_TASK_NAME, ignore_result=True)
def embed_import_task(import_id: str) -> str:
    """Embed an export import's shares (S-3.7.5), a batch at a time; resumable."""
    from app.services import echo_import_service

    db = SessionLocal()
    try:
        return echo_import_service.embed_import(db, import_id)
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


POLL_IMAP_TASK = "echo.poll_imap"


@celery_app.task(name=POLL_IMAP_TASK, ignore_result=True)
def poll_imap_task(target_id: str, scheduled_run_id: str | None = None) -> str:
    """One poll. Fail-soft: a mailbox that cannot be reached logs and waits
    for the next tick."""
    db = SessionLocal()
    try:
        return echo_imap_service.poll(db).status
    finally:
        db.close()


scheduler_service.register_kind(echo_imap_service.KIND, poll_imap_task)


GENERATE_VOICE_TEST_TASK = "echo.generate_voice_test"


@celery_app.task(name=GENERATE_VOICE_TEST_TASK, ignore_result=True)
def generate_voice_test_task(test_id: str) -> str:
    """Write one voice test's pairs. Fail-soft: an error marks the test
    failed, in words, and the user may start another."""
    from app.services import echo_voice_test_service

    db = SessionLocal()
    try:
        row = echo_voice_test_service.generate(db, test_id)
        return row.status if row is not None else "missing"
    finally:
        db.close()

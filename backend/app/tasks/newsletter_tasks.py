"""``newsletter.issue`` — one issue of a reader's digest (S-6.4.2 / E-6.4).

The scheduler tick dispatches this for every due ``scheduled_runs`` row of
kind ``newsletter``, passing the slot it was due at, which decides the
period the issue belongs to; "Send now" dispatches it with
``trigger="manual"``. The work is in ``newsletter_service.deliver``.
Registering the kind here is what lets a worker that imports this module
dispatch it (``celery_app`` autodiscovers it); without it the tick records
``no_handler``, as for saved searches (T-8.3.2.5).
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.database import SessionLocal
from app.services import newsletter_service, scheduler_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_NAME = "newsletter.issue"


@celery_app.task(name=TASK_NAME, ignore_result=True)
def issue_newsletter(subscription_id: str, scheduled_run_id: str | None = None, slot: str | None = None,
                     trigger: str = "schedule") -> dict:
    import app.services.outputters  # noqa: F401 — registers the newsletter outputter in this worker

    db = SessionLocal()
    try:
        when = datetime.fromisoformat(slot) if slot else None
        result = newsletter_service.deliver(db, subscription_id, slot=when, trigger=trigger)
        logger.info("newsletter %s (%s): %s", subscription_id, trigger, result.get("status"))
        return result
    finally:
        db.close()


def _args_for(run) -> tuple[list, dict]:
    # The slot the row was due at, before the tick advances it: the period key.
    return [run.target_id], {"scheduled_run_id": run.id, "slot": run.next_run_at.isoformat()}


scheduler_service.register_kind(newsletter_service.KIND, issue_newsletter, args_for=_args_for)

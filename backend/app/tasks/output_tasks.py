"""``generate_output`` — Author Studio generation in the worker (S-6.7.1).

`POST /author/outputs` writes a `pending` row and dispatches this task on
the owner's tier queue (`task_routing_service.dispatch_for_user`). The task
loads the row and its owner and hands both to
``output_service.run_generation``, which owns the lifecycle, the progress
published on `job_progress:{output_id}`, and cooperative cancellation.

No automatic retries: a generation that failed has already recorded why on
the row, and a retry would publish a confusing second `generating`. The
user regenerates from the Author page.
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models.output import Output
from app.models.user import User
from app.services import output_service
from app.services import outputters  # noqa: F401  (registers every outputter)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="author.generate_output", ignore_result=True)
def generate_output(self, output_id: str) -> str | None:
    """Generate one output. Returns its final status (for logs and tests)."""
    db = SessionLocal()
    try:
        output = db.get(Output, output_id)
        if output is None:
            logger.warning("generate_output: output %s not found (deleted before it ran?)", output_id)
            return None
        user = db.get(User, output.user_id)
        if user is None:
            output_service.transition_to(
                db, output, output_service.OutputStatus.FAILED,
                error_message="The output's owner no longer exists.", progress_message="Failed",
            )
            return output.status
        if output.status in output_service.TERMINAL_STATUSES:
            logger.info("generate_output: output %s already %s; skipping", output_id, output.status)
            return output.status
        if self.request.id and output.celery_task_id != self.request.id:
            # Dispatched before the router recorded the id, or re-delivered.
            output.celery_task_id = self.request.id
            db.commit()
        result = output_service.run_generation(db, user, output)
        return result.status
    finally:
        db.close()

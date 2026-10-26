import logging
import sys

from celery import Celery
from celery.signals import worker_process_init, worker_ready

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "videoresearchpro",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


def _beat_schedule() -> dict:
    """The single static beat entry (S-8.3.1 / M3).

    Everything that runs on a schedule — saved searches, the newsletter,
    Echo syncs — is a ROW in `scheduled_runs`, not a beat entry. Beat only
    fires `scheduler.tick`, which reads the rows. Keeping beat static means
    the schedule state lives in SQLite with the rest of the data and no
    Redis-backed beat store is needed.

    `expires` drops a tick that sat unconsumed for a whole interval (the
    worker was down), so a restart does not replay a backlog of ticks: one
    tick after restart catches up every due row anyway.
    """
    if not settings.SCHEDULER_ENABLED:
        return {}
    return {
        "scheduler-tick": {
            "task": "scheduler.tick",
            "schedule": float(settings.SCHEDULER_TICK_SECONDS),
            "options": {
                "queue": "default",
                "expires": settings.SCHEDULER_TICK_SECONDS,
            },
        }
    }


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_concurrency=settings.MAX_CONCURRENT_JOBS,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # T-5.6.5: per-tier task queues. Default queue handles unattributed
    # tasks; tier_free / tier_pro / tier_studio receive user-initiated
    # work routed via app/services/task_routing_service.dispatch_for_user.
    # Self-host workers should consume all queues:
    #   celery -A app.tasks.celery_app worker -Q default,tier_free,tier_pro,tier_studio
    # SaaS deployments can split worker pools per queue.
    task_default_queue="default",
    # S-8.3.1: run by exactly one `celery -A app.tasks.celery_app beat`
    # process (scripts/start.ps1 starts it). Two beats double the tick
    # load; the row lease prevents double dispatch but not the waste.
    beat_schedule=_beat_schedule(),
)

celery_app.autodiscover_tasks(["app.tasks"], related_name="job_tasks")
# S-8.3.1: the scheduler tick (and, later, each scheduled kind's task module)
# lives apart from job orchestration so the beat entry and the kind registry
# are greppable on their own. Each `related_name` is one module to import.
celery_app.autodiscover_tasks(["app.tasks"], related_name="scheduler_tasks")
# S-6.7.1: Author Studio generation runs in the worker.
celery_app.autodiscover_tasks(["app.tasks"], related_name="output_tasks")
# S-8.3.2: registers the `saved_search` scheduler kind on import. Without
# this the tick records `no_handler` and a saved search never runs.
celery_app.autodiscover_tasks(["app.tasks"], related_name="saved_search_tasks")
# S-6.4.2: registers the `newsletter` scheduler kind (T-6.4.2.4).
celery_app.autodiscover_tasks(["app.tasks"], related_name="newsletter_tasks")
# S-3.7.2: Echo share processing, one task per share.
celery_app.autodiscover_tasks(["app.tasks"], related_name="echo_tasks")
# S-3.2.1: Echo connector syncs; registers the `echo_sync` scheduler kind on
# import (D-077), so without this the tick records `no_handler`.
celery_app.autodiscover_tasks(["app.tasks"], related_name="echo_connector_tasks")
# S-1.18.2: on-demand frame capture for one document.
celery_app.autodiscover_tasks(["app.tasks"], related_name="visual_tasks")


@celery_app.task(name="chroma.backfill_qa_library", ignore_result=True)
def backfill_qa_library_task() -> int:
    """The Q&A library backfill as a task, queued by ``run_startup_backfills``.

    Defined here rather than in an autodiscovered module so every process
    that loads the Celery app, a prefork child included, knows the task.
    """
    from app.services import chroma_service

    return chroma_service.backfill_qa_library()


@worker_ready.connect
def run_startup_backfills(**_kwargs) -> None:
    """The API lifespan's Chroma backfills, on worker start too (S-5.10.5).

    The worker retrieves and writes as well: a saved-search run is a library
    Q&A over the global collection and upserts its exchange into the Q&A
    library. While the backfills ran only in the API lifespan, an upgrade
    that started the worker alone left chunks embedded before 2026-10-19
    without the ``document_id`` that retrieval filters on (D-070), so they
    were unretrievable until the API booted once.

    The chunk backfill runs here, synchronously: Celery sends
    ``worker_ready`` just before the consumer loop starts, so no task
    retrieves from un-stamped chunks. It is a metadata scan, nothing is
    re-embedded. The Q&A library backfill re-embeds every exchange on every
    run and nothing waits on it, so it is queued as a task instead: it no
    longer holds the consumer loop for a time that grows with the history,
    and on a prefork pool it runs in a child, not here.

    Then the Chroma client and the model the chunk backfill opened are
    closed, because this is the process a prefork pool forks its
    replacement children from (after a revoke with ``terminate``, a crash,
    an OOM kill), and neither survives a fork. On the solo pool the first
    task that needs them opens them again.

    Both backfills are idempotent (upsert on fixed ids; stamped chunks are
    skipped), so the API and every worker running them is safe, and a
    failure is logged and never stops the worker. Beat and the API import
    this module but never send the signal.
    """
    # Imported at call time so importing the Celery configuration never
    # loads chromadb by itself (autodiscovery above is lazy too).
    from app.services import chroma_service

    try:
        chroma_service.backfill_chunk_document_ids()
    except Exception:
        logger.exception("Chunk document_id backfill failed; worker continues")
    finally:
        chroma_service.close_client()

    try:
        backfill_qa_library_task.delay()
    except Exception:
        logger.exception("Could not queue the Q&A library backfill; worker continues")


@worker_process_init.connect
def forget_inherited_chroma(**_kwargs) -> None:
    """A prefork child never uses the Chroma client or model of the process
    it was forked from (S-5.10.5): see ``chroma_service.forget_inherited_client``.

    Nothing to forget unless this process has the module loaded, so a child
    never imports chromadb just to start.
    """
    chroma_service = sys.modules.get("app.services.chroma_service")
    if chroma_service is not None:
        chroma_service.forget_inherited_client()

from celery import Celery

from app.config import settings

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

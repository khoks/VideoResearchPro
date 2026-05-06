from celery import Celery

from app.config import settings

celery_app = Celery(
    "videoresearchpro",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

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
)

celery_app.autodiscover_tasks(["app.tasks"], related_name="job_tasks")

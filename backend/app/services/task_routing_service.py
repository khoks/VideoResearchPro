"""Per-tenant Celery task routing — T-5.6.5.

Foundation for SaaS multi-tenant Celery deployment. Picks a queue
name based on the dispatching user's tier so heavy Free-tier workloads
can't starve Studio-tier workers (and vice versa, if SaaS needs to
guarantee Studio users don't wait behind a Free-tier backlog).

Self-host posture (today):
- One worker, default config, all queues delivered to it. The queue
  attribution still happens at dispatch time, so logs / inspectors
  show which tier each task came from.

SaaS posture (when E-5.8 ships):
- Multiple worker pools, each consuming a subset of queues. Studio
  users hit a low-latency pool; Free users hit a backlog-tolerant
  pool. Configure via the worker launch:
    celery -A app.tasks.celery_app worker -Q tier_studio,tier_pro
    celery -A app.tasks.celery_app worker -Q tier_free,default

Queue names:
- ``default`` — fallback for unattributed tasks (background reaping,
  startup migrations, etc.).
- ``tier_free`` — Free-tier user-initiated tasks.
- ``tier_pro`` — Pro-tier.
- ``tier_studio`` — Studio-tier.

The function ``queue_for_user(user)`` is the single source of truth
for the mapping; dispatch sites call ``dispatch_for_user(task, user,
*args, **kwargs)`` which forwards to ``task.apply_async`` with the
right ``queue=``.
"""
from __future__ import annotations

import logging
from typing import Any

from app.models.user import User
from app.services.tier_service import Tier, get_user_tier

logger = logging.getLogger(__name__)


# Tier → queue name. The keys must align with `Tier` enum values; the
# values are arbitrary strings as long as they're consistent across
# dispatchers and worker config.
_QUEUE_BY_TIER: dict[Tier, str] = {
    Tier.FREE: "tier_free",
    Tier.PRO: "tier_pro",
    Tier.STUDIO: "tier_studio",
}

# Fallback for tasks that don't have a user context (startup migrations,
# scheduled cleanup, etc.). Workers should always include this in their
# `-Q` list so anonymous tasks get processed.
DEFAULT_QUEUE = "default"


def queue_for_user(user: User | None) -> str:
    """Resolve the queue name for a user-initiated task. Returns
    ``DEFAULT_QUEUE`` when user is None (system tasks)."""
    if user is None:
        return DEFAULT_QUEUE
    tier = get_user_tier(user)
    return _QUEUE_BY_TIER.get(tier, DEFAULT_QUEUE)


def queue_for_tier(tier: Tier) -> str:
    """Resolve the queue name from a Tier enum directly. Used by
    Celery tasks that have a tenant_id but not a User row."""
    return _QUEUE_BY_TIER.get(tier, DEFAULT_QUEUE)


def queue_for_tenant_id(db: Any, tenant_id: str | None) -> str:
    """Resolve the queue name from a tenant_id by looking up the user.
    Used by tasks that need to chain another task as the same user
    (e.g. resume-after-approval). Falls back to DEFAULT_QUEUE on
    lookup failure — never blocks dispatch."""
    if tenant_id is None or db is None:
        return DEFAULT_QUEUE
    try:
        from app.services import auth_service

        user = auth_service.get_user_by_id(db, tenant_id)
        return queue_for_user(user)
    except Exception:
        logger.exception(
            "queue_for_tenant_id: lookup failed tenant_id=%s — using default queue",
            tenant_id,
        )
        return DEFAULT_QUEUE


def dispatch_for_user(
    task: Any,
    user: User | None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Dispatch ``task`` (a Celery task object) on the queue
    appropriate for ``user``. Returns the AsyncResult.

    Equivalent to ``task.apply_async(args=args, kwargs=kwargs,
    queue=queue_for_user(user))`` but a thin wrapper makes the
    dispatch sites easier to read and easier to grep for.
    """
    queue = queue_for_user(user)
    logger.info(
        "task_routing: dispatch task=%s queue=%s user=%s",
        getattr(task, "name", task),
        queue,
        user.id if user is not None else "<system>",
    )
    return task.apply_async(args=list(args), kwargs=kwargs, queue=queue)


def dispatch_for_tenant_id(
    task: Any,
    db: Any,
    tenant_id: str | None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Dispatch ``task`` on the queue appropriate for a tenant_id.
    Looks up the User to resolve tier; falls back to DEFAULT_QUEUE
    on lookup failure. Useful for tasks that chain other tasks (e.g.
    resume-after-approval reads ``job.tenant_id``)."""
    queue = queue_for_tenant_id(db, tenant_id)
    logger.info(
        "task_routing: dispatch task=%s queue=%s tenant_id=%s",
        getattr(task, "name", task),
        queue,
        tenant_id or "<system>",
    )
    return task.apply_async(args=list(args), kwargs=kwargs, queue=queue)


def supported_queues() -> list[str]:
    """Return every queue name dispatched on. Worker startup MUST
    include this list in its ``-Q`` argument (or accept all via no
    ``-Q``) — otherwise tasks will sit in unattended queues."""
    return sorted({DEFAULT_QUEUE, *_QUEUE_BY_TIER.values()})

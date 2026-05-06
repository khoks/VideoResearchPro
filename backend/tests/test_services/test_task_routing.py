"""Tests for T-5.6.5 — per-tenant Celery queue routing."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import auth_service
from app.services.task_routing_service import (
    DEFAULT_QUEUE,
    dispatch_for_tenant_id,
    dispatch_for_user,
    queue_for_tenant_id,
    queue_for_tier,
    queue_for_user,
    supported_queues,
)
from app.services.tier_service import Tier


# ---------------------------------------------------------------------------
# queue_for_user / queue_for_tier
# ---------------------------------------------------------------------------


def test_queue_for_user_resolves_per_tier(db):
    free_user = auth_service.create_user(db, email="rf@x.com", password="pw" * 6)
    pro_user = auth_service.create_user(db, email="rp@x.com", password="pw" * 6)
    studio_user = auth_service.create_user(db, email="rs@x.com", password="pw" * 6)
    pro_user.tier = "pro"
    studio_user.tier = "studio"
    db.commit()

    assert queue_for_user(free_user) == "tier_free"
    assert queue_for_user(pro_user) == "tier_pro"
    assert queue_for_user(studio_user) == "tier_studio"


def test_queue_for_user_none_returns_default():
    assert queue_for_user(None) == DEFAULT_QUEUE


def test_queue_for_tier_returns_correct_queue():
    assert queue_for_tier(Tier.FREE) == "tier_free"
    assert queue_for_tier(Tier.PRO) == "tier_pro"
    assert queue_for_tier(Tier.STUDIO) == "tier_studio"


def test_queue_for_tenant_id_resolves_via_user_lookup(db):
    user = auth_service.create_user(db, email="rt@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()

    assert queue_for_tenant_id(db, user.id) == "tier_studio"
    # Unknown tenant_id → default (don't block dispatch).
    assert queue_for_tenant_id(db, "no-such-user") == DEFAULT_QUEUE
    # None → default.
    assert queue_for_tenant_id(db, None) == DEFAULT_QUEUE


# ---------------------------------------------------------------------------
# dispatch_for_user
# ---------------------------------------------------------------------------


def test_dispatch_for_user_calls_apply_async_with_correct_queue(db):
    user = auth_service.create_user(db, email="d1@x.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()

    fake_task = MagicMock()
    fake_task.name = "fake_task"
    fake_task.apply_async = MagicMock(return_value=MagicMock(id="task-123"))

    result = dispatch_for_user(fake_task, user, "arg1", kwarg1="value1")

    fake_task.apply_async.assert_called_once_with(
        args=["arg1"], kwargs={"kwarg1": "value1"}, queue="tier_pro"
    )
    assert result.id == "task-123"


def test_dispatch_for_user_with_none_routes_to_default(db):
    fake_task = MagicMock()
    fake_task.name = "fake_task"
    fake_task.apply_async = MagicMock(return_value=MagicMock(id="task-456"))

    dispatch_for_user(fake_task, None, "arg")
    fake_task.apply_async.assert_called_once_with(
        args=["arg"], kwargs={}, queue=DEFAULT_QUEUE
    )


def test_dispatch_for_tenant_id_resolves_and_routes(db):
    user = auth_service.create_user(db, email="d2@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()

    fake_task = MagicMock()
    fake_task.name = "fake_task"
    fake_task.apply_async = MagicMock(return_value=MagicMock(id="task-789"))

    dispatch_for_tenant_id(fake_task, db, user.id, "job-xyz")
    fake_task.apply_async.assert_called_once_with(
        args=["job-xyz"], kwargs={}, queue="tier_studio"
    )


# ---------------------------------------------------------------------------
# Supported-queues sanity
# ---------------------------------------------------------------------------


def test_supported_queues_includes_all_tier_queues_plus_default():
    qs = set(supported_queues())
    assert qs == {"default", "tier_free", "tier_pro", "tier_studio"}


# ---------------------------------------------------------------------------
# Router integration — job creation routes to the requesting user's tier
# ---------------------------------------------------------------------------


def test_create_topic_job_dispatches_to_tier_queue(client, db, test_user, monkeypatch):
    """The job-creation router uses dispatch_for_user; the captured
    queue argument matches the test_user's tier (Free by default)."""
    # The conftest already mocks `execute_topic_job.delay` to a MagicMock.
    # We additionally mock `apply_async` so we can inspect the queue arg.
    captured: dict = {}

    def fake_apply_async(args=None, kwargs=None, queue=None):
        captured["queue"] = queue
        m = MagicMock()
        m.id = "test-task-id"
        return m

    # Re-target the patched task in the conftest so apply_async is captured.
    from app.routers import jobs as jobs_router_module

    monkeypatch.setattr(
        jobs_router_module.execute_topic_job, "apply_async", fake_apply_async
    )

    r = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "topic",
            "topic": "test topic",
            "search_instructions": "test",
            "num_videos": 5,
        },
    )
    assert r.status_code == 201
    assert captured["queue"] == "tier_free"


def test_create_topic_job_studio_user_dispatches_to_studio_queue(
    client, db, test_user, monkeypatch
):
    """Upgrade test_user to Studio mid-test, dispatch, observe routing."""
    test_user.tier = "studio"
    db.commit()

    captured: dict = {}

    def fake_apply_async(args=None, kwargs=None, queue=None):
        captured["queue"] = queue
        m = MagicMock()
        m.id = "test-task-id"
        return m

    from app.routers import jobs as jobs_router_module
    monkeypatch.setattr(
        jobs_router_module.execute_topic_job, "apply_async", fake_apply_async
    )

    r = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "topic",
            "topic": "x",
            "search_instructions": "x",
            "num_videos": 5,
        },
    )
    assert r.status_code == 201
    assert captured["queue"] == "tier_studio"

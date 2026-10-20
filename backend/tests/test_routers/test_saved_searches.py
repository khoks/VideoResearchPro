"""S-8.3.2: saved searches — REST, the run, and the scheduler wiring.

The run is exercised through ``saved_search_service.execute`` with a fake
agent (no provider is called); the wiring tests prove the tick reaches the
task and that a worker's autodiscovery registers the ``saved_search`` kind,
which is the failure the board filed as T-8.3.2.5.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.quota_usage import QuotaUsage
from app.models.saved_search import SavedSearch
from app.models.scheduled_run import ScheduledRun
from app.services import (
    auth_service,
    saved_search_service,
    scheduler_service,
    shelf_service,
    visibility_service,
)
from app.services.tier_service import TIER_CAPABILITIES, Tier

URL = "/api/v1/saved-searches"
WEEKLY = {"cadence": "weekly", "hour": 9, "weekday": 0, "timezone": "Europe/London"}


@pytest.fixture
def pro(db, test_user):
    test_user.tier = "pro"
    db.commit()
    return test_user


def _create(client, **over):
    body = {"question": "What do my sources say about rate cuts?", "cadence": WEEKLY, **over}
    return client.post(URL, json=body)


def _doc(db, tenant_id, title):
    doc = Document(video_id=os.urandom(5).hex()[:11], title=title, url="https://example.com", transcript_status="completed")
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], tenant_id, "job")
    return doc


class FakeAgent:
    def __init__(self, answer="Rates fell twice.", refs=("vidB", "vidA", "vidA"), fail=False):
        self.answer, self.refs, self.fail = answer, refs, fail
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider down")
        return {"answer": self.answer, "references": [{"video_id": r, "video_title": r} for r in self.refs]}


@pytest.fixture(autouse=True)
def _no_chroma():
    with patch("app.services.chroma_service.upsert_qa_exchange") as up:
        yield up


# ---------------------------------------------------------------- gate + CRUD


def test_free_tier_has_no_saved_searches(client):
    assert client.get(URL).status_code == 403
    assert _create(client).status_code == 403


def test_create_schedules_one_row_and_lists_it(client, db, pro):
    r = _create(client)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["cadence"] == {"cadence": "weekly", "hour": 9, "minute": 0, "weekday": 0, "timezone": "Europe/London"}
    assert data["enabled"] is True and data["next_run_at"]
    row = db.query(ScheduledRun).filter_by(kind="saved_search", target_id=data["id"]).one()
    assert row.tenant_id == pro.id and row.enabled
    listing = client.get(URL).json()
    assert [i["id"] for i in listing["items"]] == [data["id"]]
    assert listing["active"] == 1 and listing["cap"] == 10


@pytest.mark.parametrize(
    "body",
    [
        {"cadence": {"cadence": "every", "seconds": 3600}},
        {"cadence": {"cadence": "daily", "hour": 9, "timezone": "Mars/Olympus"}},
        {"cadence": {"cadence": "weekly", "hour": 9}},
        {"cadence": {"cadence": "monthly", "hour": 9, "day_of_month": 31}},
        {"question": "hi"},
        {"surprise": True},
        {"scope": {"job_id": "x"}},
    ],
)
def test_bad_requests_are_422(client, pro, body):
    assert _create(client, **body).status_code == 422


def test_scope_must_be_your_own_shelf(client, db, pro):
    mine = shelf_service.create_shelf(db, pro.id, name="Macro")
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    theirs = shelf_service.create_shelf(db, other.id, name="Theirs")
    assert _create(client, scope={"shelf_id": mine.id}).json()["scope"] == {"shelf_id": mine.id}
    assert _create(client, scope={"shelf_id": theirs.id}).status_code == 404


def test_the_active_cap_counts_enabled_rows(client, pro, monkeypatch):
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.PRO], "saved_searches_active_cap", 2)
    a = _create(client).json()
    _create(client)
    assert _create(client).status_code == 409
    assert client.patch(f"{URL}/{a['id']}", json={"enabled": False}).status_code == 200
    third = _create(client)
    assert third.status_code == 201
    assert client.patch(f"{URL}/{a['id']}", json={"enabled": True}).status_code == 409


def test_pause_cadence_change_and_delete_keep_the_schedule_in_step(client, db, pro):
    ss = _create(client).json()
    paused = client.patch(f"{URL}/{ss['id']}", json={"enabled": False}).json()
    assert paused["enabled"] is False and paused["next_run_at"] is None
    assert db.query(ScheduledRun).filter_by(target_id=ss["id"]).one().enabled is False
    moved = client.patch(f"{URL}/{ss['id']}", json={"enabled": True, "cadence": {"cadence": "daily", "hour": 7}}).json()
    assert moved["cadence"]["cadence"] == "daily" and moved["next_run_at"]
    db.expire_all()
    assert db.query(ScheduledRun).filter_by(target_id=ss["id"]).one().enabled is True
    assert client.delete(f"{URL}/{ss['id']}").status_code == 204
    assert db.query(ScheduledRun).filter_by(target_id=ss["id"]).count() == 0
    assert client.get(f"{URL}/{ss['id']}").status_code == 404


def test_another_tenants_saved_search_is_invisible(client, db, pro):
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    other.tier = "pro"
    db.commit()
    theirs = saved_search_service.create(db, other, question="Their question here", cadence=WEEKLY)
    assert client.get(URL).json()["items"] == []
    for method, path in (("get", ""), ("patch", ""), ("delete", ""), ("post", "/run-now")):
        r = getattr(client, method)(f"{URL}/{theirs.id}{path}", **({"json": {}} if method == "patch" else {}))
        assert r.status_code == 404, (method, path)


def test_run_now_queues_on_the_tenants_queue_and_respects_the_quota(client, db, pro):
    ss = _create(client).json()
    with patch("app.routers.saved_searches.task_routing_service.dispatch_for_user") as dispatch:
        r = client.post(f"{URL}/{ss['id']}/run-now")
    assert r.status_code == 202 and r.json() == {"status": "queued"}
    task, user, target = dispatch.call_args.args[:3]
    assert task.name == "saved_search.run" and user.id == pro.id and target == ss["id"]
    assert dispatch.call_args.kwargs == {"trigger": "manual"}
    from app.services.quota_metering_service import QuotaExceededError

    with patch(
        "app.routers.saved_searches.quota_metering_service.enforce_quota_or_raise",
        side_effect=QuotaExceededError(resource="library_qa_exchanges", consumed=1, limit=1, retry_at=None),
    ), patch("app.routers.saved_searches.task_routing_service.dispatch_for_user") as dispatch:
        assert client.post(f"{URL}/{ss['id']}/run-now").status_code == 429
        dispatch.assert_not_called()


# ---------------------------------------------------------------- the run


def _saved(db, user, **over):
    return saved_search_service.create(db, user, question="What do my sources say about rate cuts?", cadence=WEEKLY, **over)


def test_a_run_asks_over_the_visible_set_and_stores_the_baseline(db, pro, _no_chroma):
    mine = _doc(db, pro.id, "Mine")
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    _doc(db, other.id, "Theirs")
    ss = _saved(db, pro)
    agent = FakeAgent()
    out = saved_search_service.execute(db, ss.id, agent=agent)
    assert out["status"] == "ok"
    assert agent.calls[0]["visible_document_ids"] == [mine.document_id]
    assert agent.calls[0]["question"] == ss.question
    db.refresh(ss)
    assert ss.last_status == "ok" and ss.last_exchange_id == out["exchange_id"]
    assert json.loads(ss.last_reference_ids_json) == ["vidA", "vidB"]
    assert len(ss.last_answer_hash) == 64
    exchange = db.get(LibraryQAExchange, out["exchange_id"])
    assert exchange.tenant_id == pro.id and exchange.answer == "Rates fell twice."
    assert db.query(QuotaUsage).filter_by(user_id=pro.id, resource="library_qa_exchanges").one().consumed == 1
    _no_chroma.assert_called_once()


def test_a_shelf_scope_narrows_to_that_shelfs_documents(db, pro):
    in_shelf, outside = _doc(db, pro.id, "In"), _doc(db, pro.id, "Out")
    job = Job(job_type="topic", topic="t", status="completed", num_videos=1, tenant_id=pro.id)
    db.add(job)
    db.commit()
    db.add(JobVideo(job_id=job.id, document_id=in_shelf.document_id, video_id=in_shelf.video_id, approved=True))
    db.commit()
    shelf = shelf_service.create_shelf(db, pro.id, name="Macro")
    shelf_service.add_job(db, shelf, job)
    empty = shelf_service.create_shelf(db, pro.id, name="Empty")
    agent = FakeAgent()
    saved_search_service.execute(db, _saved(db, pro, scope={"shelf_id": shelf.id}).id, agent=agent)
    saved_search_service.execute(db, _saved(db, pro, scope={"shelf_id": empty.id}).id, agent=agent)
    assert agent.calls[0]["visible_document_ids"] == [in_shelf.document_id]
    assert agent.calls[1]["visible_document_ids"] == []  # never widens to the library
    assert outside.document_id not in agent.calls[0]["visible_document_ids"]


def test_over_quota_skips_before_spending_and_keeps_the_baseline(db, pro):
    ss = _saved(db, pro)
    saved_search_service.execute(db, ss.id, agent=FakeAgent())
    db.refresh(ss)
    baseline = (ss.last_exchange_id, ss.last_answer_hash)
    agent = FakeAgent(answer="different")
    with patch("app.services.quota_metering_service.check_quota", return_value=(False, None)):
        out = saved_search_service.execute(db, ss.id, agent=agent)
    assert out["status"] == "quota_exceeded" and agent.calls == []
    db.refresh(ss)
    assert ss.last_status == "quota_exceeded" and (ss.last_exchange_id, ss.last_answer_hash) == baseline


def test_a_failed_run_is_recorded_and_leaves_the_previous_result(db, pro):
    ss = _saved(db, pro)
    saved_search_service.execute(db, ss.id, agent=FakeAgent())
    db.refresh(ss)
    baseline = ss.last_exchange_id
    out = saved_search_service.execute(db, ss.id, agent=FakeAgent(fail=True))
    assert out["status"] == "failed"
    db.refresh(ss)
    assert ss.last_status == "failed" and "provider down" in ss.last_error
    assert ss.last_exchange_id == baseline
    assert db.query(QuotaUsage).filter_by(user_id=pro.id).one().consumed == 1  # only the good run counted


def test_runs_that_should_not_happen_do_not(db, pro):
    ss = _saved(db, pro)
    agent = FakeAgent()
    saved_search_service.update(db, pro, ss, enabled=False)
    assert saved_search_service.execute(db, ss.id, agent=agent)["status"] == "disabled"
    assert saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)["status"] == "ok"
    pro.tier = "free"
    db.commit()
    assert saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)["status"] == "feature_unavailable"
    assert len(agent.calls) == 1
    assert saved_search_service.execute(db, "nope", agent=agent)["status"] == "missing"


def test_a_deleted_shelf_stops_the_run(db, pro):
    shelf = shelf_service.create_shelf(db, pro.id, name="Gone soon")
    ss = _saved(db, pro, scope={"shelf_id": shelf.id})
    shelf_service.delete_shelf(db, shelf)
    agent = FakeAgent()
    assert saved_search_service.execute(db, ss.id, agent=agent)["status"] == "scope_missing"
    assert agent.calls == []


# ---------------------------------------------------------------- wiring


def test_the_tick_dispatches_a_due_saved_search_to_its_task(db, pro):
    import app.tasks.saved_search_tasks as tasks

    ss = _saved(db, pro)
    row = scheduler_service.get_run(db, "saved_search", ss.id)
    row.next_run_at = scheduler_service.utcnow() - timedelta(minutes=1)
    db.commit()
    with patch.object(tasks.run_saved_search, "apply_async") as apply_async:
        result = scheduler_service.run_tick(db)
    assert result["dispatched"] == 1
    kwargs = apply_async.call_args.kwargs
    assert kwargs["args"] == [ss.id] and kwargs["kwargs"] == {"scheduled_run_id": row.id}


def test_the_task_runs_the_service(db, pro):
    import app.tasks.saved_search_tasks as tasks

    with patch.object(tasks.saved_search_service, "execute", return_value={"status": "ok"}) as execute, patch.object(
        tasks, "SessionLocal", return_value=db
    ):
        assert tasks.run_saved_search.run("ss-1", scheduled_run_id="r1") == {"status": "ok"}
    assert execute.call_args.args[1] == "ss-1" and execute.call_args.kwargs == {"trigger": "schedule"}


def test_a_worker_registers_the_kind_through_autodiscovery():
    """A fresh interpreter, as a worker starts: only autodiscovery imports
    the task module. Without it the tick would record `no_handler`."""
    backend = Path(__file__).resolve().parents[2]
    code = (
        "from app.tasks.celery_app import celery_app\n"
        "celery_app.loader.import_default_modules()\n"
        "from app.services import scheduler_service\n"
        "print('saved_search' in scheduler_service.registered_kinds(), 'saved_search.run' in celery_app.tasks)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(backend)}
    out = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env, capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "True True", out.stderr[-2000:]

"""S-6.7.1 — Author Studio generation runs in the worker.

Router: `POST /author/outputs` queues `generate_output` on the owner's tier
queue and returns `pending`; a kind with no outputter is 501 before any row;
a broker failure is recorded on the row; cancel mirrors `/jobs/{id}/cancel`.
Socket: a user may subscribe to their own output's progress and not to
anyone else's.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.models.job import Job
from app.models.output import Output
from app.services import auth_service, output_service
from app.services.output_service import OutputStatus


def _pro(db, email: str):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def _job(db, user_id: str) -> Job:
    job = Job(id=str(uuid.uuid4()), job_type="topic", status="completed", topic="T",
              tenant_id=user_id, report_path="/r.html")
    db.add(job)
    db.commit()
    return job


def _book(client, headers, job_id: str, *, sync: bool = False):
    url = "/api/v1/author/outputs" + ("?sync=true" if sync else "")
    return client.post(url, headers=headers,
                       json={"kind": "book", "title": "B", "source_ids": [job_id], "parameters": {"include_qa": False}})


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_create_queues_generation_on_the_tier_queue_and_returns_pending(unauthenticated_client, db):
    from app.routers import author as author_router

    user, headers = _pro(db, "q@x.com")
    job = _job(db, user.id)
    r = _book(unauthenticated_client, headers, job.id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["has_content"] is False
    assert body["celery_task_id"] == "mock-generate-output-task-id"
    assert body["progress_message"] == "Queued"

    task = author_router.generate_output
    task.apply_async.assert_called_once()
    kwargs = task.apply_async.call_args.kwargs
    assert kwargs["args"] == [body["id"]]
    assert kwargs["queue"] == "tier_pro"

    row = db.get(Output, body["id"])
    assert row.celery_task_id == "mock-generate-output-task-id"


def test_sync_query_generates_inline(unauthenticated_client, db, monkeypatch):
    from app.routers import author as author_router
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<h1>T</h1><p>Body.</p>")
    user, headers = _pro(db, "s@x.com")
    job = _job(db, user.id)
    r = _book(unauthenticated_client, headers, job.id, sync=True)
    body = r.json()
    assert body["status"] == "completed" and body["has_content"] is True
    assert body["progress_pct"] == 100 and body["progress_message"] == "Done"
    author_router.generate_output.apply_async.assert_not_called()


def test_no_outputter_is_501_and_writes_no_row(unauthenticated_client, db):
    _, headers = _pro(db, "n@x.com")
    r = unauthenticated_client.post("/api/v1/author/outputs", headers=headers,
                                    json={"kind": "reel", "title": "x", "source_ids": ["a"]})
    assert r.status_code == 501
    assert db.query(Output).count() == 0


def test_broker_failure_is_recorded_on_the_row(unauthenticated_client, db):
    from app.routers import author as author_router

    user, headers = _pro(db, "b@x.com")
    job = _job(db, user.id)
    author_router.generate_output.apply_async.side_effect = ConnectionError("redis down")
    r = _book(unauthenticated_client, headers, job.id)
    body = r.json()
    assert body["status"] == "failed"
    assert "Could not queue generation" in body["error_message"] and "redis down" in body["error_message"]


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def test_cancel_revokes_marks_cancelled_and_publishes(unauthenticated_client, db):
    user, headers = _pro(db, "c@x.com")
    job = _job(db, user.id)
    out = _book(unauthenticated_client, headers, job.id).json()

    fake_celery = MagicMock()
    with (
        patch("app.tasks.celery_app.celery_app", fake_celery),
        patch("app.services.progress_service.publish_status_change") as pub,
    ):
        r = unauthenticated_client.post(f"/api/v1/author/outputs/{out['id']}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    fake_celery.control.revoke.assert_called_once_with("mock-generate-output-task-id", terminate=True)
    pub.assert_called_once_with(out["id"], "pending", "cancelled", "Cancelled by user")

    again = unauthenticated_client.post(f"/api/v1/author/outputs/{out['id']}/cancel", headers=headers)
    assert again.status_code == 400


def test_cancel_another_users_output_is_404(unauthenticated_client, db):
    owner, headers_owner = _pro(db, "co@x.com")
    _, headers_other = _pro(db, "cx@x.com")
    job = _job(db, owner.id)
    out = _book(unauthenticated_client, headers_owner, job.id).json()
    r = unauthenticated_client.post(f"/api/v1/author/outputs/{out['id']}/cancel", headers=headers_other)
    assert r.status_code == 404
    assert db.get(Output, out["id"]).status == "pending"


def test_cancel_a_finished_output_is_400(unauthenticated_client, db, monkeypatch):
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")
    user, headers = _pro(db, "cf@x.com")
    job = _job(db, user.id)
    out = _book(unauthenticated_client, headers, job.id, sync=True).json()
    r = unauthenticated_client.post(f"/api/v1/author/outputs/{out['id']}/cancel", headers=headers)
    assert r.status_code == 400 and "completed" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Socket ownership: outputs share the job progress channel
# ---------------------------------------------------------------------------


def test_socket_subscription_allows_own_output_and_denies_foreign(db):
    from app.routers.ws import _owns_job
    from tests.conftest import TestingSessionLocal

    mine = auth_service.create_user(db, email="w1@x.com", password="pw" * 6)
    theirs = auth_service.create_user(db, email="w2@x.com", password="pw" * 6)
    row = output_service.create_output(db, user_id=theirs.id, kind="book", title="T", source_ids=["j"])
    assert _owns_job(theirs.id, row.id, TestingSessionLocal) is True
    assert _owns_job(mine.id, row.id, TestingSessionLocal) is False


# ---------------------------------------------------------------------------
# Service: cooperative cancellation and progress
# ---------------------------------------------------------------------------


def test_cancel_during_generation_ends_cancelled_with_no_content(db, monkeypatch):
    """The user cancels after chapter one; the outputter's next progress
    report raises and the row ends `cancelled`, never `completed`."""
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")
    user = auth_service.create_user(db, email="cd@x.com", password="pw" * 6)
    jobs = [_job(db, user.id) for _ in range(3)]
    import app.services.outputters  # noqa: F401

    row = output_service.create_output(db, user_id=user.id, kind="book", title="B",
                                       source_ids=[j.id for j in jobs], parameters={"include_qa": False})
    calls = {"n": 0}
    real = output_service._publish_progress

    def cancel_after_first(output):
        real(output)
        calls["n"] += 1
        if calls["n"] == 1:  # simulate the API process cancelling now
            db.query(Output).filter(Output.id == output.id).update({"status": "cancelled"})
            db.commit()

    monkeypatch.setattr(output_service, "_publish_progress", cancel_after_first)
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        result = output_service.run_generation(db, user, row)
    assert result.status == OutputStatus.CANCELLED.value
    assert result.content_text is None
    assert calls["n"] == 1, "generation stopped at the next chapter"


def test_progress_is_published_per_chapter_and_status_changes_too(db, monkeypatch):
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")
    user = auth_service.create_user(db, email="pp@x.com", password="pw" * 6)
    jobs = [_job(db, user.id) for _ in range(2)]
    import app.services.outputters  # noqa: F401

    row = output_service.create_output(db, user_id=user.id, kind="book", title="B",
                                       source_ids=[j.id for j in jobs], parameters={"include_qa": False})
    with (
        patch("app.services.progress_service.publish_progress") as prog,
        patch("app.services.progress_service.publish_status_change") as stat,
    ):
        result = output_service.run_generation(db, user, row)
    assert result.status == "completed"
    assert [c.args[2] for c in prog.call_args_list] == [5, 50, 90]
    assert all(c.args[0] == row.id for c in prog.call_args_list)
    assert "Chapter 2 of 2" in prog.call_args_list[-1].args[3]
    assert [(c.args[1], c.args[2]) for c in stat.call_args_list] == [("pending", "generating"), ("generating", "completed")]


def test_a_row_cancelled_before_it_starts_is_left_alone(db):
    user = auth_service.create_user(db, email="pre@x.com", password="pw" * 6)
    import app.services.outputters  # noqa: F401

    row = output_service.create_output(db, user_id=user.id, kind="book", title="B", source_ids=["j"])
    row.status = "cancelled"
    db.commit()
    with patch("app.services.progress_service.publish_status_change") as stat:
        result = output_service.run_generation(db, user, row)
    assert result.status == "cancelled"
    stat.assert_not_called()

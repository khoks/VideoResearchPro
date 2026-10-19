"""S-6.7.1 — the `generate_output` Celery task is wired.

The task opens its own session (the worker has no request), so these tests
point its `SessionLocal` at the test engine and run the task body directly.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.job import Job
from app.models.output import Output
from app.services import auth_service, output_service
from app.tasks import output_tasks
from app.tasks.celery_app import celery_app
from tests.conftest import TestingSessionLocal


@pytest.fixture
def worker_session(db):
    with (
        patch.object(output_tasks, "SessionLocal", TestingSessionLocal),
        patch("app.services.progress_service.publish_progress"),
        patch("app.services.progress_service.publish_status_change"),
    ):
        yield db


def _book_row(db, monkeypatch) -> Output:
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<h1>T</h1><p>Body.</p>")
    user = auth_service.create_user(db, email=f"{uuid.uuid4().hex[:6]}@x.com", password="pw" * 6)
    job = Job(id=str(uuid.uuid4()), job_type="topic", status="completed", topic="T",
              tenant_id=user.id, report_path="/r.html")
    db.add(job)
    db.commit()
    return output_service.create_output(db, user_id=user.id, kind="book", title="B",
                                        source_ids=[job.id], parameters={"include_qa": False})


def test_task_is_registered_under_its_name():
    assert "author.generate_output" in celery_app.tasks


def test_task_generates_the_output(worker_session, monkeypatch):
    row = _book_row(worker_session, monkeypatch)
    assert output_tasks.generate_output.run(row.id) == "completed"
    worker_session.expire_all()
    done = worker_session.get(Output, row.id)
    assert done.status == "completed" and "# B" in done.content_text
    assert done.progress_pct == 100


def test_task_skips_a_cancelled_or_finished_row(worker_session, monkeypatch):
    row = _book_row(worker_session, monkeypatch)
    row.status = "cancelled"
    worker_session.commit()
    assert output_tasks.generate_output.run(row.id) == "cancelled"
    worker_session.expire_all()
    assert worker_session.get(Output, row.id).content_text is None


def test_task_tolerates_a_deleted_row(worker_session):
    assert output_tasks.generate_output.run("no-such-output") is None


def test_task_fails_the_row_when_the_owner_is_gone(worker_session):
    row = output_service.create_output(worker_session, user_id="ghost-user", kind="book", title="B", source_ids=["j"])
    assert output_tasks.generate_output.run(row.id) == "failed"
    worker_session.expire_all()
    assert "owner no longer exists" in worker_session.get(Output, row.id).error_message

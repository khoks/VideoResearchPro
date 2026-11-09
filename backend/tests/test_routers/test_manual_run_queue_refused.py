"""T-5.2.19: Run now and Send now answer 503 in words when the queue is down.

``POST /saved-searches/{id}/run-now`` and ``POST /author/newsletter/send-now``
dispatch a worker task and nothing else. With the broker down the dispatch
raised and the API answered a bare 500, as ``POST /jobs`` did before T-5.2.17.
They now answer 503 with a sentence the page can show and never the broker's
error, which can hold its URL and password.

Neither route has anything to undo. Run now checks the saved-search quota by
reading it (the run itself records the use when it answers), and Send now
reads the subscription; the issue, its send row and the email are the worker's.
The tests below look at every table those could touch.

Mutation check: remove either ``except`` and its test fails on a 500 (the
TestClient re-raises the broker's error).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.newsletter_subscription import NewsletterSend, NewsletterSubscription
from app.models.output import Output
from app.models.quota_usage import QuotaUsage
from app.models.saved_search import SavedSearch
from app.models.saved_search_run import SavedSearchRun
from app.models.scheduled_run import ScheduledRun
from app.services import newsletter_service, saved_search_service

# What a broker's error can hold: the broker URL, with its password.
BROKER_DOWN = OSError("Error 10061 connecting to redis://:hunter2-secret@localhost:6379/1")
WEEKLY = {"cadence": "weekly", "hour": 9, "weekday": 0, "timezone": "Europe/London"}


@pytest.fixture
def pro(db, test_user):
    test_user.tier = "pro"
    db.commit()
    return test_user


def _rows(db) -> dict:
    db.expire_all()
    return {
        "quota_usage": [(q.resource, q.consumed) for q in db.query(QuotaUsage).all()],
        "saved_search_runs": db.query(SavedSearchRun).count(),
        "scheduled_runs": [(r.kind, r.next_run_at, r.last_status) for r in db.query(ScheduledRun).all()],
        "saved_searches": [(s.id, s.last_run_at, s.last_status, s.last_error) for s in db.query(SavedSearch).all()],
        "newsletter_sends": db.query(NewsletterSend).count(),
        "outputs": db.query(Output).count(),
        "subscriptions": [(s.id, s.last_issue_at) for s in db.query(NewsletterSubscription).all()],
    }


def test_run_now_with_the_queue_down_answers_503_in_words(client, db, pro):
    ss = saved_search_service.create(db, pro, question="What do my sources say about rate cuts?", cadence=WEEKLY)
    before = _rows(db)

    with patch("app.routers.saved_searches.task_routing_service.dispatch_for_user", side_effect=BROKER_DOWN) as dispatch:
        response = client.post(f"/api/v1/saved-searches/{ss.id}/run-now")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Could not queue the run; the task queue is unavailable. Try Run now again in a few minutes."
    )
    assert "hunter2" not in response.text and "redis" not in response.text
    dispatch.assert_called_once()
    assert _rows(db) == before, "nothing was written, so nothing is left to undo"


def test_run_now_queued_is_unchanged(client, db, pro):
    ss = saved_search_service.create(db, pro, question="What do my sources say about rate cuts?", cadence=WEEKLY)
    with patch("app.routers.saved_searches.task_routing_service.dispatch_for_user") as dispatch:
        response = client.post(f"/api/v1/saved-searches/{ss.id}/run-now")
    assert response.status_code == 202 and response.json() == {"status": "queued"}
    dispatch.assert_called_once()


def test_send_now_with_the_queue_down_answers_503_in_words(client, db, pro):
    newsletter_service.save(db, pro, cadence=WEEKLY)
    before = _rows(db)

    with patch("app.routers.author.issue_newsletter") as task:
        task.apply_async.side_effect = BROKER_DOWN
        response = client.post("/api/v1/author/newsletter/send-now")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Could not queue the issue, so nothing was sent; the task queue is unavailable. "
        "Try Send now again in a few minutes."
    )
    assert "hunter2" not in response.text and "redis" not in response.text
    task.apply_async.assert_called_once()
    assert _rows(db) == before, "nothing was written, so nothing is left to undo"


def test_send_now_queued_is_unchanged(client, db, pro):
    newsletter_service.save(db, pro, cadence=WEEKLY)
    response = client.post("/api/v1/author/newsletter/send-now")
    assert response.status_code == 200
    assert response.json() == {"status": "queued", "task_id": "mock-issue-newsletter-task-id"}


def test_send_now_with_the_digest_off_is_still_a_400_before_any_dispatch(client, db, pro):
    with patch("app.routers.author.issue_newsletter") as task:
        task.apply_async.side_effect = BROKER_DOWN
        response = client.post("/api/v1/author/newsletter/send-now")
    assert response.status_code == 400
    task.apply_async.assert_not_called()

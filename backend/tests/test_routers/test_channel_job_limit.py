"""T-5.2.15: a channel sync meets the same per-user limit as any other job.

``_dispatch_subscription_sync`` writes its row directly, so nothing checked it,
and a sync could take a user past the limit it counted toward. It has two
callers, and they answer differently:

- ``sync_channel``: a user pressed Sync now. At the limit it is refused, 429,
  with the sentence ``POST /jobs`` uses.
- ``subscribe_channel``: subscribing is not a job, so it always succeeds. At
  the limit the first sync does not start, and the response says so.

Mutation check: remove the ``refuse_if_at_limit`` call from ``sync_channel`` and
``test_sync_now_at_the_limit_is_refused_like_any_other_job`` fails on 200; from
``subscribe_channel`` and ``test_subscribing_at_the_limit_stands_and_says_no_sync_started``
fails on a job the limit should have stopped.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.channel import Channel
from app.models.job import Job
from app.services import auth_service, subscription_service

CHANNEL = "UClimit000001"
JOB_BODY = {"job_type": "topic", "topic": "tariffs"}


@pytest.fixture
def limit(db) -> int:
    db.add(Channel(channel_id=CHANNEL, name="Limit Channel", uploads_playlist_id="UUlimit000001"))
    db.commit()
    return settings.MAX_CONCURRENT_JOBS


@pytest.fixture
def task():
    with patch("app.tasks.job_tasks.execute_subscription_job") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="sync-task")
        yield mock_task


def _hold(db, tenant_id: str, count: int, status: str = "extracting") -> None:
    db.add_all([Job(job_type="topic", topic="held", status=status, tenant_id=tenant_id) for _ in range(count)])
    db.commit()


def _sync_rows(db) -> list[Job]:
    db.expire_all()
    return db.query(Job).filter(Job.job_type == "subscription").all()


def test_sync_now_at_the_limit_is_refused_like_any_other_job(client, db, test_user, limit, task):
    _hold(db, test_user.id, limit)
    other_job = client.post("/api/v1/jobs", json=JOB_BODY)

    response = client.post(f"/api/v1/channels/{CHANNEL}/sync")

    assert response.status_code == 429
    assert response.json()["detail"] == other_job.json()["detail"]
    assert response.json()["detail"] == (
        "You have 5 active jobs, and your limit is 5 at once. "
        "Other people's jobs do not count toward it. Wait for one to finish, or cancel one."
    )
    task.apply_async.assert_not_called()
    assert _sync_rows(db) == []


def test_sync_now_one_under_the_limit_starts(client, db, test_user, limit, task):
    _hold(db, test_user.id, limit - 1)

    response = client.post(f"/api/v1/channels/{CHANNEL}/sync")

    assert response.status_code == 200
    assert response.json()["job_id"] == _sync_rows(db)[0].id
    assert response.json()["sync_note"] is None
    task.apply_async.assert_called_once()


def test_a_sync_now_counts_toward_the_next_one(client, db, test_user, limit, task):
    """So a user cannot press past the limit with syncs alone."""
    for _ in range(limit):
        assert client.post(f"/api/v1/channels/{CHANNEL}/sync").status_code == 200

    assert client.post(f"/api/v1/channels/{CHANNEL}/sync").status_code == 429
    assert len(_sync_rows(db)) == limit


def test_other_peoples_jobs_do_not_refuse_a_sync(client, db, test_user, limit, task):
    other = auth_service.create_user(db, email="busy@example.com", password="pw" * 6)
    _hold(db, other.id, limit)

    assert client.post(f"/api/v1/channels/{CHANNEL}/sync").status_code == 200


def test_subscribing_at_the_limit_stands_and_says_no_sync_started(client, db, test_user, limit, task):
    _hold(db, test_user.id, limit)

    response = client.post(f"/api/v1/channels/{CHANNEL}/subscribe")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] is None
    assert body["sync_note"] == (
        "You are subscribed to Limit Channel, but the first sync has not started. "
        "You have 5 active jobs, and your limit is 5 at once. "
        "Other people's jobs do not count toward it. Wait for one to finish, or cancel one. "
        "Then use Sync now to start it."
    )
    assert subscription_service.get_or_create(db, CHANNEL, test_user.id).subscribed is True
    task.apply_async.assert_not_called()
    assert _sync_rows(db) == []


def test_subscribing_with_room_starts_the_first_sync_as_before(client, db, test_user, limit, task):
    response = client.post(f"/api/v1/channels/{CHANNEL}/subscribe")

    assert response.status_code == 200
    assert response.json()["job_id"] == _sync_rows(db)[0].id
    assert response.json()["sync_note"] is None
    task.apply_async.assert_called_once()


def test_sync_now_is_how_the_first_sync_starts_later(client, db, test_user, limit, task):
    _hold(db, test_user.id, limit)
    assert client.post(f"/api/v1/channels/{CHANNEL}/subscribe").json()["job_id"] is None

    db.query(Job).update({"status": "completed"})
    db.commit()
    response = client.post(f"/api/v1/channels/{CHANNEL}/sync")

    assert response.status_code == 200
    assert response.json()["job_id"] is not None
    assert subscription_service.get_or_create(db, CHANNEL, test_user.id).subscribed is True


@pytest.mark.parametrize(
    "path, note",
    [
        (
            "subscribe",
            "You are subscribed to Limit Channel, but the first sync could not be queued. "
            "Use Sync now to start it.",
        ),
        ("sync", "The sync could not be queued. Try Sync now again in a moment."),
    ],
)
def test_a_sync_the_broker_refused_says_so_and_holds_no_place(client, db, test_user, limit, task, path, note):
    """A row nothing will run stayed pending, which the limit now reads as
    active: enough of them and a user could never start another job."""
    task.apply_async.side_effect = OSError("broker down")

    response = client.post(f"/api/v1/channels/{CHANNEL}/{path}")

    assert response.status_code == 200
    assert response.json() == {"channel_id": CHANNEL, "job_id": None, "sync_note": note}
    rows = _sync_rows(db)
    assert [r.status for r in rows] == ["failed"]
    assert rows[0].error_message == "The sync could not be queued."
    _hold(db, test_user.id, limit - 1)
    assert client.post("/api/v1/jobs", json=JOB_BODY).status_code == 201


def test_a_full_library_still_refuses_a_subscribe_before_the_job_limit_is_read(
    client, db, test_user, limit, task, monkeypatch
):
    """T-5.2.10's rule is unchanged: nothing flips and the cap is what it says."""
    from app.services import document_cap_service

    def full(*a, **k):
        raise document_cap_service.DocumentCapExceeded(
            action=document_cap_service.ACTION_SYNC, plan="Free", consumed=500, limit=500, requested=None
        )

    monkeypatch.setattr(document_cap_service, "refuse_if_full", full)
    _hold(db, test_user.id, limit)

    response = client.post(f"/api/v1/channels/{CHANNEL}/subscribe")

    assert response.status_code == 429
    assert response.json()["detail"]["resource"] == "documents"
    assert subscription_service.get_or_create(db, CHANNEL, test_user.id).subscribed is False

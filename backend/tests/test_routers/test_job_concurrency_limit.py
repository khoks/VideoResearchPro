"""T-5.2.14: ``MAX_CONCURRENT_JOBS`` is each user's own limit, at ``POST /jobs``.

It counted active jobs across the whole install, so one user's five jobs
refused everyone else. A single-user install keeps exactly what it had: five
at once, a sixth refused. Mutation check: drop the tenant filter in
``job_service.create_job`` and ``test_one_users_jobs_never_use_up_anothers_room``
fails on the second user's 429.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.models.job import Job
from app.services import auth_service

BODY = {"job_type": "topic", "topic": "tariffs"}


def _headers(db, email: str) -> dict[str, str]:
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    token, _ = auth_service.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _hold(db, tenant_id: str | None, count: int, status: str = "extracting") -> None:
    db.add_all([Job(job_type="topic", topic="held", status=status, tenant_id=tenant_id) for _ in range(count)])
    db.commit()


@pytest.fixture
def limit() -> int:
    assert settings.MAX_CONCURRENT_JOBS == 5, "the single-user default this item must not loosen"
    return settings.MAX_CONCURRENT_JOBS


def test_one_users_jobs_never_use_up_anothers_room(client, db, test_user, limit):
    _hold(db, test_user.id, limit)
    other = _headers(db, "other@example.com")

    assert client.post("/api/v1/jobs", json=BODY).status_code == 429
    r = client.post("/api/v1/jobs", json=BODY, headers=other)

    assert r.status_code == 201, r.text
    assert db.get(Job, r.json()["id"]).tenant_id != test_user.id


def test_a_single_user_install_still_stops_at_five(client, limit):
    """Through the route alone, as a one-user install reaches it."""
    for i in range(limit):
        assert client.post("/api/v1/jobs", json=BODY).status_code == 201, i
    assert client.post("/api/v1/jobs", json=BODY).status_code == 429


def test_the_refusal_says_whose_limit_it_is(client, db, test_user, limit):
    _hold(db, test_user.id, limit)

    r = client.post("/api/v1/jobs", json=BODY)

    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail == (
        "You have 5 active jobs, and your limit is 5 at once. "
        "Other people's jobs do not count toward it. Wait for one to finish, or cancel one."
    )


def test_the_refusal_states_the_count_when_syncs_took_it_past_the_limit(client, db, test_user, limit):
    """Syncs from before T-5.2.15, or a lowered setting, can leave a user over
    the limit, and the number must be theirs, not the cap repeated."""
    _hold(db, test_user.id, limit + 2)

    assert "You have 7 active jobs" in client.post("/api/v1/jobs", json=BODY).json()["detail"]


def test_a_job_waiting_for_approval_still_holds_its_place(client, db, test_user, limit):
    _hold(db, test_user.id, limit, status="awaiting_approval")

    assert client.post("/api/v1/jobs", json=BODY).status_code == 429


@pytest.mark.parametrize("status", ["completed", "cancelled", "failed"])
def test_a_finished_job_gives_its_place_back(client, db, test_user, limit, status):
    _hold(db, test_user.id, limit, status=status)

    assert client.post("/api/v1/jobs", json=BODY).status_code == 201


def test_one_under_the_limit_is_accepted(client, db, test_user, limit):
    _hold(db, test_user.id, limit - 1)

    assert client.post("/api/v1/jobs", json=BODY).status_code == 201


def test_a_channel_sync_counts_against_its_owner_alone(client, db, test_user, limit):
    """Syncs are jobs. Five of someone else's leave this user's room alone."""
    other = auth_service.create_user(db, email="syncs@example.com", password="pw" * 6)
    db.add_all([
        Job(job_type="subscription", topic="Sync", status="extracting", tenant_id=other.id)
        for _ in range(limit)
    ])
    db.commit()

    assert client.post("/api/v1/jobs", json=BODY).status_code == 201


def test_a_jobs_row_with_no_owner_counts_against_no_user(client, db, limit):
    """A row from before E-5.1. Nobody's limit can be charged with it."""
    _hold(db, None, limit)

    assert client.post("/api/v1/jobs", json=BODY).status_code == 201


def test_the_setting_is_read_per_user_at_any_value(client, db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_JOBS", 1)
    _hold(db, test_user.id, 1)
    other = _headers(db, "low-limit@example.com")

    assert client.post("/api/v1/jobs", json=BODY).status_code == 429
    assert client.post("/api/v1/jobs", json=BODY, headers=other).status_code == 201
    assert client.post("/api/v1/jobs", json=BODY, headers=other).status_code == 429

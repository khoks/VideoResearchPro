"""Tests for the E-5.1 phase-1 ``tenant_id`` columns.

Phase 1 (Alembic ``a1b2c3d4e5f6``) adds a NULLABLE ``tenant_id``
column with index to four user-scoped tables:

- ``jobs``
- ``qa_exchanges``
- ``library_qa_exchanges``
- ``qa_history_exchanges``

Until phase 2 (backfill + NOT NULL + query updates) lands, the
column is purely additive: every existing INSERT/SELECT path
continues to work unchanged. These tests lock that contract in.
"""
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange


# ---------------------------------------------------------------------------
# Default behaviour — tenant_id is NULL when not set
# ---------------------------------------------------------------------------


def test_job_tenant_id_defaults_to_none(db):
    """An existing-style INSERT (no tenant_id supplied) must succeed
    and store NULL. Phase 1 must not break code paths that haven't
    been updated yet."""
    job = Job(job_type="topic", topic="anything")
    db.add(job)
    db.commit()
    db.refresh(job)
    assert job.tenant_id is None


def test_qa_exchange_tenant_id_defaults_to_none(db):
    job = Job(job_type="topic", topic="x")
    db.add(job)
    db.commit()
    db.refresh(job)

    qa = QAExchange(
        job_id=job.id,
        question="Q?",
        answer="A.",
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)
    assert qa.tenant_id is None


def test_library_qa_exchange_tenant_id_defaults_to_none(db):
    lqa = LibraryQAExchange(question="Q?", answer="A.")
    db.add(lqa)
    db.commit()
    db.refresh(lqa)
    assert lqa.tenant_id is None


def test_qa_history_exchange_tenant_id_defaults_to_none(db):
    qh = QAHistoryExchange(question="Q?", answer="A.")
    db.add(qh)
    db.commit()
    db.refresh(qh)
    assert qh.tenant_id is None


# ---------------------------------------------------------------------------
# Setting tenant_id works — phase 2 readiness
# ---------------------------------------------------------------------------


def test_job_tenant_id_can_be_set(db):
    """Phase 2 will add `Job(tenant_id=current_user.id)` everywhere
    rows are created. Lock that the column accepts string values
    today so phase 2 just toggles the call sites."""
    job = Job(job_type="topic", topic="x", tenant_id="user-uuid-123")
    db.add(job)
    db.commit()
    db.refresh(job)
    assert job.tenant_id == "user-uuid-123"


def test_qa_exchange_tenant_id_can_be_set(db):
    job = Job(job_type="topic", topic="x", tenant_id="user-uuid-1")
    db.add(job)
    db.commit()
    db.refresh(job)

    qa = QAExchange(
        job_id=job.id,
        question="Q?",
        answer="A.",
        tenant_id="user-uuid-1",
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)
    assert qa.tenant_id == "user-uuid-1"


def test_library_qa_exchange_tenant_id_can_be_set(db):
    lqa = LibraryQAExchange(
        question="Q?", answer="A.", tenant_id="user-uuid-2"
    )
    db.add(lqa)
    db.commit()
    db.refresh(lqa)
    assert lqa.tenant_id == "user-uuid-2"


def test_qa_history_exchange_tenant_id_can_be_set(db):
    qh = QAHistoryExchange(
        question="Q?", answer="A.", tenant_id="user-uuid-3"
    )
    db.add(qh)
    db.commit()
    db.refresh(qh)
    assert qh.tenant_id == "user-uuid-3"


# ---------------------------------------------------------------------------
# Mixed populations — backfill scenarios
# ---------------------------------------------------------------------------


def test_filter_by_tenant_id_returns_only_matching_rows(db):
    """Phase 2 will add `WHERE tenant_id = ?` to every query.
    Lock the index works for that filter today."""
    j_a = Job(job_type="topic", topic="A", tenant_id="user-A")
    j_b = Job(job_type="topic", topic="B", tenant_id="user-B")
    j_legacy = Job(job_type="topic", topic="Legacy")  # no tenant_id
    db.add_all([j_a, j_b, j_legacy])
    db.commit()

    user_a_jobs = db.query(Job).filter(Job.tenant_id == "user-A").all()
    assert len(user_a_jobs) == 1
    assert user_a_jobs[0].topic == "A"

    user_b_jobs = db.query(Job).filter(Job.tenant_id == "user-B").all()
    assert len(user_b_jobs) == 1
    assert user_b_jobs[0].topic == "B"

    legacy_jobs = db.query(Job).filter(Job.tenant_id.is_(None)).all()
    assert len(legacy_jobs) == 1
    assert legacy_jobs[0].topic == "Legacy"


# ---------------------------------------------------------------------------
# Phase 2a — write-side enforcement (router endpoints stamp tenant_id
# from the authenticated user)
# ---------------------------------------------------------------------------


def test_create_topic_job_via_endpoint_stamps_tenant_id(client, test_user, db):
    """Router POST /jobs creates a Job with tenant_id = current_user.id."""
    response = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "topic",
            "topic": "tariffs",
            "search_instructions": "test",
            "num_videos": 5,
        },
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    db.expire_all()
    job = db.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.tenant_id == test_user.id


def test_subscribe_channel_creates_job_with_tenant_id(
    client, test_user, db, monkeypatch
):
    """Subscribe endpoint dispatches a subscription Job tagged with
    the operator's tenant_id."""
    from app.models.channel import Channel

    # Need a channel row to subscribe to.
    channel = Channel(
        channel_id="UC_test",
        name="Test Channel",
        creator_external_id="UC_test",
        source_type="video",
    )
    db.add(channel)
    db.commit()

    response = client.post("/api/v1/channels/UC_test/subscribe")
    assert response.status_code == 200

    db.expire_all()
    sub_job = (
        db.query(Job).filter(Job.job_type == "subscription").first()
    )
    assert sub_job is not None
    assert sub_job.tenant_id == test_user.id


# ---------------------------------------------------------------------------
# Phase 2b — read-side enforcement (queries filter by tenant_id)
# ---------------------------------------------------------------------------


def test_list_jobs_only_returns_current_users_jobs(client, db, test_user):
    """E-5.1 phase 2b: GET /api/v1/jobs filters by current_user.id."""
    # Mine — should appear.
    j_mine = Job(job_type="topic", topic="MINE", tenant_id=test_user.id)
    # Someone else's — must not appear.
    j_other = Job(job_type="topic", topic="OTHER", tenant_id="someone-else-uuid")
    # Legacy NULL row — phase 2 chose to NOT show legacy NULL rows
    # to current users since the backfill has populated tenant_id
    # everywhere. Operators who upgrade in-place follow the runbook.
    j_legacy = Job(job_type="topic", topic="LEGACY")
    db.add_all([j_mine, j_other, j_legacy])
    db.commit()

    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    topics = {j["topic"] for j in response.json()}
    assert topics == {"MINE"}


def test_get_job_returns_404_for_other_users_job(client, db, test_user):
    """E-5.1 phase 2b: GET /api/v1/jobs/{id} — other-user's job
    returns 404, not 403, to avoid leaking existence."""
    other_job = Job(
        job_type="topic", topic="OTHER", tenant_id="someone-else-uuid"
    )
    db.add(other_job)
    db.commit()
    db.refresh(other_job)

    response = client.get(f"/api/v1/jobs/{other_job.id}")
    assert response.status_code == 404


def test_library_qa_history_only_returns_current_users_exchanges(
    client, db, test_user
):
    """E-5.1 phase 2b: GET /api/v1/library/qa filters by tenant_id."""
    from app.models.library_qa_exchange import LibraryQAExchange

    mine = LibraryQAExchange(
        question="MINE", answer="A", tenant_id=test_user.id
    )
    other = LibraryQAExchange(
        question="OTHER", answer="B", tenant_id="someone-else-uuid"
    )
    db.add_all([mine, other])
    db.commit()

    response = client.get("/api/v1/library/qa")
    assert response.status_code == 200
    questions = {q["question"] for q in response.json()}
    assert questions == {"MINE"}


def test_qa_history_chat_list_only_returns_current_users_exchanges(
    client, db, test_user
):
    """E-5.1 phase 2b: GET /api/v1/qa-history/exchanges filters by tenant_id."""
    from app.models.qa_history_exchange import QAHistoryExchange

    mine = QAHistoryExchange(
        question="MINE", answer="A", tenant_id=test_user.id
    )
    other = QAHistoryExchange(
        question="OTHER", answer="B", tenant_id="someone-else-uuid"
    )
    db.add_all([mine, other])
    db.commit()

    response = client.get("/api/v1/qa-history/exchanges")
    assert response.status_code == 200
    questions = {q["question"] for q in response.json()}
    assert questions == {"MINE"}

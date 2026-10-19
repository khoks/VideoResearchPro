"""S-8.1.1 — shelves REST: tier gate, CRUD, membership, cascade, isolation.

Two tenants throughout: the authenticated ``test_user`` (flipped to Pro
where a write is exercised) and ``OTHER``, a second real user whose shelves
and jobs must be invisible — list excludes them, every direct lookup is a
404 (never a 403, which would confirm the id exists).
"""
import pytest

from app.services import auth_service, shelf_service


@pytest.fixture
def pro_user(db, test_user):
    test_user.tier = "pro"
    db.commit()
    return test_user


@pytest.fixture
def other(db):
    user = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    user.tier = "pro"
    db.commit()
    return user


def _create_job(client, topic="A run"):
    r = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": topic, "num_videos": 3})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _other_job(db, other, topic="Their run"):
    from app.models.job import Job

    job = Job(tenant_id=other.id, job_type="topic", topic=topic, status="completed", num_videos=3)
    db.add(job)
    db.commit()
    return job.id


# ---------------------------------------------------------------------------
# Tier gate: reads for everyone, writes for Pro+
# ---------------------------------------------------------------------------

def test_free_tier_can_read_but_not_write(client, db, test_user):
    shelf = shelf_service.create_shelf(db, test_user.id, "Kept after downgrade")

    assert client.get("/api/v1/shelves").status_code == 200
    assert client.get(f"/api/v1/shelves/{shelf.id}").status_code == 200

    assert client.post("/api/v1/shelves", json={"name": "New"}).status_code == 403
    assert client.put(f"/api/v1/shelves/{shelf.id}", json={"name": "Renamed"}).status_code == 403
    assert client.delete(f"/api/v1/shelves/{shelf.id}").status_code == 403
    job_id = _create_job(client)
    assert client.post(f"/api/v1/shelves/{shelf.id}/jobs/{job_id}").status_code == 403
    assert client.delete(f"/api/v1/shelves/{shelf.id}/jobs/{job_id}").status_code == 403


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_list_update_delete(client, pro_user):
    r = client.post(
        "/api/v1/shelves",
        json={"name": "  Macro  economics ", "description": "Rates and such", "color": "green"},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "Macro economics", "whitespace is collapsed"
    assert created["color"] == "green"
    assert created["job_count"] == 0
    shelf_id = created["id"]

    listed = client.get("/api/v1/shelves").json()
    assert [s["id"] for s in listed] == [shelf_id]

    r = client.put(f"/api/v1/shelves/{shelf_id}", json={"name": "Macro", "description": None})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Macro"
    assert r.json()["description"] is None, "an explicit null clears the description"
    assert r.json()["color"] == "green", "fields not sent are untouched"

    assert client.delete(f"/api/v1/shelves/{shelf_id}").status_code == 204
    assert client.get(f"/api/v1/shelves/{shelf_id}").status_code == 404
    assert client.get("/api/v1/shelves").json() == []


def test_name_collision_is_case_insensitive_and_409(client, pro_user):
    assert client.post("/api/v1/shelves", json={"name": "Kashmir"}).status_code == 201
    r = client.post("/api/v1/shelves", json={"name": "kashmir"})
    assert r.status_code == 409
    assert "already have a shelf" in r.json()["detail"]

    second = client.post("/api/v1/shelves", json={"name": "Ladakh"}).json()
    # Renaming onto another shelf's name collides; re-casing your own does not.
    assert client.put(f"/api/v1/shelves/{second['id']}", json={"name": "KASHMIR"}).status_code == 409
    assert client.put(f"/api/v1/shelves/{second['id']}", json={"name": "LADAKH"}).status_code == 200


def test_validation_rejects_blank_name_and_unknown_colour(client, pro_user):
    assert client.post("/api/v1/shelves", json={"name": "   "}).status_code == 422
    assert client.post("/api/v1/shelves", json={"name": "X", "color": "#ff0000"}).status_code == 422
    assert client.post("/api/v1/shelves", json={"name": "X", "color": "teal"}).status_code == 422


# ---------------------------------------------------------------------------
# Membership and cascade (T-8.1.1.4)
# ---------------------------------------------------------------------------

def test_add_job_is_idempotent_and_detail_lists_jobs(client, pro_user):
    shelf_id = client.post("/api/v1/shelves", json={"name": "Project"}).json()["id"]
    job_a = _create_job(client, "First")
    job_b = _create_job(client, "Second")

    assert client.post(f"/api/v1/shelves/{shelf_id}/jobs/{job_a}").json()["job_count"] == 1
    assert client.post(f"/api/v1/shelves/{shelf_id}/jobs/{job_a}").json()["job_count"] == 1
    assert client.post(f"/api/v1/shelves/{shelf_id}/jobs/{job_b}").json()["job_count"] == 2

    detail = client.get(f"/api/v1/shelves/{shelf_id}").json()
    assert detail["job_count"] == 2
    assert {j["id"] for j in detail["jobs"]} == {job_a, job_b}
    assert {j["topic"] for j in detail["jobs"]} == {"First", "Second"}

    mine = client.get(f"/api/v1/jobs/{job_a}/shelves").json()
    assert [s["id"] for s in mine] == [shelf_id]

    assert client.delete(f"/api/v1/shelves/{shelf_id}/jobs/{job_a}").status_code == 204
    assert client.delete(f"/api/v1/shelves/{shelf_id}/jobs/{job_a}").status_code == 404
    assert client.get(f"/api/v1/jobs/{job_a}/shelves").json() == []
    assert client.get(f"/api/v1/shelves/{shelf_id}").json()["job_count"] == 1


def test_a_job_can_sit_on_several_shelves(client, pro_user):
    a = client.post("/api/v1/shelves", json={"name": "A"}).json()["id"]
    b = client.post("/api/v1/shelves", json={"name": "B"}).json()["id"]
    job_id = _create_job(client)
    client.post(f"/api/v1/shelves/{a}/jobs/{job_id}")
    client.post(f"/api/v1/shelves/{b}/jobs/{job_id}")
    assert {s["name"] for s in client.get(f"/api/v1/jobs/{job_id}/shelves").json()} == {"A", "B"}


def test_deleting_a_shelf_keeps_its_jobs(client, pro_user):
    shelf_id = client.post("/api/v1/shelves", json={"name": "Temp"}).json()["id"]
    job_id = _create_job(client)
    client.post(f"/api/v1/shelves/{shelf_id}/jobs/{job_id}")

    assert client.delete(f"/api/v1/shelves/{shelf_id}").status_code == 204
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/v1/jobs/{job_id}/shelves").json() == []


def test_deleting_a_job_removes_it_from_every_shelf(client, db, pro_user):
    from app.models.shelf_job import ShelfJob

    a = client.post("/api/v1/shelves", json={"name": "A"}).json()["id"]
    b = client.post("/api/v1/shelves", json={"name": "B"}).json()["id"]
    job_id = _create_job(client)
    client.post(f"/api/v1/shelves/{a}/jobs/{job_id}")
    client.post(f"/api/v1/shelves/{b}/jobs/{job_id}")
    assert db.query(ShelfJob).filter(ShelfJob.job_id == job_id).count() == 2

    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204

    db.expire_all()
    assert db.query(ShelfJob).filter(ShelfJob.job_id == job_id).count() == 0, (
        "SQLite does not enforce FK cascades here; the ORM relationship must"
    )
    assert client.get(f"/api/v1/shelves/{a}").json()["job_count"] == 0
    assert client.get(f"/api/v1/shelves/{b}").status_code == 200


# ---------------------------------------------------------------------------
# Isolation (T-8.1.1.5): everything of the other tenant is a 404
# ---------------------------------------------------------------------------

def test_two_tenant_isolation(client, db, pro_user, other):
    theirs = shelf_service.create_shelf(db, other.id, "Their shelf")
    their_job = _other_job(db, other)
    shelf_service.add_job(db, theirs, _job(db, their_job))

    mine = client.post("/api/v1/shelves", json={"name": "Their shelf"})
    assert mine.status_code == 201, "names are unique per tenant, not globally"
    my_shelf = mine.json()["id"]
    my_job = _create_job(client)

    ids = {s["id"] for s in client.get("/api/v1/shelves").json()}
    assert theirs.id not in ids and my_shelf in ids

    assert client.get(f"/api/v1/shelves/{theirs.id}").status_code == 404
    assert client.put(f"/api/v1/shelves/{theirs.id}", json={"name": "Hijack"}).status_code == 404
    assert client.delete(f"/api/v1/shelves/{theirs.id}").status_code == 404
    # Their job onto my shelf, my job onto their shelf, listing their job's shelves.
    assert client.post(f"/api/v1/shelves/{my_shelf}/jobs/{their_job}").status_code == 404
    assert client.post(f"/api/v1/shelves/{theirs.id}/jobs/{my_job}").status_code == 404
    assert client.delete(f"/api/v1/shelves/{theirs.id}/jobs/{their_job}").status_code == 404
    assert client.get(f"/api/v1/jobs/{their_job}/shelves").status_code == 404

    db.expire_all()
    assert shelf_service.get_shelf(db, theirs.id, other.id).name == "Their shelf"
    assert shelf_service.job_count(db, theirs.id) == 1, "nothing of theirs changed"


def _job(db, job_id):
    from app.models.job import Job

    return db.get(Job, job_id)


def test_shelf_endpoints_require_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/shelves").status_code == 401
    assert unauthenticated_client.post("/api/v1/shelves", json={"name": "x"}).status_code == 401

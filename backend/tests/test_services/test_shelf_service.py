"""`shelf_service` — the single accessor for shelves (S-8.1.1)."""
import pytest

from app.models.job import Job
from app.models.shelf_job import ShelfJob
from app.services import shelf_service
from app.services.shelf_service import ForeignJob, ShelfNameTaken

ME = "tenant-me"
THEM = "tenant-them"


def _job(db, tenant_id, topic="run"):
    job = Job(tenant_id=tenant_id, job_type="topic", topic=topic, status="completed", num_videos=1)
    db.add(job)
    db.commit()
    return job


def test_create_and_case_insensitive_collision(db):
    shelf = shelf_service.create_shelf(db, ME, "Macro", "notes", "blue")
    assert shelf.color == "blue" and shelf.description == "notes"
    with pytest.raises(ShelfNameTaken):
        shelf_service.create_shelf(db, ME, "MACRO")
    # Same name for another tenant is fine.
    assert shelf_service.create_shelf(db, THEM, "macro").tenant_id == THEM


def test_list_is_tenant_scoped_and_sorted_case_insensitively(db):
    shelf_service.create_shelf(db, ME, "zeta")
    shelf_service.create_shelf(db, ME, "Alpha")
    shelf_service.create_shelf(db, THEM, "Beta")
    assert [s.name for s in shelf_service.list_shelves(db, ME)] == ["Alpha", "zeta"]


def test_get_requires_matching_tenant(db):
    shelf = shelf_service.create_shelf(db, ME, "Mine")
    assert shelf_service.get_shelf(db, shelf.id, ME) is shelf
    assert shelf_service.get_shelf(db, shelf.id, THEM) is None


def test_update_recases_own_name_but_not_onto_another(db):
    a = shelf_service.create_shelf(db, ME, "Alpha")
    b = shelf_service.create_shelf(db, ME, "Beta")
    assert shelf_service.update_shelf(db, a, name="ALPHA").name == "ALPHA"
    with pytest.raises(ShelfNameTaken):
        shelf_service.update_shelf(db, b, name="alpha")
    # Untouched fields stay; description can be cleared explicitly.
    shelf_service.update_shelf(db, b, description="d", color="red")
    shelf_service.update_shelf(db, b, description=None)
    assert b.description is None and b.color == "red" and b.name == "Beta"


def test_add_remove_and_counts(db):
    shelf = shelf_service.create_shelf(db, ME, "Project")
    j1, j2 = _job(db, ME, "one"), _job(db, ME, "two")
    assert shelf_service.add_job(db, shelf, j1) is True
    assert shelf_service.add_job(db, shelf, j1) is False, "idempotent"
    assert shelf_service.add_job(db, shelf, j2) is True
    assert shelf_service.job_count(db, shelf.id) == 2
    assert [j.id for j in shelf_service.shelf_jobs(db, shelf)] in ([j2.id, j1.id], [j1.id, j2.id])
    assert set(shelf_service.job_ids_for_shelf(db, shelf.id)) == {j1.id, j2.id}
    assert shelf_service.remove_job(db, shelf, j1.id) is True
    assert shelf_service.remove_job(db, shelf, j1.id) is False
    assert shelf_service.job_count(db, shelf.id) == 1


def test_memberships_in_one_query_including_empty_shelves(db):
    full = shelf_service.create_shelf(db, ME, "Full")
    empty = shelf_service.create_shelf(db, ME, "Empty")
    j1, j2 = _job(db, ME, "one"), _job(db, ME, "two")
    shelf_service.add_job(db, full, j1)
    shelf_service.add_job(db, full, j2)
    members = shelf_service.memberships(db, [full.id, empty.id])
    assert set(members[full.id]) == {j1.id, j2.id}
    assert members[empty.id] == []
    as_dicts = shelf_service.shelves_to_dicts(db, [full, empty])
    assert [d["job_count"] for d in as_dicts] == [2, 0]


def test_add_job_refuses_another_tenants_job(db):
    shelf = shelf_service.create_shelf(db, ME, "Mine")
    theirs = _job(db, THEM)
    with pytest.raises(ForeignJob):
        shelf_service.add_job(db, shelf, theirs)
    assert shelf_service.job_count(db, shelf.id) == 0


def test_shelves_for_job_is_scoped_by_the_shelf_owner(db):
    mine = shelf_service.create_shelf(db, ME, "Mine")
    job = _job(db, ME)
    shelf_service.add_job(db, mine, job)
    assert [s.id for s in shelf_service.shelves_for_job(db, job.id, ME)] == [mine.id]
    assert shelf_service.shelves_for_job(db, job.id, THEM) == []


def test_delete_shelf_removes_memberships_and_keeps_jobs(db):
    shelf = shelf_service.create_shelf(db, ME, "Temp")
    job = _job(db, ME)
    shelf_service.add_job(db, shelf, job)
    shelf_service.delete_shelf(db, shelf)
    assert db.query(ShelfJob).count() == 0
    assert db.get(Job, job.id) is not None


def test_deleting_a_job_through_the_orm_removes_its_memberships(db):
    """`job_service.delete_job` does `db.delete(job)`; the relationship on
    `Job` must cascade because SQLite is not enforcing the FK here."""
    a = shelf_service.create_shelf(db, ME, "A")
    b = shelf_service.create_shelf(db, ME, "B")
    job = _job(db, ME)
    shelf_service.add_job(db, a, job)
    shelf_service.add_job(db, b, job)
    db.delete(job)
    db.commit()
    assert db.query(ShelfJob).count() == 0
    assert shelf_service.get_shelf(db, a.id, ME) is not None
    assert shelf_service.get_shelf(db, b.id, ME) is not None

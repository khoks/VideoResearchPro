"""S-8.1.2 — `GET /shelves/{id}/documents`: the union of the shelf's jobs'
documents, deduplicated, scoped by visibility, with the library filters."""
from datetime import datetime, timezone

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import auth_service, shelf_service, visibility_service


@pytest.fixture
def pro_user(db, test_user):
    test_user.tier = "pro"
    db.commit()
    return test_user


def _doc(db, vid, title):
    d = Document(
        video_id=vid, title=title, url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=120, transcript_status="fetched",
        created_at=datetime.now(timezone.utc),
    )
    db.add(d)
    db.commit()
    return d


def _job(db, tenant_id, topic, video_ids):
    job = Job(tenant_id=tenant_id, job_type="topic", topic=topic, status="completed", num_videos=5)
    db.add(job)
    db.commit()
    db.add_all([JobVideo(job_id=job.id, video_id=v, approved=True) for v in video_ids])
    db.commit()
    return job


def test_union_is_deduplicated_scoped_by_shelf_and_visibility(client, db, pro_user):
    docs = {
        vid: _doc(db, vid, title)
        for vid, title in [("shelfvid001", "Alpha"), ("shelfvid002", "Beta"),
                           ("shelfvid003", "Gamma"), ("shelfvid004", "Delta")]
    }
    # Gamma is selected by a shelf job but never granted to the caller.
    # D-070: grants are keyed on document_id.
    visibility_service.grant(
        db, [docs[v].document_id for v in ("shelfvid001", "shelfvid002", "shelfvid004")], pro_user.id
    )

    a = _job(db, pro_user.id, "Run A", ["shelfvid001", "shelfvid002"])
    b = _job(db, pro_user.id, "Run B", ["shelfvid002", "shelfvid003"])
    _job(db, pro_user.id, "Run C (not shelved)", ["shelfvid004"])

    shelf = shelf_service.create_shelf(db, pro_user.id, "Project")
    shelf_service.add_job(db, shelf, a)
    shelf_service.add_job(db, shelf, b)

    r = client.get(f"/api/v1/shelves/{shelf.id}/documents")
    assert r.status_code == 200, r.text
    rows = {row["video_id"]: row for row in r.json()}
    assert set(rows) == {"shelfvid001", "shelfvid002"}, (
        "Beta once (dedup), Gamma hidden (visibility), Delta absent (not on the shelf)"
    )
    assert rows["shelfvid002"]["job_count"] == 2
    assert set(rows["shelfvid002"]["job_titles"]) == {"Run A", "Run B"}

    # The library filters apply.
    r = client.get(f"/api/v1/shelves/{shelf.id}/documents", params={"search": "alp"})
    assert [row["video_id"] for row in r.json()] == ["shelfvid001"]


def test_empty_shelf_lists_nothing_not_the_whole_library(client, db, pro_user):
    d = _doc(db, "shelfvid010", "Visible but unshelved")
    visibility_service.grant(db, [d.document_id], pro_user.id)
    _job(db, pro_user.id, "Unshelved run", ["shelfvid010"])
    shelf = shelf_service.create_shelf(db, pro_user.id, "Empty")

    r = client.get(f"/api/v1/shelves/{shelf.id}/documents")
    assert r.status_code == 200
    assert r.json() == []


def test_foreign_shelf_is_404_and_free_tier_can_read(client, db, test_user):
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    theirs = shelf_service.create_shelf(db, other.id, "Theirs")
    assert client.get(f"/api/v1/shelves/{theirs.id}/documents").status_code == 404

    mine = shelf_service.create_shelf(db, test_user.id, "Mine")  # test_user is Free
    assert client.get(f"/api/v1/shelves/{mine.id}/documents").status_code == 200


def test_library_listing_unchanged_by_the_refactor(client, db, pro_user):
    d = _doc(db, "shelfvid020", "Still listed")
    visibility_service.grant(db, [d.document_id], pro_user.id)
    _job(db, pro_user.id, "Some run", ["shelfvid020"])
    r = client.get("/api/v1/library/videos")
    assert r.status_code == 200
    assert [row["video_id"] for row in r.json()] == ["shelfvid020"]
    assert r.json()[0]["job_titles"] == ["Some run"]

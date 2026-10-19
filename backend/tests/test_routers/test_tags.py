"""S-8.1.3 — per-tenant tags on documents.

The documents are shared (D-063) and the tags are not: two readers who can
both see the same document each see only their own tags on it, a tag id from
another reader is a 404 everywhere, and a document the caller cannot see can
be neither tagged nor found through a tag filter.
"""
from datetime import datetime, timezone

import pytest

from app.models.document import Document
from app.models.tagging import Tagging
from app.services import auth_service, shelf_service, tag_service, visibility_service


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="other@example.com", password="otherpass123")


def _doc(db, vid, title, granted_to=()):
    d = Document(
        video_id=vid, title=title, url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=90, transcript_status="fetched",
        created_at=datetime.now(timezone.utc),
    )
    db.add(d)
    db.commit()
    for tenant in granted_to:
        visibility_service.grant(db, [d.document_id], tenant)
    return d


# ---------------------------------------------------------------------------
# Tag CRUD
# ---------------------------------------------------------------------------

def test_create_list_rename_recolour(client):
    r = client.post("/api/v1/tags", json={"name": "  must  read ", "color": "red"})
    assert r.status_code == 201, r.text
    tag = r.json()
    assert tag["name"] == "must read" and tag["color"] == "red" and tag["document_count"] == 0

    assert client.post("/api/v1/tags", json={"name": "MUST READ"}).status_code == 409
    assert client.post("/api/v1/tags", json={"name": "x", "color": "#123456"}).status_code == 422

    r = client.put(f"/api/v1/tags/{tag['id']}", json={"name": "Must read", "color": "blue"})
    assert r.status_code == 200
    assert r.json()["id"] == tag["id"], "rename keeps the id"
    assert (r.json()["name"], r.json()["color"]) == ("Must read", "blue")

    assert [t["name"] for t in client.get("/api/v1/tags").json()] == ["Must read"]


def test_rename_onto_another_tag_is_409(client):
    a = client.post("/api/v1/tags", json={"name": "alpha"}).json()
    client.post("/api/v1/tags", json={"name": "beta"})
    assert client.put(f"/api/v1/tags/{a['id']}", json={"name": "BETA"}).status_code == 409


# ---------------------------------------------------------------------------
# Applying tags, the row field, the filter
# ---------------------------------------------------------------------------

def test_apply_shows_on_rows_filters_and_counts(client, db, test_user):
    d1 = _doc(db, "tagvid00001", "One", [test_user.id])
    d2 = _doc(db, "tagvid00002", "Two", [test_user.id])
    tag = client.post("/api/v1/tags", json={"name": "keep", "color": "green"}).json()

    r = client.put(f"/api/v1/library/videos/{d1.document_id}/tags/{tag['id']}")
    assert r.status_code == 200, r.text
    assert [t["name"] for t in r.json()] == ["keep"]
    # Idempotent.
    assert client.put(f"/api/v1/library/videos/{d1.document_id}/tags/{tag['id']}").status_code == 200
    assert db.query(Tagging).count() == 1

    rows = {row["id"]: row for row in client.get("/api/v1/library/videos").json()}
    assert [t["id"] for t in rows[d1.document_id]["tags"]] == [tag["id"]]
    assert rows[d2.document_id]["tags"] == []

    filtered = client.get("/api/v1/library/videos", params={"tag": tag["id"]}).json()
    assert [row["id"] for row in filtered] == [d1.document_id]
    assert client.get("/api/v1/tags").json()[0]["document_count"] == 1

    assert client.delete(f"/api/v1/library/videos/{d1.document_id}/tags/{tag['id']}").status_code == 204
    assert client.delete(f"/api/v1/library/videos/{d1.document_id}/tags/{tag['id']}").status_code == 404
    assert client.get("/api/v1/library/videos", params={"tag": tag["id"]}).json() == []


def test_shelf_documents_accept_the_tag_filter(client, db, test_user):
    from app.models.job import Job
    from app.models.job_video import JobVideo

    d1 = _doc(db, "tagvid00011", "Shelved tagged", [test_user.id])
    d2 = _doc(db, "tagvid00012", "Shelved untagged", [test_user.id])
    job = Job(tenant_id=test_user.id, job_type="topic", topic="run", status="completed", num_videos=2)
    db.add(job)
    db.commit()
    db.add_all([JobVideo(job_id=job.id, video_id=v, approved=True) for v in ("tagvid00011", "tagvid00012")])
    db.commit()
    shelf = shelf_service.create_shelf(db, test_user.id, "S")
    shelf_service.add_job(db, shelf, job)
    tag = tag_service.create_tag(db, test_user.id, "flag")
    tag_service.apply_tag(db, tag, d1.document_id)

    rows = client.get(f"/api/v1/shelves/{shelf.id}/documents", params={"tag": tag.id}).json()
    assert [row["id"] for row in rows] == [d1.document_id]
    assert d2.document_id not in {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# Delete and merge
# ---------------------------------------------------------------------------

def test_delete_removes_taggings_and_keeps_documents(client, db, test_user):
    d = _doc(db, "tagvid00021", "Doc", [test_user.id])
    tag = client.post("/api/v1/tags", json={"name": "gone"}).json()
    client.put(f"/api/v1/library/videos/{d.document_id}/tags/{tag['id']}")

    assert client.delete(f"/api/v1/tags/{tag['id']}").status_code == 204
    assert db.query(Tagging).count() == 0
    assert client.get("/api/v1/tags").json() == []
    assert [row["id"] for row in client.get("/api/v1/library/videos").json()] == [d.document_id]


def test_merge_moves_taggings_without_duplicates(client, db, test_user):
    d1 = _doc(db, "tagvid00031", "Both tags", [test_user.id])
    d2 = _doc(db, "tagvid00032", "Source only", [test_user.id])
    src = client.post("/api/v1/tags", json={"name": "ml"}).json()
    dst = client.post("/api/v1/tags", json={"name": "machine learning"}).json()
    for doc_id, tag_id in [(d1.document_id, src["id"]), (d1.document_id, dst["id"]), (d2.document_id, src["id"])]:
        assert client.put(f"/api/v1/library/videos/{doc_id}/tags/{tag_id}").status_code == 200

    assert client.delete(f"/api/v1/tags/{src['id']}", params={"into": src["id"]}).status_code == 400
    assert client.delete(f"/api/v1/tags/{src['id']}", params={"into": dst["id"]}).status_code == 204

    tags = client.get("/api/v1/tags").json()
    assert [(t["name"], t["document_count"]) for t in tags] == [("machine learning", 2)]
    assert db.query(Tagging).count() == 2, "d1's duplicate was dropped, not doubled"
    rows = {row["id"]: row for row in client.get("/api/v1/library/videos").json()}
    assert [t["name"] for t in rows[d1.document_id]["tags"]] == ["machine learning"]
    assert [t["name"] for t in rows[d2.document_id]["tags"]] == ["machine learning"]


# ---------------------------------------------------------------------------
# Isolation (T-8.1.3.4)
# ---------------------------------------------------------------------------

def test_tags_never_cross_tenants(client, db, test_user, other):
    shared = _doc(db, "tagvid00041", "Shared doc", [test_user.id, other.id])
    hidden = _doc(db, "tagvid00042", "Theirs only", [other.id])

    theirs = tag_service.create_tag(db, other.id, "secret project", "purple")
    tag_service.apply_tag(db, theirs, shared.document_id)
    tag_service.apply_tag(db, theirs, hidden.document_id)

    # Same name is fine for a different reader.
    mine = client.post("/api/v1/tags", json={"name": "secret project"})
    assert mine.status_code == 201
    mine = mine.json()

    assert [t["id"] for t in client.get("/api/v1/tags").json()] == [mine["id"]]
    row = next(r for r in client.get("/api/v1/library/videos").json() if r["id"] == shared.document_id)
    assert row["tags"] == [], "their tag on a shared document is not shown to me"

    # Their tag id is a 404 for every operation, and filters to nothing.
    assert client.put(f"/api/v1/tags/{theirs.id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/tags/{theirs.id}").status_code == 404
    assert client.delete(f"/api/v1/tags/{mine['id']}", params={"into": theirs.id}).status_code == 404
    assert client.put(f"/api/v1/library/videos/{shared.document_id}/tags/{theirs.id}").status_code == 404
    assert client.get("/api/v1/library/videos", params={"tag": theirs.id}).json() == []

    # A document I cannot see cannot be tagged, even with my own tag.
    assert client.put(f"/api/v1/library/videos/{hidden.document_id}/tags/{mine['id']}").status_code == 404

    db.expire_all()
    assert tag_service.document_counts(db, other.id, [theirs.id]) == {theirs.id: 2}
    assert tag_service.get_tag(db, theirs.id, other.id).name == "secret project"


def test_counts_only_cover_documents_still_visible(db, test_user):
    """A count must not reveal a document the reader cannot see, even one
    their own tag points at (a grant removed later, or a row written by
    hand)."""
    visible = _doc(db, "tagvid00051", "Visible", [test_user.id])
    invisible = _doc(db, "tagvid00052", "Invisible")
    tag = tag_service.create_tag(db, test_user.id, "t")
    tag_service.apply_tag(db, tag, visible.document_id)
    db.add(Tagging(tag_id=tag.id, tenant_id=test_user.id, target_type="document", target_id=invisible.document_id))
    db.commit()
    assert tag_service.document_counts(db, test_user.id, [tag.id]) == {tag.id: 1}


def test_tag_endpoints_require_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/tags").status_code == 401

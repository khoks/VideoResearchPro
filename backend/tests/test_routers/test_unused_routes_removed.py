"""Two read routes with no caller were removed (2026-11-04).

* ``GET /channels/{id}/videos``: the channel page lists a channel's
  documents through ``GET /library/videos?channel_id=``, whose rows carry
  ``job_count`` / ``job_titles`` and the library's search, filters and
  paging. The two scoped to the same visible set (D-063).
* ``GET /jobs/{id}/shelves``: the job page reads a run's shelves from the
  ``GET /shelves`` listing's ``job_ids`` (``useJobShelves``), one request
  for a whole page of job cards.

Each test builds the state in which the old route answered 200 with data,
so putting a route back fails it; and each checks that the read the page
does use still answers.
"""
from datetime import datetime, timezone

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.services import shelf_service, subscription_service, visibility_service

CH = "UCgone000000000000000001"


def test_channel_videos_route_is_gone(client, db, test_user):
    db.add(Channel(channel_id=CH, name="Gone Channel"))
    db.commit()
    subscription_service.get_or_create(db, CH, test_user.id)
    doc = Document(
        video_id="gonevid0001", title="Still listed", channel_id=CH,
        url="https://www.youtube.com/watch?v=gonevid0001",
        transcript_status="fetched", created_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], test_user.id)

    gone = client.get(f"/api/v1/channels/{CH}/videos")
    assert gone.status_code == 404
    assert gone.json()["detail"] == "Not Found", "no route, not a missing channel"

    # What the channel page reads instead.
    listed = client.get("/api/v1/library/videos", params={"channel_id": CH})
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [doc.document_id]
    assert client.get(f"/api/v1/channels/{CH}").json()["video_count"] == 1


def test_job_shelves_route_is_gone(client, db, test_user):
    job = Job(tenant_id=test_user.id, job_type="topic", topic="Shelved", status="completed")
    db.add(job)
    db.commit()
    shelf = shelf_service.create_shelf(db, test_user.id, "Holds the run")
    shelf_service.add_job(db, shelf, job)

    gone = client.get(f"/api/v1/jobs/{job.id}/shelves")
    assert gone.status_code == 404
    assert gone.json()["detail"] == "Not Found", "no route, not a missing job"

    # What the job page reads instead: the listing's memberships.
    listing = client.get("/api/v1/shelves")
    assert listing.status_code == 200
    holding = [s["name"] for s in listing.json() if job.id in s["job_ids"]]
    assert holding == ["Holds the run"]


def test_the_api_schema_no_longer_names_them(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/channels/{channel_id}/videos" not in paths
    assert "/api/v1/jobs/{job_id}/shelves" not in paths
    # Their neighbours stay.
    assert "/api/v1/channels/{channel_id}" in paths
    assert "/api/v1/jobs/{job_id}/videos" in paths

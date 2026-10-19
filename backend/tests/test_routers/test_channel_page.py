"""S-8.7.1 — the channel detail page reads `GET /channels/{id}` for its header
and the library listing (filtered by channel) for its documents.

These tests pin the response fields the page depends on and would fail if
they were dropped: `id` (the frontend keys rows and mutations on it — before
this PR the API never sent it, so the Channels tab called
``/channels/undefined/subscribe``), `url`, and the caller's own
`source_weight` (D-065: per tenant; D-068: read-only until S-7.1.1 ships the
write path).
"""
from datetime import datetime, timezone

from app.models.channel import Channel
from app.models.document import Document
from app.services import subscription_service, visibility_service

OTHER = "other-tenant-uuid"
CH = "UCpage000000000000000001"


def _seed(db, tenant_id):
    ch = Channel(channel_id=CH, name="Page Channel", subscriber_count=42)
    db.add(ch)
    db.commit()
    subscription_service.get_or_create(db, CH, tenant_id)
    return ch


def test_detail_carries_id_url_and_weight(client, db, test_user):
    _seed(db, test_user.id)

    r = client.get(f"/api/v1/channels/{CH}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == CH, "frontend rows and mutations key on `id`"
    assert data["channel_id"] == CH
    assert data["url"] == f"https://www.youtube.com/channel/{CH}"
    assert data["source_weight"] == 1.0
    assert data["subscribed"] is False


def test_list_rows_carry_id(client, db, test_user):
    _seed(db, test_user.id)
    r = client.get("/api/v1/channels")
    assert r.status_code == 200
    assert [row["id"] for row in r.json()] == [CH]


def test_source_weight_in_response_is_the_callers_not_another_tenants(
    client, db, test_user
):
    """Two tenants following the same channel see their own weight. A global
    value here would make one user's trust setting show up for everyone."""
    _seed(db, test_user.id)
    theirs = subscription_service.get_or_create(db, CH, OTHER)
    theirs.source_weight = 1.8
    db.commit()

    r = client.get(f"/api/v1/channels/{CH}")
    assert r.status_code == 200
    assert r.json()["source_weight"] == 1.0

    mine = subscription_service.get_or_create(db, CH, test_user.id)
    mine.source_weight = 0.5
    db.commit()
    assert client.get(f"/api/v1/channels/{CH}").json()["source_weight"] == 0.5
    assert subscription_service.get_or_create(db, CH, OTHER).source_weight == 1.8


def test_library_listing_filtered_by_channel_matches_channel_videos(
    client, db, test_user
):
    """The page lists documents through `GET /library/videos?channel_id=`
    (it needs `job_count` / `job_titles` for the shared row component).
    Both routes must scope to the same per-tenant visible set (D-063)."""
    _seed(db, test_user.id)
    now = datetime.now(timezone.utc)
    docs = [
        Document(
            video_id=f"pagevid{i:04d}", title=f"Doc {i}", channel_id=CH,
            url=f"https://www.youtube.com/watch?v=pagevid{i:04d}",
            duration_seconds=100 + i, transcript_status="fetched", created_at=now,
        )
        for i in range(3)
    ]
    db.add_all(docs)
    db.commit()
    # Only two of the three are visible to the caller; the third belongs to
    # another tenant and must appear in neither listing.
    visibility_service.grant(db, ["pagevid0000", "pagevid0001"], test_user.id)
    visibility_service.grant(db, ["pagevid0002"], OTHER)

    via_library = client.get("/api/v1/library/videos", params={"channel_id": CH})
    via_channel = client.get(f"/api/v1/channels/{CH}/videos")
    assert via_library.status_code == 200 and via_channel.status_code == 200
    lib_ids = {row["video_id"] for row in via_library.json()}
    ch_ids = {row["video_id"] for row in via_channel.json()}
    assert lib_ids == ch_ids == {"pagevid0000", "pagevid0001"}
    assert client.get(f"/api/v1/channels/{CH}").json()["video_count"] == 2

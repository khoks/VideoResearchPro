from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _seed_channel(db, channel_id="UCabcdefghijklmnopqrstuv", tenant_id=None, **overrides):
    """Seed a channel and, when ``tenant_id`` is given, that tenant's
    subscription state.

    D-065: subscription state moved off `channels` (where it was global —
    one user subscribing changed everyone's view) into per-tenant rows, and
    channel listings are scoped to what the tenant can see. Seeds therefore
    need a tenant or the channel is correctly invisible."""
    from app.models.channel import Channel

    channel = Channel(
        channel_id=channel_id,
        name=overrides.get("name", "Test Channel"),
        uploads_playlist_id=overrides.get("uploads_playlist_id", "UUabcdefghijklmnopqrstuv"),
        subscriber_count=overrides.get("subscriber_count", 12345),
        subscribed=overrides.get("subscribed", False),
        last_synced_at=overrides.get("last_synced_at"),
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)

    if tenant_id is not None:
        from app.services import subscription_service

        sub = subscription_service.get_or_create(db, channel.channel_id, tenant_id)
        sub.subscribed = overrides.get("subscribed", False)
        sub.last_synced_at = overrides.get("last_synced_at")
        db.commit()

    return channel


def test_list_channels_empty(client):
    response = client.get("/api/v1/channels")
    assert response.status_code == 200
    assert response.json() == []


def test_list_channels_returns_seeded(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UC000000000000000000000A", name="Alpha")
    _seed_channel(db, tenant_id=test_user.id, channel_id="UC000000000000000000000B", name="Bravo")

    response = client.get("/api/v1/channels")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = sorted(c["name"] for c in data)
    assert names == ["Alpha", "Bravo"]
    assert all("video_count" in c for c in data)


def test_get_channel_detail(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCxx1", name="Solo", subscribed=True)

    response = client.get("/api/v1/channels/UCxx1")
    assert response.status_code == 200
    data = response.json()
    assert data["channel_id"] == "UCxx1"
    assert data["name"] == "Solo"
    assert data["subscribed"] is True
    assert data["video_count"] == 0


def test_get_channel_not_found(client):
    response = client.get("/api/v1/channels/UCdoesnotexist")
    assert response.status_code == 404


def test_subscribe_channel_dispatches_sync(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCsub1", subscribed=False)

    with patch("app.tasks.job_tasks.execute_subscription_job") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="mock-sub-task-id")
        response = client.post("/api/v1/channels/UCsub1/subscribe")

    assert response.status_code == 200
    data = response.json()
    assert data["channel_id"] == "UCsub1"
    assert data["job_id"] is not None
    # T-5.6.5: dispatch via apply_async with per-tier queue, not raw .delay()
    mock_task.apply_async.assert_called_once()

    # D-065: subscription state is per tenant now, not a global column on
    # `channels` — assert the caller's row flipped, and only theirs.
    from app.services import subscription_service

    assert subscription_service.get_or_create(db, "UCsub1", test_user.id).subscribed is True
    assert subscription_service.get_or_create(db, "UCsub1", "someone-else").subscribed is False


def test_unsubscribe_channel(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCunsub1", subscribed=True)

    response = client.post("/api/v1/channels/UCunsub1/unsubscribe")
    assert response.status_code == 200
    assert response.json()["subscribed"] is False


def test_sync_channel_dispatches_job(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCsync1", subscribed=True)

    with patch("app.tasks.job_tasks.execute_subscription_job") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="mock-sub-task-id")
        response = client.post("/api/v1/channels/UCsync1/sync")

    assert response.status_code == 200
    data = response.json()
    assert data["channel_id"] == "UCsync1"
    assert data["job_id"] is not None
    # T-5.6.5: dispatch via apply_async with per-tier queue.
    mock_task.apply_async.assert_called_once()


def test_channel_videos_empty(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCvids1")
    response = client.get("/api/v1/channels/UCvids1/videos")
    assert response.status_code == 200
    assert response.json() == []


def test_channel_videos_lists_only_channel_videos(client, db, test_user):
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCvids2", name="Vids2")
    _seed_channel(db, tenant_id=test_user.id, channel_id="UCother", name="Other")

    from app.models.document import Document

    # Global Document rows (no job_id; channel_id is the scoping field)
    v1 = Document(
        video_id="vid1", title="one", channel_id="UCvids2",
        url="https://youtube.com/watch?v=vid1",
        duration_seconds=60, transcript_status="pending",
        created_at=datetime.now(timezone.utc),
    )
    v2 = Document(
        video_id="vid2", title="two", channel_id="UCvids2",
        url="https://youtube.com/watch?v=vid2",
        duration_seconds=60, transcript_status="pending",
        created_at=datetime.now(timezone.utc),
    )
    v_other = Document(
        video_id="other", title="other", channel_id="UCother",
        url="https://youtube.com/watch?v=other",
        duration_seconds=60, transcript_status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add_all([v1, v2, v_other])
    db.commit()

    # D-063: the listing shows only documents this tenant ingested.
    from app.services import visibility_service

    visibility_service.grant(
        db, ["vid1", "vid2", "other"], test_user.id, visibility_service.SOURCE_JOB
    )

    response = client.get("/api/v1/channels/UCvids2/videos")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {v["video_id"] for v in data} == {"vid1", "vid2"}


def test_channels_require_auth(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/channels")
    assert response.status_code == 401


def test_create_subscription_job_validates_channel_list(client):
    response = client.post("/api/v1/jobs", json={"job_type": "subscription"})
    assert response.status_code == 422


def test_create_subscription_job_dispatches(client):
    response = client.post(
        "/api/v1/jobs",
        json={"job_type": "subscription", "channel_list": ["@foo"]},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["job_type"] == "subscription"
    assert data["channel_list"] == ["@foo"]

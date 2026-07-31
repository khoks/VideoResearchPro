"""D-065 — channel subscription state is per-tenant.

`channels` kept `subscribed`, `source_weight` and `last_synced_at` globally, so
one user subscribing (or re-weighting a source for retrieval ranking) silently
changed every other user's view. The channel RECORD stays shared — its name and
subscriber count are public facts — but the state moves per tenant.
"""
import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.services import subscription_service

OTHER = "other-tenant-uuid"


@pytest.fixture
def two_tenant_channels(db, test_user):
    """One channel visible to the caller, one only to a foreign tenant."""
    mine = Channel(
        channel_id="UCmine0000000000000000",
        name="My Channel",
        creator_external_id="UCmine0000000000000000",
    )
    theirs = Channel(
        channel_id="UCtheirs00000000000000",
        name="Their Channel",
        creator_external_id="UCtheirs00000000000000",
    )
    db.add_all([mine, theirs])
    db.commit()

    d_mine = Document(
        document_id="doc-mine", video_id="minevid0001",
        channel_id=mine.channel_id, title="Mine", url="https://youtu.be/minevid0001",
    )
    d_theirs = Document(
        document_id="doc-theirs", video_id="theirvid001",
        channel_id=theirs.channel_id, title="Theirs", url="https://youtu.be/theirvid001",
    )
    db.add_all([d_mine, d_theirs])
    db.commit()
    db.add_all([
        DocumentVisibility(video_id="minevid0001", tenant_id=test_user.id, source="job"),
        DocumentVisibility(video_id="theirvid001", tenant_id=OTHER, source="job"),
    ])
    db.commit()
    return {"mine": mine, "theirs": theirs}


def test_channel_list_excludes_channels_the_tenant_cannot_see(client, two_tenant_channels):
    r = client.get("/api/v1/channels")
    assert r.status_code == 200
    ids = {c["channel_id"] for c in r.json()}
    assert "UCmine0000000000000000" in ids
    assert "UCtheirs00000000000000" not in ids


def test_subscribing_does_not_change_another_tenants_state(db, test_user, two_tenant_channels):
    ch = "UCmine0000000000000000"
    subscription_service.set_subscribed(db, ch, test_user.id, True)

    mine = subscription_service.get_or_create(db, ch, test_user.id)
    theirs = subscription_service.get_or_create(db, ch, OTHER)
    assert mine.subscribed is True
    assert theirs.subscribed is False, "one user's subscription must not follow another"


def test_source_weight_is_per_tenant(db, test_user, two_tenant_channels):
    """It was always described as a *user-set* trust score that re-ranks
    retrieval; storing it globally meant one user re-weighted everyone."""
    ch = "UCmine0000000000000000"
    mine = subscription_service.get_or_create(db, ch, test_user.id)
    mine.source_weight = 2.5
    db.commit()

    theirs = subscription_service.get_or_create(db, ch, OTHER)
    assert theirs.source_weight == 1.0


def test_sync_timestamp_is_per_subscription(db, test_user, two_tenant_channels):
    """Two tenants subscribing at different times must not skip each other's
    backlog."""
    ch = "UCmine0000000000000000"
    subscription_service.mark_synced(db, ch, test_user.id)
    assert subscription_service.get_or_create(db, ch, test_user.id).last_synced_at is not None
    assert subscription_service.get_or_create(db, ch, OTHER).last_synced_at is None


def test_state_is_created_neutral_on_first_read(db, test_user, two_tenant_channels):
    row = subscription_service.get_or_create(db, "UCmine0000000000000000", test_user.id)
    assert row.subscribed is False
    assert row.source_weight == 1.0


def test_channel_video_listing_hides_foreign_documents(client, two_tenant_channels):
    r = client.get("/api/v1/channels/UCtheirs00000000000000/videos")
    assert r.status_code == 200
    assert r.json() == [], "a foreign tenant's videos must not be listed"


def test_video_count_reflects_only_visible_documents(client, two_tenant_channels):
    """A global count would leak how much others ingested from the channel."""
    r = client.get("/api/v1/channels")
    assert r.status_code == 200
    by_id = {c["channel_id"]: c for c in r.json()}
    assert by_id["UCmine0000000000000000"]["video_count"] == 1


def test_subscribed_channel_ids_are_scoped(db, test_user, two_tenant_channels):
    ch = "UCmine0000000000000000"
    subscription_service.set_subscribed(db, ch, test_user.id, True)
    assert subscription_service.subscribed_channel_ids(db, test_user.id) == [ch]
    assert subscription_service.subscribed_channel_ids(db, OTHER) == []

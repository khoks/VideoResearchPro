"""S-8.7.4 — `GET /library/video-channels`: cited video → channel, for the
citation chip's link to the channel page. Visibility-scoped (D-063)."""
from datetime import datetime, timezone

from app.models.channel import Channel
from app.models.document import Document
from app.services import auth_service, visibility_service


def _doc(db, vid, channel_id, granted):
    d = Document(
        video_id=vid, title=vid, channel_id=channel_id, url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=60, transcript_status="fetched", created_at=datetime.now(timezone.utc),
    )
    db.add(d)
    db.commit()
    for t in granted:
        visibility_service.grant(db, [d.document_id], t)
    return d


def test_maps_only_visible_videos(client, db, test_user):
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    db.add_all([Channel(channel_id="UCcite1", name="Cite One"), Channel(channel_id="UCcite2", name="Cite Two")])
    db.commit()
    _doc(db, "citevid0001", "UCcite1", [test_user.id])
    _doc(db, "citevid0002", "UCcite2", [test_user.id, other.id])
    _doc(db, "citevid0003", "UCcite2", [other.id])  # theirs only

    r = client.get("/api/v1/library/video-channels", params={"video_ids": "citevid0001,citevid0002,citevid0003,nosuchvideo,citevid0001"})
    assert r.status_code == 200
    assert r.json() == {
        "citevid0001": {"channel_id": "UCcite1", "channel_name": "Cite One"},
        "citevid0002": {"channel_id": "UCcite2", "channel_name": "Cite Two"},
    }, "another reader's document and unknown ids are absent, not errors"


def test_empty_and_capped(client, db, test_user):
    assert client.get("/api/v1/library/video-channels", params={"video_ids": ",, ,"}).json() == {}
    db.add(Channel(channel_id="UCcap", name="Cap"))
    db.commit()
    _doc(db, "capvid00000", "UCcap", [test_user.id])
    ids = ",".join([f"fake{i:07d}" for i in range(250)] + ["capvid00000"])
    # The real id is past the cap, so it is not resolved.
    assert client.get("/api/v1/library/video-channels", params={"video_ids": ids}).json() == {}


def test_requires_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/library/video-channels", params={"video_ids": "x"}).status_code == 401

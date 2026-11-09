"""T-1.11.11.5: ``api_quota_log`` can name the lazy audio-language lookup.

It was logged as ``videos``, the same as ``get_video_details``. Two things read
that column's values, and neither may notice the new label:

- ``quota_service.OPERATION_COSTS`` prices it, and an unknown name falls back
  to 1 unit: right today, by luck;
- ``usage_service.YOUTUBE_FEATURES`` files it under a feature, and an unknown
  name falls into ``other``, which would move a tenant's figure.

``/health/quota`` reads the Redis total, which adds units and no names.

Mutation check: drop ``videos_audio_language`` from ``YOUTUBE_FEATURES`` and
``test_the_lookup_counts_as_it_did_for_the_tenant`` fails on ``other``; pass
``"videos"`` in ``get_default_audio_languages`` and the log test fails.
"""
from __future__ import annotations

from app.config import settings
from app.models.api_quota_log import ApiQuotaLog
from app.services import quota_service, usage_service, youtube_service
from tests.usage_helpers import FakeRedis, usage_rows, youtube_network  # noqa: F401  (fixture)

VIDEOS = {
    "items": [
        {
            "id": "vLabel00001",
            "snippet": {
                "title": "A talk", "channelTitle": "A channel", "channelId": "UClabel",
                "publishedAt": "2026-01-01T00:00:00Z", "description": "",
            },
            "contentDetails": {"duration": "PT10M"},
            "statistics": {},
        }
    ]
}


def _both_calls(youtube_network) -> None:  # noqa: F811
    youtube_network.responses = {"videos": VIDEOS}
    youtube_service.get_video_details(["vLabel00001"])
    youtube_service._lookup_default_audio_language("vLabel00001", "")


def test_the_log_names_the_lookup(db, youtube_network):  # noqa: F811
    _both_calls(youtube_network)

    db.expire_all()
    assert sorted((r.operation, r.units) for r in db.query(ApiQuotaLog)) == [
        ("videos", 1),
        ("videos_audio_language", 1),
    ]


def test_the_lookup_counts_as_it_did_for_the_tenant(db, test_user, youtube_network):  # noqa: F811
    with usage_service.metered(db, test_user.id):
        _both_calls(youtube_network)

    assert usage_rows(db, test_user.id) == {("video_metadata", "youtube_units"): 2}


def test_health_quota_sees_the_same_total(client, youtube_network, monkeypatch):  # noqa: F811
    redis = FakeRedis()
    monkeypatch.setattr(quota_service, "get_redis", lambda: redis)
    _both_calls(youtube_network)

    body = client.get("/api/v1/health/quota").json()

    assert body["used"] == 2
    assert body["remaining"] == settings.YOUTUBE_DAILY_QUOTA - 2


def test_a_batch_read_by_the_refetch_script_carries_the_label_per_request(db, youtube_network):  # noqa: F811
    """``refetch_dubbed_transcripts`` calls this with many ids: 1 unit per 50."""
    youtube_network.responses = {"videos": {"items": []}}

    youtube_service.get_default_audio_languages([f"v{i}" for i in range(51)])

    db.expire_all()
    assert sorted(r.operation for r in db.query(ApiQuotaLog)) == ["videos_audio_language"] * 2

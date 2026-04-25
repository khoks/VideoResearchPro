"""Tests for the L1 multi-source schema columns on `documents` and `channels`.

PR 1 introduced `source_type`, `source_id`, `source_url`, `source_metadata_json`,
`language`, `word_count`, `user_provenance_json` on `documents` (then named
`videos`) and `source_type`, `creator_external_id`, `source_weight`,
`creator_metadata_json` on `channels`. PR 4 renamed `videos` → `documents`
and the `Video` model class to `Document`; the YouTube-flavoured column
names (`video_id`, `url`) stay for back-compat.

The legacy YouTube ingest call sites are not yet aware of these columns, so
the model `__init__` overrides default `source_id` from `video_id`,
`source_url` from `url`, and `creator_external_id` from `channel_id`.
"""
from sqlalchemy.exc import IntegrityError

from app.models.channel import Channel
from app.models.document import Document


def _video(db, video_id: str = "abc123def45", **overrides) -> Document:
    kwargs = dict(
        video_id=video_id,
        title="A title",
        url=f"https://www.youtube.com/watch?v={video_id}",
        duration_seconds=300,
    )
    kwargs.update(overrides)
    v = Document(**kwargs)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _channel(db, channel_id: str = "UCabcDEFghiJKLmnoPQR", **overrides) -> Channel:
    kwargs = dict(channel_id=channel_id, name="A channel")
    kwargs.update(overrides)
    c = Channel(**kwargs)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


class TestVideoDefaults:
    def test_legacy_init_defaults_source_columns_from_youtube_fields(self, db):
        """Legacy YouTube call sites pass only `video_id`/`url`. The model must
        backfill `source_type`, `source_id`, and `source_url` automatically."""
        v = _video(db, video_id="legacy12345")
        assert v.source_type == "video"
        assert v.source_id == "legacy12345"
        assert v.source_url == "https://www.youtube.com/watch?v=legacy12345"

    def test_explicit_source_fields_take_precedence_over_defaults(self, db):
        """Future non-YouTube call sites supply their own values."""
        v = _video(
            db,
            video_id="podcast-eg-1",
            source_type="podcast",
            source_id="ep-guid-42",
            source_url="https://example.com/feed/episode-42.mp3",
            duration_seconds=None,
        )
        assert v.source_type == "podcast"
        assert v.source_id == "ep-guid-42"
        assert v.source_url == "https://example.com/feed/episode-42.mp3"
        assert v.duration_seconds is None

    def test_new_columns_are_nullable_when_not_set(self, db):
        v = _video(db)
        assert v.source_metadata_json is None
        assert v.language is None
        assert v.word_count is None
        assert v.user_provenance_json is None

    def test_unique_source_type_source_id_pair(self, db):
        """Two `video`-source rows with the same source_id are forbidden."""
        _video(db, video_id="aaa1112223")
        clash = Document(
            video_id="zzz9998887",
            title="Different title",
            url="https://www.youtube.com/watch?v=zzz9998887",
            duration_seconds=100,
            source_type="video",
            source_id="aaa1112223",
        )
        db.add(clash)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            db.rollback()
            raise AssertionError("expected IntegrityError on duplicate (source_type, source_id)")

    def test_same_source_id_under_different_source_type_is_allowed(self, db):
        """Cross-source dedup is scoped by `source_type`, not global."""
        _video(db, video_id="vidshare01")
        v2 = _video(
            db,
            video_id="podshare01",
            source_type="podcast",
            source_id="vidshare01",
        )
        assert v2.source_type == "podcast"
        assert v2.source_id == "vidshare01"


class TestChannelDefaults:
    def test_legacy_init_defaults_creator_columns_from_channel_id(self, db):
        c = _channel(db, channel_id="UClegacyAAAAAAAAAAAA")
        assert c.source_type == "video"
        assert c.creator_external_id == "UClegacyAAAAAAAAAAAA"
        assert c.source_weight == 1.0
        assert c.creator_metadata_json is None

    def test_explicit_creator_fields_take_precedence(self, db):
        c = _channel(
            db,
            channel_id="UCpodcastBBBBBBBBBBBB",
            source_type="podcast",
            creator_external_id="show-rss-uuid",
            source_weight=2.5,
        )
        assert c.source_type == "podcast"
        assert c.creator_external_id == "show-rss-uuid"
        assert c.source_weight == 2.5

"""Unit tests for the YouTube connector — verify the connector wraps
`youtube_service` correctly and produces well-shaped dataclasses.

These tests mock `youtube_service` because the connector is intentionally
a thin pass-through; we want to lock down the *shape transformation*
(provider dict → typed dataclass) and the wiring (which service function
each connector method calls), not re-test YouTube API behavior.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.sources.types import Candidate, CreatorMetadata, ExtractedText, SourceMetadata
from app.sources.video import connector as yt_connector_mod
from app.sources.video.connector import YouTubeConnector


@pytest.fixture
def yt():
    return YouTubeConnector()


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------
def test_search_converts_dicts_to_candidates(yt):
    fake_results = [
        {
            "video_id": "abc123",
            "title": "Sample title",
            "channel_id": "UCfoo",
            "channel_name": "Channel Foo",
            "published_at": "2025-01-15T10:00:00Z",
            "thumbnail_url": "https://img/abc123.jpg",
        }
    ]
    with patch.object(
        yt_connector_mod.youtube_service, "search_videos", return_value=fake_results
    ) as mock_search:
        out = yt.search("monetary policy", instructions="focus on macro", limit=5)

    mock_search.assert_called_once_with("monetary policy", max_results=5)
    assert len(out) == 1
    c = out[0]
    assert isinstance(c, Candidate)
    assert c.source_type == "video"
    assert c.source_id == "abc123"
    assert c.title == "Sample title"
    assert c.source_url == "https://www.youtube.com/watch?v=abc123"
    assert c.creator_external_id == "UCfoo"
    assert c.creator_name == "Channel Foo"
    assert c.thumbnail_url == "https://img/abc123.jpg"
    # ISO timestamp parsed and timezone-aware.
    assert c.published_at is not None
    assert c.published_at == datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)


def test_search_handles_missing_optional_fields(yt):
    """Search results sometimes omit thumbnail / channel / publish — the
    connector must not crash on a sparse provider dict."""
    fake_results = [{"video_id": "xyz789", "title": "minimal"}]
    with patch.object(
        yt_connector_mod.youtube_service, "search_videos", return_value=fake_results
    ):
        out = yt.search("anything")

    c = out[0]
    assert c.source_id == "xyz789"
    assert c.title == "minimal"
    assert c.creator_external_id is None
    assert c.creator_name is None
    assert c.published_at is None
    assert c.thumbnail_url is None


def test_search_returns_empty_list_when_no_results(yt):
    with patch.object(
        yt_connector_mod.youtube_service, "search_videos", return_value=[]
    ):
        assert yt.search("nothing matches") == []


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------
def test_list_creator_items_no_limit_uses_all_helper(yt):
    """When `limit` is None, the connector must call `get_channel_videos_all`
    (subscription job path) — not `get_channel_videos`."""
    with (
        patch.object(
            yt_connector_mod.youtube_service,
            "get_channel_videos_all",
            return_value=["v1", "v2", "v3"],
        ) as mock_all,
        patch.object(
            yt_connector_mod.youtube_service, "get_channel_videos"
        ) as mock_paged,
    ):
        out = list(yt.list_creator_items("UCfoo"))

    mock_all.assert_called_once_with("UCfoo")
    mock_paged.assert_not_called()
    assert [c.source_id for c in out] == ["v1", "v2", "v3"]
    # All should be shallow Candidates with source_type=video.
    assert all(c.source_type == "video" for c in out)
    assert all(c.title == "" for c in out)
    assert out[0].source_url == "https://www.youtube.com/watch?v=v1"


def test_list_creator_items_with_limit_uses_paged_helper(yt):
    """When `limit` is provided, the connector must call `get_channel_videos`
    (manual channel job path) — not `get_channel_videos_all`."""
    with (
        patch.object(
            yt_connector_mod.youtube_service,
            "get_channel_videos",
            return_value=["v1", "v2"],
        ) as mock_paged,
        patch.object(
            yt_connector_mod.youtube_service, "get_channel_videos_all"
        ) as mock_all,
    ):
        out = list(yt.list_creator_items("UCfoo", limit=10))

    mock_paged.assert_called_once_with("UCfoo", max_results=10)
    mock_all.assert_not_called()
    assert [c.source_id for c in out] == ["v1", "v2"]


def test_list_creator_items_returns_iterator(yt):
    """The contract promises `Iterable`; today it's a generator. Ensure
    we don't accidentally regress to a materialized list (that would
    blow memory on a big channel)."""
    with patch.object(
        yt_connector_mod.youtube_service,
        "get_channel_videos_all",
        return_value=iter(["v1"]),
    ):
        gen = yt.list_creator_items("UCfoo")
        # generators have __next__; lists don't.
        assert hasattr(gen, "__next__")


# ---------------------------------------------------------------------------
# fetch_metadata()
# ---------------------------------------------------------------------------
def test_fetch_metadata_returns_empty_for_empty_input(yt):
    """No-op shortcut — must never call `get_video_details([])`."""
    with patch.object(
        yt_connector_mod.youtube_service, "get_video_details"
    ) as mock_details:
        assert yt.fetch_metadata([]) == {}

    mock_details.assert_not_called()


def test_fetch_metadata_converts_details_to_source_metadata(yt):
    fake = {
        "abc": {
            "title": "Sample",
            "channel_id": "UCfoo",
            "channel_name": "Foo",
            "duration_seconds": 600,
            "published_at": "2025-02-01T00:00:00Z",
            "thumbnail_url": "https://img/abc.jpg",
            "view_count": 1234,
            "like_count": 56,
            "url": "https://www.youtube.com/watch?v=abc",
        }
    }
    with patch.object(
        yt_connector_mod.youtube_service, "get_video_details", return_value=fake
    ) as mock_details:
        out = yt.fetch_metadata(["abc"])

    mock_details.assert_called_once_with(["abc"])
    assert set(out.keys()) == {"abc"}
    sm = out["abc"]
    assert isinstance(sm, SourceMetadata)
    assert sm.title == "Sample"
    assert sm.creator_external_id == "UCfoo"
    assert sm.creator_name == "Foo"
    assert sm.duration_seconds == 600
    assert sm.thumbnail_url == "https://img/abc.jpg"
    assert sm.published_at == datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc)
    # extra holds the YouTube-specific bits we don't want polluting the
    # core SourceMetadata shape.
    assert sm.extra == {
        "view_count": 1234,
        "like_count": 56,
        "url": "https://www.youtube.com/watch?v=abc",
    }


def test_fetch_metadata_extra_omits_none_values(yt):
    """Provider returns `like_count: None` for videos with likes hidden;
    we shouldn't smuggle Nones into `extra`."""
    fake = {
        "abc": {
            "title": "t",
            "view_count": 10,
            "like_count": None,
            "url": "https://www.youtube.com/watch?v=abc",
        }
    }
    with patch.object(
        yt_connector_mod.youtube_service, "get_video_details", return_value=fake
    ):
        out = yt.fetch_metadata(["abc"])

    assert "like_count" not in out["abc"].extra
    assert out["abc"].extra["view_count"] == 10


# ---------------------------------------------------------------------------
# fetch_creator()
# ---------------------------------------------------------------------------
def test_fetch_creator_returns_none_when_service_returns_none(yt):
    with patch.object(
        yt_connector_mod.youtube_service, "get_channel_metadata", return_value=None
    ):
        assert yt.fetch_creator("UCfoo") is None


def test_fetch_creator_returns_none_when_service_returns_empty_dict(yt):
    with patch.object(
        yt_connector_mod.youtube_service, "get_channel_metadata", return_value={}
    ):
        assert yt.fetch_creator("UCfoo") is None


def test_fetch_creator_converts_to_creator_metadata(yt):
    fake = {
        "name": "Channel Foo",
        "url": "https://www.youtube.com/channel/UCfoo",
        "description": "Macro analysis",
        "subscriber_count": 100_000,
        "uploads_playlist_id": "UUfoo",
    }
    with patch.object(
        yt_connector_mod.youtube_service, "get_channel_metadata", return_value=fake
    ) as mock_meta:
        out = yt.fetch_creator("UCfoo")

    mock_meta.assert_called_once_with("UCfoo")
    assert isinstance(out, CreatorMetadata)
    assert out.creator_external_id == "UCfoo"
    assert out.name == "Channel Foo"
    assert out.url == "https://www.youtube.com/channel/UCfoo"
    assert out.description == "Macro analysis"
    assert out.subscriber_count == 100_000
    assert out.extra == {"uploads_playlist_id": "UUfoo"}


# ---------------------------------------------------------------------------
# fetch_text()
# ---------------------------------------------------------------------------
def _candidate(source_id: str = "abc123") -> Candidate:
    return Candidate(
        source_type="video",
        source_id=source_id,
        title="t",
        source_url=f"https://www.youtube.com/watch?v={source_id}",
    )


def test_fetch_text_returns_none_on_unavailable_transcript(yt):
    """`fetch_transcript` returns None when no transcript exists and
    Whisper fallback also failed. The connector must propagate that as
    None — orchestrator marks the doc as `transcript_status='failed'`."""
    with patch.object(
        yt_connector_mod.youtube_service, "fetch_transcript", return_value=None
    ):
        assert yt.fetch_text(_candidate(), job_id="job-1") is None


def test_fetch_text_returns_extracted_text_on_success(yt):
    segments = [
        {"text": "hello world", "start": 0.0, "duration": 1.5},
        {"text": "foo bar baz", "start": 1.5, "duration": 2.0},
    ]
    with patch.object(
        yt_connector_mod.youtube_service,
        "fetch_transcript",
        return_value=(segments, "en"),
    ) as mock_fetch:
        out = yt.fetch_text(_candidate("abc123"), job_id="job-42")

    # The connector forwards source_id and job_id; language comes from settings.
    assert mock_fetch.call_count == 1
    args, kwargs = mock_fetch.call_args
    assert args == ("abc123",)
    assert kwargs["job_id"] == "job-42"
    assert "language" in kwargs

    assert isinstance(out, ExtractedText)
    assert out.segments == segments
    assert out.language == "en"
    # text_source is currently hardcoded to "youtube" — see the connector
    # docstring on the future Whisper-vs-API distinction.
    assert out.text_source == "youtube"
    # Word count = "hello" + "world" + "foo" + "bar" + "baz" = 5
    assert out.word_count == 5


def test_fetch_text_handles_segments_without_text(yt):
    """Defensive: a malformed segment dict shouldn't crash word_count."""
    segments = [
        {"text": "ok", "start": 0.0, "duration": 1.0},
        {"start": 1.0, "duration": 1.0},  # no "text" key
        {"text": "", "start": 2.0, "duration": 1.0},  # empty text
    ]
    with patch.object(
        yt_connector_mod.youtube_service,
        "fetch_transcript",
        return_value=(segments, "en"),
    ):
        out = yt.fetch_text(_candidate())

    assert out is not None
    assert out.word_count == 1  # only "ok"


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------
def test_connector_source_type_is_video():
    """Locks the source_type discriminator — changing this would silently
    break every job in the database that has `source_type='video'`."""
    assert YouTubeConnector.source_type == "video"

"""Unit tests for the podcast connector + flatten + client.

Strategy mirrors the social-media connectors: mock the underlying
client + Whisper round-trip so tests cover *shape transformation*
(iTunes JSON / RSS feed / Whisper response → typed dataclasses) and
*wiring* (which client method each connector method calls).

No network calls, no Whisper API calls. Tests run in <1 second.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import feedparser
import httpx
import pytest

from app.services import source_failure, youtube_service
from app.sources import registry
from app.sources.podcast import client as podcast_client_mod
from app.sources.podcast import connector as podcast_connector_mod
from app.sources.podcast import flatten as podcast_flatten
from app.sources.podcast.client import PodcastClient, _itunes_id_from_url
from app.sources.podcast.connector import (
    PodcastConnector,
    _parse_itunes_duration,
)
from app.sources.types import Candidate, ExtractedText


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def podcast():
    return PodcastConnector()


@pytest.fixture
def fake_client():
    return Mock(spec=PodcastClient)


# Minimal RSS-2.0 feed with iTunes namespace + one episode. feedparser
# tolerates much messier shapes; we keep this clean for readability.
RSS_FEED_WITH_ENCLOSURE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>The Test Show</title>
    <link>https://testshow.example.com/</link>
    <language>en</language>
    <itunes:author>Alice Host</itunes:author>
    <itunes:summary>A show about software.</itunes:summary>
    <item>
      <title>Episode 1: Hello</title>
      <link>https://testshow.example.com/ep1</link>
      <guid>https://testshow.example.com/ep1</guid>
      <pubDate>Mon, 15 Jan 2024 12:00:00 GMT</pubDate>
      <description>First episode summary.</description>
      <enclosure url="https://cdn.testshow.example.com/ep1.mp3" type="audio/mpeg" length="100000" />
      <itunes:duration>00:42:30</itunes:duration>
      <itunes:episode>1</itunes:episode>
    </item>
  </channel>
</rss>
"""

RSS_FEED_TWO_EPISODES = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Multi Show</title>
    <link>https://multi.example.com/</link>
    <language>en</language>
    <item>
      <title>Episode A</title>
      <guid>guid-a</guid>
      <pubDate>Mon, 15 Jan 2024 12:00:00 GMT</pubDate>
      <enclosure url="https://cdn.multi.example.com/a.mp3" type="audio/mpeg" />
    </item>
    <item>
      <title>Episode B</title>
      <guid>guid-b</guid>
      <pubDate>Mon, 22 Jan 2024 12:00:00 GMT</pubDate>
      <enclosure url="https://cdn.multi.example.com/b.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
"""


def _parse(rss_xml: str) -> dict:
    """Parse an RSS string the way `client.fetch_feed` does."""
    return feedparser.parse(rss_xml)


# ---------------------------------------------------------------------------
# iTunes ID extraction
# ---------------------------------------------------------------------------


def test_itunes_id_from_url_extracts_trailing_id():
    assert (
        _itunes_id_from_url(
            "https://podcasts.apple.com/us/podcast/some-show/id1234567890"
        )
        == "1234567890"
    )


def test_itunes_id_from_url_handles_trailing_slash():
    assert (
        _itunes_id_from_url(
            "https://podcasts.apple.com/us/podcast/some-show/id999/"
        )
        == "999"
    )


def test_itunes_id_from_url_handles_query_string():
    assert (
        _itunes_id_from_url(
            "https://podcasts.apple.com/us/podcast/show/id42?i=10"
        )
        == "42"
    )


def test_itunes_id_from_url_returns_none_on_non_apple_url():
    assert _itunes_id_from_url("https://example.com/feed.rss") is None
    assert _itunes_id_from_url("") is None


# ---------------------------------------------------------------------------
# Duration parser
# ---------------------------------------------------------------------------


def test_parse_itunes_duration_hms():
    assert _parse_itunes_duration("01:02:03") == 3723


def test_parse_itunes_duration_ms():
    assert _parse_itunes_duration("42:30") == 42 * 60 + 30


def test_parse_itunes_duration_bare_seconds():
    assert _parse_itunes_duration("3600") == 3600


def test_parse_itunes_duration_invalid_returns_none():
    assert _parse_itunes_duration("") is None
    assert _parse_itunes_duration("forty-two") is None
    assert _parse_itunes_duration(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


def test_search_returns_empty_when_query_blank(podcast, fake_client):
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.search("   ") == []
    fake_client.itunes_search.assert_not_called()


def test_search_combines_itunes_shows_and_rss_episodes(podcast, fake_client):
    """Two iTunes results × one episode each = 2 candidates."""
    fake_client.itunes_search.return_value = {
        "resultCount": 2,
        "results": [
            {
                "collectionName": "Show A",
                "artistName": "Host A",
                "feedUrl": "https://a.example.com/feed.rss",
            },
            {
                "collectionName": "Show B",
                "artistName": "Host B",
                "feedUrl": "https://b.example.com/feed.rss",
            },
        ],
    }
    fake_client.fetch_feed.side_effect = [
        _parse(RSS_FEED_WITH_ENCLOSURE),
        _parse(RSS_FEED_WITH_ENCLOSURE),
    ]

    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("software", limit=20)

    assert len(out) == 2
    assert all(isinstance(c, Candidate) for c in out)
    assert all(c.source_type == "podcast_episode" for c in out)
    # Each candidate's source_id is `podcast:<guid>`.
    assert all(c.source_id.startswith("podcast:") for c in out)
    # Show name surfaces as creator_name
    assert {c.creator_name for c in out} == {"Show A", "Show B"}


def test_search_yields_at_most_limit(podcast, fake_client):
    """If iTunes returns 3 shows × 5 episodes each, we still cap at limit."""
    fake_client.itunes_search.return_value = {
        "resultCount": 3,
        "results": [
            {"collectionName": f"S{i}", "feedUrl": f"https://s{i}.example.com/f.rss"}
            for i in range(3)
        ],
    }
    fake_client.fetch_feed.side_effect = [
        _parse(RSS_FEED_TWO_EPISODES),
        _parse(RSS_FEED_TWO_EPISODES),
        _parse(RSS_FEED_TWO_EPISODES),
    ]
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("anything", limit=4)
    assert len(out) == 4


def _show_feed(name: str, episodes: int) -> dict:
    return {
        "feed": {"title": name},
        "entries": [
            {
                "id": f"{name}-{i}",
                "title": f"{name}{i}",
                "enclosures": [{"href": f"https://cdn.example.com/{name}-{i}.mp3"}],
            }
            for i in range(episodes)
        ],
    }


def _titles_found(podcast, fake_client, shows: dict[str, int], limit: int) -> list[str]:
    fake_client.itunes_search.return_value = {
        "results": [
            {"collectionName": name, "feedUrl": f"https://{name}.example.com/f"}
            for name in shows
        ],
    }
    fake_client.fetch_feed.side_effect = [_show_feed(n, count) for n, count in shows.items()]
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        return [c.title for c in podcast.search("anything", limit=limit)]


@pytest.mark.parametrize(
    "limit, expected",
    [
        (1, ["A0"]),
        (6, ["A0", "B0", "C0", "A1", "B1", "C1"]),
        (8, ["A0", "B0", "C0", "A1", "B1", "C1", "A2", "B2"]),
        (15, [f"{show}{i}" for i in range(5) for show in "ABC"]),
    ],
)
def test_search_takes_each_shows_newest_episodes_in_turn(podcast, fake_client, limit, expected):
    """A run's share is small (6 in the debate starter) and a show gives up to 5
    episodes, so filling it show by show would make it one show's back catalogue."""
    assert _titles_found(podcast, fake_client, {"A": 5, "B": 5, "C": 5}, limit) == expected


def test_search_lets_other_shows_fill_what_a_short_show_cannot(podcast, fake_client):
    assert _titles_found(podcast, fake_client, {"A": 1, "B": 5}, 4) == ["A0", "B0", "B1", "B2"]


def test_search_skips_results_without_feed_url(podcast, fake_client):
    """iTunes occasionally returns matches without feedUrl; skip them."""
    fake_client.itunes_search.return_value = {
        "results": [
            {"collectionName": "No Feed Show"},  # missing feedUrl
            {"collectionName": "Real Show", "feedUrl": "https://real.example.com/f.rss"},
        ],
    }
    fake_client.fetch_feed.return_value = _parse(RSS_FEED_WITH_ENCLOSURE)
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("x", limit=10)
    # Only the real show contributed an episode.
    assert len(out) == 1
    fake_client.fetch_feed.assert_called_once_with(
        "https://real.example.com/f.rss"
    )


def test_search_isolates_per_show_feed_failures(podcast, fake_client):
    """One show's feed-fetch error must not poison the whole search."""
    fake_client.itunes_search.return_value = {
        "results": [
            {"collectionName": "Bad Show", "feedUrl": "https://bad.example.com/f"},
            {"collectionName": "Good Show", "feedUrl": "https://good.example.com/f"},
        ],
    }
    fake_client.fetch_feed.side_effect = [
        RuntimeError("DNS failed"),
        _parse(RSS_FEED_WITH_ENCLOSURE),
    ]
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("x", limit=10)
    assert len(out) == 1
    assert out[0].creator_name == "Good Show"


def test_search_lets_an_itunes_failure_through(podcast, fake_client):
    """An empty list means nothing was found, so a failure stays raised for
    the dispatcher to report (T-1.5.14.1)."""
    fake_client.itunes_search.side_effect = RuntimeError("upstream 503")
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ), pytest.raises(RuntimeError):
        podcast.search("anything")


def test_search_candidate_carries_duration_and_published_at(podcast, fake_client):
    fake_client.itunes_search.return_value = {
        "results": [
            {"collectionName": "S", "feedUrl": "https://s.example.com/f.rss"},
        ],
    }
    fake_client.fetch_feed.return_value = _parse(RSS_FEED_WITH_ENCLOSURE)
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("x")
    c = out[0]
    assert c.duration_seconds == 42 * 60 + 30  # from itunes:duration
    assert c.published_at is not None
    assert c.published_at.tzinfo is not None
    assert c.published_at.year == 2024


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------


def test_list_creator_items_yields_iterator(podcast, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_FEED_TWO_EPISODES)
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        gen = podcast.list_creator_items("https://multi.example.com/f.rss")
        assert hasattr(gen, "__next__")
        first = next(gen)
        assert first.title == "Episode A"


def test_list_creator_items_returns_nothing_for_empty_creator_id(podcast, fake_client):
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = list(podcast.list_creator_items(""))
    assert out == []
    fake_client.fetch_feed.assert_not_called()


def test_list_creator_items_returns_nothing_when_feed_fails(podcast, fake_client):
    fake_client.fetch_feed.side_effect = httpx.ConnectError("DNS")
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = list(podcast.list_creator_items("https://broken.example.com/f"))
    assert out == []


def test_list_creator_items_respects_limit(podcast, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_FEED_TWO_EPISODES)
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = list(podcast.list_creator_items("https://x.example.com/f", limit=1))
    assert len(out) == 1


# ---------------------------------------------------------------------------
# resolve_creator_id()
# ---------------------------------------------------------------------------


def test_resolve_creator_id_passes_through_direct_rss_url(podcast, fake_client):
    """A direct RSS URL is returned as-is — no iTunes round-trip."""
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        got = podcast.resolve_creator_id("https://show.example.com/feed.rss")
    assert got == "https://show.example.com/feed.rss"
    fake_client.itunes_lookup.assert_not_called()


def test_resolve_creator_id_resolves_apple_podcasts_url(podcast, fake_client):
    fake_client.itunes_lookup.return_value = {
        "results": [
            {
                "collectionName": "S",
                "feedUrl": "https://show.example.com/feed.rss",
            }
        ]
    }
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        got = podcast.resolve_creator_id(
            "https://podcasts.apple.com/us/podcast/show/id1234567890"
        )
    fake_client.itunes_lookup.assert_called_once_with("1234567890")
    assert got == "https://show.example.com/feed.rss"


def test_resolve_creator_id_returns_none_on_lookup_failure(podcast, fake_client):
    fake_client.itunes_lookup.side_effect = RuntimeError("lookup 500")
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        got = podcast.resolve_creator_id(
            "https://podcasts.apple.com/us/podcast/show/id1"
        )
    assert got is None


def test_resolve_creator_id_returns_none_for_empty_hint(podcast, fake_client):
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.resolve_creator_id("") is None
    fake_client.itunes_lookup.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_creator()
# ---------------------------------------------------------------------------


def test_fetch_creator_returns_show_metadata(podcast, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_FEED_WITH_ENCLOSURE)
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        cm = podcast.fetch_creator("https://testshow.example.com/feed.rss")
    assert cm is not None
    assert cm.name == "The Test Show"
    assert cm.url == "https://testshow.example.com/"


def test_fetch_creator_returns_none_when_feed_fetch_fails(podcast, fake_client):
    fake_client.fetch_feed.side_effect = httpx.ConnectError("DNS")
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.fetch_creator("https://x.example.com/f") is None


# ---------------------------------------------------------------------------
# fetch_text() — in-feed transcript path
# ---------------------------------------------------------------------------


SRT_BODY = """\
1
00:00:01,000 --> 00:00:05,500
Hello world.

2
00:00:05,500 --> 00:00:10,000
This is a test transcript.
"""


def _candidate_for_ep1() -> Candidate:
    return Candidate(
        source_type="podcast_episode",
        source_id="podcast:https://testshow.example.com/ep1",
        title="Episode 1: Hello",
        source_url="https://testshow.example.com/ep1",
        creator_external_id="https://testshow.example.com/feed.rss",
        creator_name="The Test Show",
    )


def test_fetch_text_uses_in_feed_transcript_when_available(podcast, fake_client):
    """When the feed advertises a `<podcast:transcript>` SRT, we use
    it directly without invoking Whisper."""
    # Synthesise a feed dict with the transcript on the entry. We
    # bypass feedparser for this test because feedparser's namespace
    # handling for the `podcast:` namespace varies across versions.
    fake_feed = {
        "feed": {"title": "The Test Show", "language": "en"},
        "entries": [
            {
                "id": "https://testshow.example.com/ep1",
                "title": "Episode 1: Hello",
                "link": "https://testshow.example.com/ep1",
                "podcast_transcript": {
                    "url": "https://testshow.example.com/ep1.srt",
                    "type": "application/srt",
                },
                "enclosures": [
                    {"href": "https://cdn.testshow.example.com/ep1.mp3"}
                ],
            }
        ],
    }
    fake_client.fetch_feed.return_value = fake_feed

    transcript_resp = Mock()
    transcript_resp.text = SRT_BODY
    transcript_resp.raise_for_status = Mock()

    with (
        patch.object(
            podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
        ),
        patch.object(
            podcast_connector_mod.httpx,
            "get",
            return_value=transcript_resp,
        ),
    ):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert isinstance(out, ExtractedText)
    assert out.text_source == "podcast_transcript"
    # SRT had two segments; flatten + extra-attach preserves both.
    assert len(out.segments) == 2
    assert "Hello world" in out.segments[0]["text"]
    assert "test transcript" in out.segments[1]["text"]
    # Per-segment extra carries comment_url with #t= fragment.
    extra0 = out.segments[0]["extra"]
    assert extra0["kind"] == "audio_segment"
    assert extra0["comment_id"] == "https://testshow.example.com/ep1"
    assert extra0["comment_url"].endswith("#t=1")  # start=1.0


def test_fetch_text_falls_through_to_whisper_when_no_transcript(podcast, fake_client):
    """No `<podcast:transcript>` → connector downloads audio and
    invokes the Whisper helper."""
    fake_feed = {
        "feed": {"title": "The Test Show"},
        "entries": [
            {
                "id": "https://testshow.example.com/ep1",
                "title": "Episode 1: Hello",
                "link": "https://testshow.example.com/ep1",
                "enclosures": [
                    {"href": "https://cdn.testshow.example.com/ep1.mp3"}
                ],
            }
        ],
    }
    fake_client.fetch_feed.return_value = fake_feed
    fake_client.fetch_audio_to_file.side_effect = _writes(b"fake-mp3-bytes")

    # Mock the Whisper round-trip. We patch at the function-import
    # boundary inside the connector module so the test doesn't have
    # to set up the real OpenAI client.
    fake_response = Mock()
    fake_response.segments = [
        {"start": 0.0, "end": 3.0, "text": "Whisper says hello."},
        {"start": 3.0, "end": 6.0, "text": "Second whisper segment."},
    ]

    with (
        patch.object(
            podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
        ),
        # Pretend OPENAI_API_KEY is set
        patch.object(podcast_connector_mod.settings, "OPENAI_API_KEY", "sk-fake"),
        patch(
            "app.services.youtube_service._whisper_transcribe_with_retry",
            return_value=fake_response,
        ) as mock_whisper,
        patch("app.sources.podcast.connector.OpenAI", create=True),
    ):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert isinstance(out, ExtractedText)
    assert out.text_source == "podcast_whisper"
    assert len(out.segments) == 2
    mock_whisper.assert_called_once()


def _writes(data: bytes):
    """A ``fetch_audio_to_file`` that delivers ``data`` to the path it is given."""

    def fetch(url, path):
        with open(path, "wb") as f:
            f.write(data)
        return len(data)

    return fetch


def _segment(text: str, start: float, end: float) -> SimpleNamespace:
    """A segment as the OpenAI SDK returns it: read by attribute."""
    return SimpleNamespace(text=text, start=start, end=end)


def _whisper_says(*segments: SimpleNamespace, duration: float) -> SimpleNamespace:
    return SimpleNamespace(language="en", duration=duration, segments=list(segments))


@pytest.fixture
def long_episode(fake_client, tmp_path, monkeypatch):
    """An episode with no transcript, whose audio is past the upload cap and
    splits into two chunks of 100 s with 10 s shared between them. Yields the
    chunk paths."""
    fake_client.fetch_feed.return_value = {
        "feed": {"title": "The Test Show"},
        "entries": [
            {
                "id": "https://testshow.example.com/ep1",
                "title": "Episode 1: Hello",
                "link": "https://testshow.example.com/ep1",
                "enclosures": [{"href": "https://cdn.testshow.example.com/ep1.mp3"}],
            }
        ],
    }
    fake_client.fetch_audio_to_file.side_effect = _writes(b"x" * 9)
    chunks = [tmp_path / "chunk0.mp3", tmp_path / "chunk1.mp3"]
    for chunk in chunks:
        chunk.write_bytes(b"x")
    monkeypatch.setattr(youtube_service, "WHISPER_MAX_FILE_BYTES", 8)
    monkeypatch.setattr(youtube_service.settings, "WHISPER_SEGMENT_OVERLAP_SECONDS", 10.0)
    monkeypatch.setattr(podcast_connector_mod.settings, "OPENAI_API_KEY", "sk-fake")
    monkeypatch.setattr(
        youtube_service,
        "_split_audio_for_whisper",
        lambda path, tmpdir, tag: [(str(chunks[0]), 0.0), (str(chunks[1]), 100.0)],
    )
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        yield chunks


def test_fetch_text_splits_an_episode_past_the_whisper_upload_cap(podcast, long_episode):
    """D-033's known limitation. Sent whole, Whisper refuses such a file and the
    episode is lost, which is most long shows. Each chunk goes instead, and the
    words land on one timeline with the shared 10 s kept once."""
    answers = {
        str(long_episode[0]): _whisper_says(
            _segment("Opening.", 0.0, 90.0),
            _segment("Said at the seam.", 103.0, 106.0),
            duration=110.0,
        ),
        str(long_episode[1]): _whisper_says(
            _segment("Said at the seam.", 3.0, 6.0),
            _segment("Closing.", 40.0, 50.0),
            duration=100.0,
        ),
    }
    sent: list[str] = []

    def whisper(client, path, label, tag, size_mb):
        sent.append(path)
        return answers[path]

    with patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=whisper):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert sent == [str(chunk) for chunk in long_episode], "chunks, never the whole file"
    assert out.text_source == "podcast_whisper"
    assert [(s["text"], s["start"], s["duration"]) for s in out.segments] == [
        ("Opening.", 0.0, 90.0),
        ("Said at the seam.", 103.0, 3.0),
        ("Closing.", 140.0, 10.0),
    ]
    assert out.segments[-1]["extra"]["comment_url"].endswith("#t=140")
    assert out.word_count == 6


def test_fetch_text_leaves_audio_at_the_cap_in_one_request(podcast, fake_client, long_episode):
    fake_client.fetch_audio_to_file.side_effect = _writes(b"x" * 8)
    answer = Mock(segments=[{"start": 0.0, "end": 3.0, "text": "Short episode."}])
    with (
        patch.object(youtube_service, "_transcribe_in_chunks") as in_chunks,
        patch.object(youtube_service, "_whisper_transcribe_with_retry", return_value=answer) as whisper,
    ):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    in_chunks.assert_not_called()
    whisper.assert_called_once()
    assert [s["text"] for s in out.segments] == ["Short episode."]


def test_fetch_text_loses_an_oversize_episode_it_cannot_split(podcast, long_episode, monkeypatch):
    """No ffmpeg, say. Sending it whole would only be refused."""
    monkeypatch.setattr(youtube_service, "_split_audio_for_whisper", lambda path, tmpdir, tag: None)
    with patch.object(youtube_service, "_whisper_transcribe_with_retry") as whisper:
        assert podcast.fetch_text(_candidate_for_ep1(), job_id="j1") is None
    whisper.assert_not_called()


def test_fetch_text_loses_the_episode_when_a_chunk_fails(podcast, long_episode):
    """A transcript with a hole would read as the whole episode, so there is
    no text. The chunk before the failure was billed, so the job is told."""
    answers = [_whisper_says(_segment("Opening.", 0.0, 90.0), duration=110.0), RuntimeError("refused")]
    with (
        patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=answers),
        pytest.raises(source_failure.TranscriptionCutShort),
    ):
        podcast.fetch_text(_candidate_for_ep1(), job_id="j1")


def test_a_first_chunk_failure_has_nothing_to_report(podcast, long_episode):
    with patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=RuntimeError("refused")):
        assert podcast.fetch_text(_candidate_for_ep1(), job_id="j1") is None


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="needs ffmpeg and ffprobe",
)
def test_a_real_mp3_splits_under_the_cap_and_covers_the_episode(podcast, fake_client, tmp_path, monkeypatch):
    """The fakes above stop at `_split_audio_for_whisper`. This runs it on a real
    mp3, in the file name the connector gives an enclosure."""
    audio = tmp_path / "source.mp3"
    made = subprocess.run(
        [
            shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=150",
            "-c:a", "libmp3lame", "-b:a", "128k", str(audio),
        ],
        capture_output=True,
    )
    if made.returncode != 0:
        pytest.skip("this ffmpeg cannot encode mp3")
    # 150 s at 128 kbps is about 2.4 MB, so a 1 MB cap stands in for 25 MB.
    cap = 1024 * 1024
    monkeypatch.setattr(youtube_service, "WHISPER_MAX_FILE_BYTES", cap)
    monkeypatch.setattr(youtube_service.settings, "WHISPER_SEGMENT_TARGET_MB", 1)
    monkeypatch.setattr(youtube_service.settings, "WHISPER_SEGMENT_OVERLAP_SECONDS", 5.0)
    monkeypatch.setattr(podcast_connector_mod.settings, "OPENAI_API_KEY", "sk-fake")
    fake_client.fetch_feed.return_value = {
        "feed": {"title": "The Test Show"},
        "entries": [
            {
                "id": "https://testshow.example.com/ep1",
                "title": "Episode 1: Hello",
                "link": "https://testshow.example.com/ep1",
                "enclosures": [{"href": "https://cdn.testshow.example.com/ep1.mp3"}],
            }
        ],
    }
    fake_client.fetch_audio_to_file.side_effect = _writes(audio.read_bytes())
    sizes: list[int] = []

    def whisper(client, path, label, tag, size_mb):
        sizes.append(os.path.getsize(path))
        duration = youtube_service._probe_audio_duration(path, "")
        return _whisper_says(_segment(f"chunk {len(sizes)}", 10.0, duration), duration=duration)

    with (
        patch.object(podcast_connector_mod.podcast_client, "get_client", return_value=fake_client),
        patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=whisper),
    ):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert len(sizes) == 3 and max(sizes) <= cap
    last = out.segments[-1]
    assert [s["text"] for s in out.segments] == ["chunk 1", "chunk 2", "chunk 3"]
    assert last["start"] + last["duration"] == pytest.approx(150.0, abs=1.0)


def test_fetch_text_never_whispers_when_whisper_is_not_allowed(podcast, fake_client):
    """S-1.5.13: a topic run's search phase passes allow_whisper=False, so an
    episode without an in-feed transcript is left for extraction (where the
    job's WHISPER_MAX_PER_JOB applies) instead of being transcribed before
    the reader approves anything."""
    fake_client.fetch_feed.return_value = {
        "feed": {"title": "The Test Show"},
        "entries": [
            {
                "id": "https://testshow.example.com/ep1",
                "title": "Episode 1: Hello",
                "link": "https://testshow.example.com/ep1",
                "enclosures": [{"href": "https://cdn.testshow.example.com/ep1.mp3"}],
            }
        ],
    }
    with (
        patch.object(
            podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
        ),
        patch.object(podcast_connector_mod.settings, "OPENAI_API_KEY", "sk-fake"),
        patch.object(podcast_connector_mod, "_whisper_transcribe_audio") as mock_whisper,
    ):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1", allow_whisper=False)

    assert out is None
    mock_whisper.assert_not_called()
    fake_client.fetch_audio_to_file.assert_not_called()


def test_fetch_text_returns_none_when_openai_key_unset_and_no_transcript(
    podcast, fake_client
):
    """No transcript + no OPENAI_API_KEY → fail-soft None."""
    fake_feed = {
        "feed": {"title": "X"},
        "entries": [
            {
                "id": "g",
                "title": "T",
                "link": "https://x.example.com/g",
                "enclosures": [{"href": "https://x.example.com/g.mp3"}],
            }
        ],
    }
    fake_client.fetch_feed.return_value = fake_feed
    cand = Candidate(
        source_type="podcast_episode",
        source_id="podcast:g",
        title="T",
        source_url="https://x.example.com/g",
        creator_external_id="https://x.example.com/f",
    )
    with (
        patch.object(
            podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
        ),
        patch.object(podcast_connector_mod.settings, "OPENAI_API_KEY", ""),
    ):
        out = podcast.fetch_text(cand, job_id="j1")
    assert out is None


def test_fetch_text_returns_none_when_no_feed_url(podcast, fake_client):
    cand = Candidate(
        source_type="podcast_episode",
        source_id="podcast:g",
        title="T",
        source_url="https://x.example.com/g",
        creator_external_id="",  # missing
    )
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.fetch_text(cand) is None


def test_fetch_text_returns_none_when_entry_not_in_feed(podcast, fake_client):
    """If the candidate's GUID doesn't appear in the current feed
    (episode was deleted, GUID changed), fail-soft None."""
    fake_client.fetch_feed.return_value = _parse(RSS_FEED_TWO_EPISODES)
    cand = Candidate(
        source_type="podcast_episode",
        source_id="podcast:guid-that-doesnt-exist",
        title="T",
        source_url="https://x.example.com/missing",
        creator_external_id="https://multi.example.com/f.rss",
    )
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.fetch_text(cand) is None


def test_fetch_text_returns_none_when_feed_fetch_raises(podcast, fake_client):
    fake_client.fetch_feed.side_effect = httpx.ConnectError("DNS")
    cand = Candidate(
        source_type="podcast_episode",
        source_id="podcast:g",
        title="T",
        source_url="https://x.example.com/g",
        creator_external_id="https://broken.example.com/f.rss",
    )
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.fetch_text(cand) is None


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------


def test_connector_source_type_is_podcast_episode():
    assert PodcastConnector.source_type == "podcast_episode"


def test_connector_registers_under_podcast_episode():
    from app.sources.podcast import connector as _  # noqa: F401

    got = registry.connector_for("podcast_episode")
    assert isinstance(got, PodcastConnector)


# ---------------------------------------------------------------------------
# Flatten module: SRT parsing
# ---------------------------------------------------------------------------


def test_parse_srt_handles_two_block_transcript():
    segs = podcast_flatten.parse_srt(SRT_BODY)
    assert len(segs) == 2
    assert segs[0]["text"] == "Hello world."
    assert segs[0]["start"] == 1.0
    assert segs[0]["duration"] == 4.5  # 5.5 - 1.0
    assert segs[1]["text"] == "This is a test transcript."


def test_parse_srt_returns_empty_for_empty_input():
    assert podcast_flatten.parse_srt("") == []
    assert podcast_flatten.parse_srt("not srt-shaped") == []


def test_parse_vtt_strips_webvtt_header():
    vtt = "WEBVTT\n\n" + SRT_BODY
    segs = podcast_flatten.parse_vtt(vtt)
    assert len(segs) == 2
    assert segs[0]["text"] == "Hello world."


def test_whisper_segments_to_canonical_normalises_end_to_duration():
    whisper_out = [
        {"start": 0.0, "end": 5.0, "text": "first"},
        {"start": 5.0, "end": 12.5, "text": "second"},
    ]
    segs = podcast_flatten.whisper_segments_to_canonical(whisper_out)
    assert len(segs) == 2
    assert segs[0]["duration"] == 5.0
    assert segs[1]["duration"] == 7.5


def test_whisper_segments_to_canonical_skips_empty_text():
    whisper_out = [
        {"start": 0.0, "end": 1.0, "text": ""},
        {"start": 1.0, "end": 2.0, "text": "real"},
    ]
    segs = podcast_flatten.whisper_segments_to_canonical(whisper_out)
    assert len(segs) == 1
    assert segs[0]["text"] == "real"


def test_attach_episode_extra_synthesises_t_fragment():
    raw = [
        {"text": "Hello", "start": 7.0, "duration": 3.0},
        {"text": "World", "start": 10.0, "duration": 4.0},
    ]
    out = podcast_flatten.attach_episode_extra(
        raw,
        "https://show.example.com/ep1",
        "Alice Host",
    )
    assert out[0]["extra"]["comment_url"] == "https://show.example.com/ep1#t=7"
    assert out[1]["extra"]["comment_url"] == "https://show.example.com/ep1#t=10"
    assert out[0]["extra"]["author"] == "Alice Host"


def test_attach_episode_extra_handles_missing_episode_url():
    raw = [{"text": "x", "start": 0, "duration": 1}]
    out = podcast_flatten.attach_episode_extra(raw, "", "")
    assert out[0]["extra"]["comment_url"] == ""


# ---------------------------------------------------------------------------
# Client: HTTP smoke tests
# ---------------------------------------------------------------------------


def test_client_itunes_search_hits_search_endpoint():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"results": []}
    api_resp.raise_for_status = Mock()

    with patch.object(podcast_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = PodcastClient()
        c.itunes_search("rust async", limit=5)

    called_url = mock_get.call_args.args[0]
    assert called_url == "https://itunes.apple.com/search"
    params = mock_get.call_args.kwargs["params"]
    assert params == {"term": "rust async", "entity": "podcast", "limit": 5}


def test_client_itunes_search_clamps_limit_to_200():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"results": []}
    api_resp.raise_for_status = Mock()
    with patch.object(podcast_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = PodcastClient()
        c.itunes_search("x", limit=500)
    assert mock_get.call_args.kwargs["params"]["limit"] == 200


def test_client_fetch_feed_returns_parsed_dict():
    api_resp = Mock(status_code=200)
    api_resp.content = RSS_FEED_WITH_ENCLOSURE.encode("utf-8")
    api_resp.raise_for_status = Mock()

    with patch.object(podcast_client_mod.httpx, "get", return_value=api_resp):
        c = PodcastClient()
        feed = c.fetch_feed("https://example.com/f.rss")

    # FeedParserDict supports both dict and attr access
    assert feed["feed"]["title"] == "The Test Show"
    assert len(feed["entries"]) == 1


@contextmanager
def _streamed(chunks, *, fail: Exception | None = None):
    """What ``httpx.stream`` yields: chunks arrive one at a time, and a
    connection can drop after any of them."""

    def iter_bytes(chunk_size=None):
        yield from chunks
        if fail is not None:
            raise fail

    yield Mock(raise_for_status=Mock(), iter_bytes=iter_bytes)


def test_client_streams_audio_to_the_file_it_is_given(tmp_path):
    """T-1.7.1.2: to disk a chunk at a time, not one 150 MB ``resp.content``."""
    dest = tmp_path / "ep.mp3"
    with patch.object(
        podcast_client_mod.httpx, "stream", return_value=_streamed([b"audio-", b"bytes"])
    ) as stream:
        written = PodcastClient().fetch_audio_to_file("https://cdn.example.com/x.mp3", str(dest))

    assert written == 11
    assert dest.read_bytes() == b"audio-bytes"
    assert stream.call_args.args == ("GET", "https://cdn.example.com/x.mp3")
    assert stream.call_args.kwargs["follow_redirects"] is True


def test_client_stops_a_download_that_never_ends(tmp_path, monkeypatch):
    monkeypatch.setattr(podcast_client_mod, "AUDIO_MAX_BYTES", 5)
    with patch.object(
        podcast_client_mod.httpx, "stream", return_value=_streamed([b"1234", b"5678", b"never reached"])
    ), pytest.raises(podcast_client_mod.AudioTooLargeError):
        PodcastClient().fetch_audio_to_file("https://cdn.example.com/x.mp3", str(tmp_path / "ep.mp3"))
    assert (tmp_path / "ep.mp3").read_bytes() == b"1234", "the chunk past the limit is not written"


@pytest.fixture
def audio_dirs(tmp_path, monkeypatch, fake_client):
    """Point temp files at one directory, so a test can see what is left, and
    give the connector an episode with no transcript. Yields that directory."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    fake_client.fetch_feed.return_value = {
        "feed": {"title": "The Test Show"},
        "entries": [
            {
                "id": "https://testshow.example.com/ep1",
                "title": "Episode 1: Hello",
                "link": "https://testshow.example.com/ep1",
                "enclosures": [{"href": "https://cdn.testshow.example.com/ep1.mp3"}],
            }
        ],
    }
    monkeypatch.setattr(podcast_connector_mod.settings, "OPENAI_API_KEY", "sk-fake")
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        yield scratch


def test_the_temporary_audio_is_gone_after_a_transcription(podcast, fake_client, audio_dirs):
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    seen: list[str] = []

    def whisper(client, path, label, tag, size_mb):
        seen.append(path)
        assert os.path.exists(path), "the audio is on disk while Whisper reads it"
        return Mock(segments=[{"start": 0.0, "end": 3.0, "text": "Hello."}])

    with patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=whisper):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert out is not None and seen and seen[0].endswith(".mp3")
    assert list(audio_dirs.iterdir()) == []


def test_a_download_that_drops_leaves_no_partial_file(podcast, fake_client, audio_dirs):
    def dropped(url, path):
        with open(path, "wb") as f:
            f.write(b"half an episode")
        raise httpx.ReadError("connection reset")

    fake_client.fetch_audio_to_file.side_effect = dropped
    with patch.object(youtube_service, "_whisper_transcribe_with_retry") as whisper:
        assert podcast.fetch_text(_candidate_for_ep1(), job_id="j1") is None
    whisper.assert_not_called()
    assert list(audio_dirs.iterdir()) == []


def test_a_full_disk_loses_the_episode_and_not_the_run(podcast, fake_client, audio_dirs):
    fake_client.fetch_audio_to_file.side_effect = OSError("no space left on device")
    assert podcast.fetch_text(_candidate_for_ep1(), job_id="j1") is None


def test_an_empty_download_is_not_sent_to_whisper(podcast, fake_client, audio_dirs):
    fake_client.fetch_audio_to_file.side_effect = _writes(b"")
    with patch.object(youtube_service, "_whisper_transcribe_with_retry") as whisper:
        assert podcast.fetch_text(_candidate_for_ep1(), job_id="j1") is None
    whisper.assert_not_called()


def test_a_whisper_failure_leaves_no_audio(podcast, fake_client, audio_dirs):
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    with patch.object(
        youtube_service, "_whisper_transcribe_with_retry", side_effect=RuntimeError("refused")
    ):
        assert podcast.fetch_text(_candidate_for_ep1(), job_id="j1") is None
    assert list(audio_dirs.iterdir()) == []


def test_an_exception_past_the_handlers_still_leaves_no_audio(podcast, fake_client, audio_dirs):
    """A task cancelled mid-transcription, say."""
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    with patch.object(
        youtube_service, "_whisper_transcribe_with_retry", side_effect=KeyboardInterrupt
    ), pytest.raises(KeyboardInterrupt):
        podcast.fetch_text(_candidate_for_ep1(), job_id="j1")
    assert list(audio_dirs.iterdir()) == []


def test_a_split_episode_leaves_neither_audio_nor_chunks(podcast, fake_client, audio_dirs, monkeypatch):
    """The chunks are written next to the audio, in the same directory."""
    fake_client.fetch_audio_to_file.side_effect = _writes(b"x" * 9)
    monkeypatch.setattr(youtube_service, "WHISPER_MAX_FILE_BYTES", 8)

    def split(path, tmpdir, tag):
        chunk = os.path.join(tmpdir, "chunk_000.mp3")
        with open(chunk, "wb") as f:
            f.write(b"x")
        return [(chunk, 0.0), (chunk, 100.0)]

    monkeypatch.setattr(youtube_service, "_split_audio_for_whisper", split)
    answers = [_whisper_says(_segment("Opening.", 0.0, 90.0), duration=110.0), RuntimeError("refused")]
    with (
        patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=answers),
        pytest.raises(source_failure.TranscriptionCutShort) as cut,
    ):
        podcast.fetch_text(_candidate_for_ep1(), job_id="j1")
    assert cut.value.seconds == 110.0, "as far as the billed chunk reached"
    assert list(audio_dirs.iterdir()) == []


# ---------------------------------------------------------------------------
# T-1.7.1.8: Whisper's words with no segments
#
# A verbose_json answer can carry the whole text and an empty `segments`.
# YouTube's path has always kept such an answer as pseudo-segments spread over
# what Whisper heard (`_synthesize_pseudo_segments`); the podcast single-file
# path dropped it, and since #430 raised `TranscriptionEmpty`, so the episode
# was paid for and lost. It now goes through the same helper. Whisper is
# `_whisper_transcribe_with_retry`, patched: the client it would use is built
# and never called, so no request leaves.
#
# Mutation check: take the `_synthesize_pseudo_segments` fallback out of
# `_whisper_transcribe_audio` and the first two tests fail on
# `TranscriptionEmpty`.
# ---------------------------------------------------------------------------
TWENTY_MINUTES_OF_WORDS = " ".join(f"word{i}" for i in range(400))


def _whisper_text_only(text: str, duration: float) -> SimpleNamespace:
    """The SDK's verbose_json model with the text and no segments."""
    return SimpleNamespace(language="en", duration=duration, segments=[], text=text)


def test_whisper_text_with_no_segments_is_kept_as_pseudo_segments(podcast, fake_client, audio_dirs):
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    answer = _whisper_text_only(TWENTY_MINUTES_OF_WORDS, 1200.0)
    with patch.object(youtube_service, "_whisper_transcribe_with_retry", return_value=answer) as whisper:
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    whisper.assert_called_once()
    assert isinstance(out, ExtractedText)
    assert out.text_source == "podcast_whisper"
    assert out.word_count == 400, "every word is kept"
    assert " ".join(s["text"] for s in out.segments) == TWENTY_MINUTES_OF_WORDS
    # The way YouTube does it, by the same helper: 30 s pseudo-segments over
    # the 1,200 s Whisper reported, the last ending where the audio does.
    youtube_segments, _, _ = youtube_service._whisper_response_to_segments(answer, "[test]", "ep1")
    assert [{k: s[k] for k in ("text", "start", "duration")} for s in out.segments] == youtube_segments
    assert len(out.segments) == 40
    assert out.segments[-1]["start"] + out.segments[-1]["duration"] == 1200.0
    # Each pseudo-segment carries the episode's provenance like a real one.
    assert out.segments[1]["extra"]["comment_url"].endswith("#t=30")


def test_an_older_sdks_dict_answer_with_only_text_is_kept_too(podcast, fake_client, audio_dirs):
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    answer = {"language": "en", "duration": 20.0, "segments": [], "text": "  A short clip.  "}
    with patch.object(youtube_service, "_whisper_transcribe_with_retry", return_value=answer):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert [(s["text"], s["start"], s["duration"]) for s in out.segments] == [("A short clip.", 0.0, 20.0)]


def test_sparse_text_still_ends_where_whisper_stopped(podcast, fake_client, audio_dirs):
    """Ten words in an hour of music. The helper gives a pseudo-segment only to
    a 30 s slot with a word, so its segments end at 300 s; the job's minute
    cap reads where the transcript ends when the feed declares no length, so
    the last one is stretched to the 3,600 s Whisper heard. Every word and
    every start stay as YouTube's helper set them.

    Mutation check: take ``_end_where_whisper_stopped`` out and the last
    segment ends at 300 s."""
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    words = " ".join(f"lyric{i}" for i in range(10))
    answer = _whisper_text_only(words, 3600.0)
    with patch.object(youtube_service, "_whisper_transcribe_with_retry", return_value=answer):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert out.word_count == 10 and " ".join(s["text"] for s in out.segments) == words
    youtube_segments, _, _ = youtube_service._whisper_response_to_segments(answer, "[test]", "ep1")
    assert [(s["text"], s["start"]) for s in out.segments] == [(s["text"], s["start"]) for s in youtube_segments]
    assert youtube_segments[-1]["start"] + youtube_segments[-1]["duration"] == 300.0, "the helper's own end"
    assert [s["duration"] for s in out.segments[:-1]] == [30.0] * 9
    assert out.segments[-1]["start"] == 270.0
    assert out.segments[-1]["start"] + out.segments[-1]["duration"] == 3600.0


@pytest.mark.parametrize("text", ["", "   \n ", None], ids=["empty", "blank", "absent"])
def test_an_answer_with_no_words_at_all_is_still_transcription_empty(podcast, fake_client, audio_dirs, text):
    """T-1.7.1.7 unchanged: billed, no words, and the job's limits hear it."""
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    answer = SimpleNamespace(language="en", duration=300.0, segments=[])
    if text is not None:
        answer.text = text
    with (
        patch.object(youtube_service, "_whisper_transcribe_with_retry", return_value=answer),
        pytest.raises(source_failure.TranscriptionEmpty) as empty,
    ):
        podcast.fetch_text(_candidate_for_ep1(), job_id="j1")
    assert empty.value.seconds == 300.0


def test_real_segments_still_win_over_the_text(podcast, fake_client, audio_dirs):
    """An answer with both keeps its own timings; the text is not read."""
    fake_client.fetch_audio_to_file.side_effect = _writes(b"mp3")
    answer = SimpleNamespace(
        language="en",
        duration=60.0,
        segments=[{"text": "Timed words.", "start": 4.0, "end": 9.0}],
        text="Timed words. And text that is not in any segment.",
    )
    with patch.object(youtube_service, "_whisper_transcribe_with_retry", return_value=answer):
        out = podcast.fetch_text(_candidate_for_ep1(), job_id="j1")

    assert [(s["text"], s["start"], s["duration"]) for s in out.segments] == [("Timed words.", 4.0, 5.0)]


# ---------------------------------------------------------------------------
# Which episodes a show contributes (T-1.7.1.3)
# ---------------------------------------------------------------------------
def _episode(n: int, title: str, summary: str = "") -> dict:
    return {"id": f"ep-{n}", "title": title, "summary": summary, "enclosures": [{"href": f"https://x/{n}.mp3"}]}


def _titles(entries: list[dict]) -> list[str]:
    return [e["title"] for e in entries]


def test_a_show_with_no_match_contributes_its_newest_as_before():
    entries = [_episode(i, f"Unrelated {i}") for i in range(8)]
    chosen = podcast_connector_mod._select_entries(entries, "nuclear power", 5)
    assert chosen == entries[:5]


def test_episodes_on_the_topic_come_before_the_newest():
    entries = [
        _episode(0, "Newest, about gardening"),
        _episode(1, "Also new, about taxes"),
        _episode(2, "Why nuclear power came back"),
        _episode(3, "Older, about sailing"),
        _episode(4, "The history of nuclear power plants"),
    ]
    chosen = podcast_connector_mod._select_entries(entries, "nuclear power", 3)
    assert _titles(chosen) == [
        "Why nuclear power came back",
        "The history of nuclear power plants",
        "Newest, about gardening",
    ], "a show with too few matches fills up from its newest"


def test_an_old_match_is_found_anywhere_in_the_feed():
    entries = [_episode(i, f"Unrelated {i}") for i in range(200)] + [_episode(200, "Nuclear power, 2009")]
    chosen = podcast_connector_mod._select_entries(entries, "nuclear power", 2)
    assert _titles(chosen) == ["Nuclear power, 2009", "Unrelated 0"]


def test_the_title_outranks_a_mention_in_the_description():
    entries = [
        _episode(0, "An interview", "We talk about nuclear power and much else."),
        _episode(1, "Nuclear power"),
    ]
    chosen = podcast_connector_mod._select_entries(entries, "nuclear power", 2)
    assert _titles(chosen) == ["Nuclear power", "An interview"]


def test_a_description_counts_when_the_title_says_nothing():
    entries = [
        _episode(0, "Episode 12"),
        _episode(1, "Episode 11", "Rare earth magnets and who makes them."),
    ]
    chosen = podcast_connector_mod._select_entries(entries, "rare earth magnets", 1)
    assert _titles(chosen) == ["Episode 11"]


def test_one_word_of_the_topic_is_not_a_match():
    """Boardroom power is not nuclear power, and it should not displace the
    show's newest."""
    entries = [_episode(0, "This week"), _episode(1, "Power in the boardroom")]
    chosen = podcast_connector_mod._select_entries(entries, "nuclear power", 1)
    assert _titles(chosen) == ["This week"]


def test_most_of_a_long_topic_is_enough():
    entries = [_episode(0, "This week"), _episode(1, "The fall of the Roman Empire")]
    chosen = podcast_connector_mod._select_entries(
        entries, "Why did the Roman Empire fall and what can we learn from it today?", 1
    )
    assert _titles(chosen) == ["The fall of the Roman Empire"]


def test_a_plural_in_the_feed_matches_the_singular_in_the_topic():
    entries = [_episode(0, "This week"), _episode(1, "Nuclear power plants")]
    chosen = podcast_connector_mod._select_entries(entries, "nuclear power plant", 1)
    assert _titles(chosen) == ["Nuclear power plants"]


def test_search_prefers_episodes_on_the_topic_and_fetches_no_audio(podcast, fake_client):
    """At ``search()``: each show in turn, its episodes on the topic first."""
    fake_client.itunes_search.return_value = {
        "results": [
            {"collectionName": "A", "feedUrl": "https://a.example.com/f.rss"},
            {"collectionName": "B", "feedUrl": "https://b.example.com/f.rss"},
        ]
    }
    feeds = {
        "https://a.example.com/f.rss": {"entries": [_episode(0, "Taxes"), _episode(1, "Nuclear power")]},
        "https://b.example.com/f.rss": {"entries": [_episode(2, "Sailing"), _episode(3, "Gardening")]},
    }
    fake_client.fetch_feed.side_effect = lambda url: feeds[url]
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("nuclear power", limit=3)

    assert [c.title for c in out] == ["Nuclear power", "Sailing", "Taxes"]
    fake_client.fetch_audio_to_file.assert_not_called()


def test_one_feed_failing_only_costs_that_show(podcast, fake_client):
    fake_client.itunes_search.return_value = {
        "results": [
            {"collectionName": "A", "feedUrl": "https://a.example.com/f.rss"},
            {"collectionName": "B", "feedUrl": "https://b.example.com/f.rss"},
        ]
    }

    def feed(url):
        if "a.example" in url:
            raise httpx.ConnectError("down")
        return {"entries": [_episode(1, "Kept")]}

    fake_client.fetch_feed.side_effect = feed
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert [c.title for c in podcast.search("anything")] == ["Kept"]


def test_every_feed_failing_is_a_failure_not_an_empty_answer(podcast, fake_client):
    fake_client.itunes_search.return_value = {
        "results": [{"collectionName": "A", "feedUrl": "https://a.example.com/f.rss"}]
    }
    down = httpx.ConnectError("down")
    fake_client.fetch_feed.side_effect = down
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ), pytest.raises(source_failure.SearchFailed) as caught:
        podcast.search("anything")
    assert caught.value.__cause__ is down


def test_a_feed_host_refusing_never_reads_as_the_service_refusing(podcast, fake_client):
    """Each feed is a different host, and iTunes has already answered."""
    fake_client.itunes_search.return_value = {
        "results": [{"collectionName": "A", "feedUrl": "https://a.example.com/f.rss"}]
    }
    fake_client.fetch_feed.side_effect = httpx.HTTPStatusError(
        "403",
        request=httpx.Request("GET", "https://a.example.com/f.rss"),
        response=httpx.Response(403),
    )
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ), pytest.raises(source_failure.SearchFailed) as caught:
        podcast.search("anything")
    assert source_failure.classify(caught.value) == source_failure.SourceFailure("failed", 403)


def test_itunes_refusing_stays_a_refusal(podcast, fake_client):
    fake_client.itunes_search.side_effect = httpx.HTTPStatusError(
        "403",
        request=httpx.Request("GET", "https://itunes.apple.com/search"),
        response=httpx.Response(403),
    )
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ), pytest.raises(httpx.HTTPStatusError) as caught:
        podcast.search("anything")
    assert source_failure.classify(caught.value).kind == "refused"


def test_a_sentence_itunes_cannot_answer_falls_back_to_its_words(podcast, fake_client):
    fake_client.itunes_search.side_effect = lambda q, limit: (
        {"results": [{"collectionName": "A", "feedUrl": "https://a.example.com/f.rss"}]}
        if q == "tariffs small businesses"
        else {"results": []}
    )
    fake_client.fetch_feed.return_value = {"entries": [_episode(1, "An episode")]}
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        out = podcast.search("What is the impact of tariffs on small businesses?")
    assert [c.title for c in out] == ["An episode"]

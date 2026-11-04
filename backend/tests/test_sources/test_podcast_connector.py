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
from types import SimpleNamespace
from unittest.mock import Mock, patch

import feedparser
import httpx
import pytest

from app.services import youtube_service
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


def test_search_returns_empty_when_itunes_fails(podcast, fake_client):
    fake_client.itunes_search.side_effect = RuntimeError("upstream 503")
    with patch.object(
        podcast_connector_mod.podcast_client, "get_client", return_value=fake_client
    ):
        assert podcast.search("anything") == []


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
    fake_client.fetch_audio.return_value = b"fake-mp3-bytes"

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
    fake_client.fetch_audio.return_value = b"x" * 9
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
    fake_client.fetch_audio.return_value = b"x" * 8
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
    """A transcript with a hole would read as the whole episode."""
    answers = [_whisper_says(_segment("Opening.", 0.0, 90.0), duration=110.0), RuntimeError("refused")]
    with patch.object(youtube_service, "_whisper_transcribe_with_retry", side_effect=answers):
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
    fake_client.fetch_audio.return_value = audio.read_bytes()
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
    fake_client.fetch_audio.assert_not_called()


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


def test_client_fetch_audio_returns_bytes():
    api_resp = Mock(status_code=200)
    api_resp.content = b"audio-bytes"
    api_resp.raise_for_status = Mock()
    with patch.object(podcast_client_mod.httpx, "get", return_value=api_resp):
        c = PodcastClient()
        out = c.fetch_audio("https://cdn.example.com/x.mp3")
    assert out == b"audio-bytes"

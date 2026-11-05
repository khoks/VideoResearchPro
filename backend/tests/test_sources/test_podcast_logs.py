"""T-1.7.1.6: a podcast's feed, audio and transcript URLs stay out of the logs.

A private feed's address carries its token, and so can the audio and transcript
links inside it. The T-3.7.2.9 treatment, on the path that task left out: a log
line names the host and the exception's type, and httpx's own line goes quiet
around these fetches. The connector's lines are checked on a patched logger,
every branch; httpx's for real, on a local server, with a handler on its logger.

Mutation checks (each failed the named test when this shipped): dropping
``@shared_url_fetch()`` from ``fetch_feed``, ``fetch_audio_to_file`` or
``_resolve_transcript_segments`` (``test_httpx_writes_no_line_for_a_feed``, and
the audio and transcript tests after it); logging ``e`` instead of its type on
any feed line (``test_a_failed_feed_names_the_host_only``); putting ``feed_url``
back on a line (the same test, and
``test_no_log_call_in_the_connector_takes_a_url_itself``); ``loggable_id`` left
off the guid (``test_a_guid_that_is_a_url_stays_out``).
"""
from __future__ import annotations

import ast
import http.server
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from app.config import settings
from app.sources.podcast import client as podcast_client
from app.sources.podcast import connector
from app.sources.podcast.client import PodcastClient
from app.sources.podcast.connector import PodcastConnector
from app.sources.types import Candidate
from app.tasks import job_tasks
from app.utils.shared_url_log import loggable_id

HOST = "feeds.example.com"
TOKEN = "private-feed-token-abc"
FEED = f"https://{HOST}/show/rss?token={TOKEN}"
AUDIO = f"https://cdn.example.net/ep1.mp3?auth={TOKEN}"
TRANSCRIPT = f"https://cdn.example.net/ep1.vtt?auth={TOKEN}"


def _rendered(log: MagicMock) -> str:
    """Every call on a patched logger, as the line it would have written."""
    lines = []
    for method in ("debug", "info", "warning", "error", "exception"):
        for call in getattr(log, method).call_args_list:
            message, *args = call.args
            lines.append(message % tuple(args) if args else message)
    return "\n".join(lines)


def _candidate(guid: str = "ep-1") -> Candidate:
    return Candidate(
        source_type="podcast_episode",
        source_id=f"podcast:{guid}",
        title="Episode",
        source_url="https://example.com/ep",
        creator_external_id=FEED,
    )


def _http_error() -> httpx.HTTPStatusError:
    """What ``raise_for_status`` raises, which quotes the URL whole."""
    return httpx.HTTPStatusError(f"Client error '403 Forbidden' for url '{FEED}'", request=MagicMock(), response=MagicMock())


def _feed_with(entry: dict) -> dict:
    return {"feed": {"title": "Show"}, "entries": [entry]}


@pytest.fixture
def client():
    fake = Mock(spec=PodcastClient)
    with patch.object(podcast_client, "get_client", return_value=fake):
        yield fake


@pytest.fixture
def log():
    with patch.object(connector, "logger") as patched:
        yield patched


def _host_only(log: MagicMock, *hosts: str) -> str:
    text = _rendered(log)
    assert text, "the failure is still logged"
    assert TOKEN not in text
    assert "/show/rss" not in text and "ep1." not in text
    for host in hosts:
        assert host in text
    return text


@pytest.mark.parametrize(
    "fail",
    [
        pytest.param(lambda c: list(PodcastConnector().list_creator_items(FEED)), id="list_creator_items"),
        pytest.param(lambda c: PodcastConnector().fetch_creator(FEED), id="fetch_creator"),
        pytest.param(lambda c: PodcastConnector().fetch_text(_candidate()), id="fetch_text"),
    ],
)
def test_a_failed_feed_names_the_host_only(client, log, fail):
    client.fetch_feed.side_effect = _http_error()
    fail(client)
    assert "HTTPStatusError" in _host_only(log, HOST)


def test_a_failed_feed_in_a_search_names_the_host_only(client, log):
    client.itunes_search.return_value = {"results": [{"feedUrl": FEED, "collectionName": "Show"}]}
    client.fetch_feed.side_effect = _http_error()
    with pytest.raises(Exception):
        PodcastConnector().search("topic")
    assert "HTTPStatusError" in _host_only(log, HOST)


def test_an_entry_missing_from_its_feed_names_the_host_only(client, log):
    client.fetch_feed.return_value = _feed_with({"id": "another", "title": "Other"})
    assert PodcastConnector().fetch_text(_candidate()) is None
    _host_only(log, HOST)


def test_a_failed_transcript_names_the_host_only(log):
    entry = {"podcast_transcript": {"url": TRANSCRIPT, "type": "text/vtt"}}
    with patch.object(connector.httpx, "get", side_effect=httpx.ConnectError(f"cannot reach {TRANSCRIPT}")):
        assert connector._resolve_transcript_segments(entry, "https://example.com/ep") is None
    assert "ConnectError" in _host_only(log, "cdn.example.net")


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(httpx.ConnectError(f"cannot reach {AUDIO}"), id="a failed download"),
        pytest.param(OSError(f"cannot write {AUDIO}"), id="a full disk"),
        pytest.param(podcast_client.AudioTooLargeError(f"{AUDIO} ran on"), id="an endless file"),
    ],
)
def test_a_failed_audio_download_names_the_host_only(client, log, error):
    client.fetch_audio_to_file.side_effect = error
    with patch("app.services.llm_service.whisper_api_key", return_value="not-used"):
        assert connector._whisper_transcribe_audio(AUDIO, "podcast:ep-1", "j") is None
    assert type(error).__name__ in _host_only(log, "cdn.example.net")


def test_an_empty_download_names_the_host_only(client, log):
    client.fetch_audio_to_file.return_value = 0
    with patch("app.services.llm_service.whisper_api_key", return_value="not-used"):
        assert connector._whisper_transcribe_audio(AUDIO, "podcast:ep-1", "j") is None
    _host_only(log, "cdn.example.net")


def test_a_guid_that_is_a_url_stays_out(client, log):
    """A feed entry with no guid goes by its link or its audio file."""
    guid = AUDIO
    client.fetch_feed.return_value = _feed_with({"id": "another", "title": "Other"})
    assert PodcastConnector().fetch_text(_candidate(guid)) is None
    assert TOKEN not in _rendered(log)
    with patch("app.services.llm_service.whisper_api_key", return_value=None):
        assert connector._whisper_transcribe_audio(AUDIO, f"podcast:{guid}", "j") is None
    assert TOKEN not in _rendered(log)


def test_a_guid_that_is_a_url_stays_out_of_whispers_own_lines(client, log):
    """The Whisper helpers log the id they are handed, on their own logger."""
    client.fetch_audio_to_file.return_value = 1024
    send = MagicMock(return_value=SimpleNamespace(segments=[]))
    with (
        patch("app.services.llm_service.whisper_api_key", return_value="not-used"),
        patch("openai.OpenAI"),
        patch("app.services.youtube_service._whisper_transcribe_with_retry", send),
    ):
        connector._whisper_transcribe_audio(AUDIO, f"podcast:{AUDIO}", "j")
    assert send.call_args.args[2] == "podcast:cdn.example.net"


@pytest.mark.parametrize(
    "source_id, expected",
    [
        ("podcast:abc-guid", "podcast:abc-guid"),
        ("article:0123456789abcdef", "article:0123456789abcdef"),
        (f"podcast:{AUDIO}", "podcast:cdn.example.net"),
        ("podcast:tag:example.com,2024:ep-1", "podcast:tag:example.com,2024:ep-1"),
        ("https://user:hunter2@host.example/x?y=1", "host.example"),
    ],
)
def test_loggable_id(source_id, expected):
    assert loggable_id(source_id) == expected


def test_no_log_call_in_the_connector_takes_a_url_itself():
    """A line added later should have to go through ``host_of``."""
    tree = ast.parse(Path(connector.__file__).read_text(encoding="utf-8"))
    urls = {"url", "audio_url", "feed_url", "creator_external_id", "source_url", "guid", "source_id"}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            names = {arg.id for arg in node.args if isinstance(arg, ast.Name)}
            assert not names & urls, ast.unparse(node)
            # Only the iTunes lookup keeps the exception's text: its URL holds a
            # public show id, and nothing else in this file quotes a private one.
            assert "e" not in names or "itunes_id" in names, ast.unparse(node)


def test_a_candidates_failure_in_a_job_keeps_a_url_in_its_id_out():
    """The two lines in ``job_tasks`` that name a candidate by its id."""
    connector_stub = MagicMock()
    connector_stub.fetch_text.side_effect = RuntimeError("boom")
    result = SimpleNamespace(candidates_by_source_type={"podcast_episode": [_candidate(AUDIO)]})
    job = SimpleNamespace(id="job-1", topic="topic")
    with (
        patch("app.sources.registry.connector_for", return_value=connector_stub),
        patch.object(job_tasks, "_upsert_candidate_and_link", side_effect=RuntimeError("boom")),
        patch.object(job_tasks, "logger") as log,
    ):
        job_tasks._store_non_video_candidates(MagicMock(), job, result, {"podcast_episode": 1})
    assert len(log.exception.call_args_list) == 2
    assert TOKEN not in repr(log.exception.call_args_list)


# ---------------------------------------------------------------------------
# httpx's own line, and the fetch that still needs the whole URL
# ---------------------------------------------------------------------------


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def httpx_lines():
    """httpx's logger at INFO, as it runs in a Celery worker."""
    log = logging.getLogger("httpx")
    handler = _Lines()
    level, disabled = log.level, log.disabled
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.disabled = False
    yield handler.lines
    log.removeHandler(handler)
    log.setLevel(level)
    log.disabled = disabled


class _Site(http.server.BaseHTTPRequestHandler):
    paths: list[str] = []
    body = b"<rss version='2.0'><channel><title>Mine</title></channel></rss>"

    def do_GET(self):
        type(self).paths.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    _Site.paths = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_the_harness_sees_httpxs_line(httpx_lines, site):
    httpx.get(f"{site}/plain?token={TOKEN}", trust_env=False)
    assert len(httpx_lines) == 1 and TOKEN in httpx_lines[0]


def test_httpx_writes_no_line_for_a_feed(httpx_lines, site, monkeypatch):
    monkeypatch.setattr(settings, "PODCAST_RATE_LIMIT_RPM", 6000)
    feed = PodcastClient().fetch_feed(f"{site}/feed.rss?token={TOKEN}")
    assert feed.feed.title == "Mine"
    assert httpx_lines == []
    assert _Site.paths == [f"/feed.rss?token={TOKEN}"], "the request itself keeps the whole URL"


def test_httpx_writes_no_line_for_the_audio(httpx_lines, site, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PODCAST_RATE_LIMIT_RPM", 6000)
    assert PodcastClient().fetch_audio_to_file(f"{site}/ep.mp3?auth={TOKEN}", str(tmp_path / "ep.mp3")) > 0
    assert httpx_lines == []
    assert _Site.paths == [f"/ep.mp3?auth={TOKEN}"]


def test_httpx_writes_no_line_for_the_transcript(httpx_lines, site, monkeypatch):
    monkeypatch.setattr(_Site, "body", b"WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nhello\n\n")
    entry = {"podcast_transcript": {"url": f"{site}/ep.vtt?auth={TOKEN}", "type": "text/vtt"}}
    assert connector._resolve_transcript_segments(entry, "https://example.com/ep")
    assert httpx_lines == []
    assert _Site.paths == [f"/ep.vtt?auth={TOKEN}"]

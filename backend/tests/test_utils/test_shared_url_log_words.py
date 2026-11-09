"""T-4.11.4.2: the helpers that keep a user's words out of the worker's log,
and the search requests that send inside ``shared_url_fetch``.

httpx writes a line of its own for every request, URL included, at INFO, and
the worker logs at INFO. A search's URL holds the topic, so each connector's
search method sends with that line off. These run the real clients over a
real ``httpx.Client`` (a mock transport in place of the network), because the
line is httpx's own, and read what a handler on the root logger, as Celery
puts one, was given.
"""
from __future__ import annotations

import io
import logging

import httplib2
import httpx
import pytest
from googleapiclient.errors import HttpError

from app.config import settings
from app.sources.article.client import ArticleClient
from app.sources.bluesky.client import BlueskyClient
from app.sources.hn.client import HNClient
from app.sources.mastodon.client import MastodonClient
from app.sources.podcast.client import PodcastClient
from app.sources.reddit.client import RedditClient
from app.sources.twitter.client import TwitterClient
from app.utils.shared_url_log import is_channel_id, loggable_channel_input, traceback_without_text

WORDS = ("zanzibar", "quokka")
QUERY = "Zanzibar quokka"


# ---------------------------------------------------------------------------
# traceback_without_text
# ---------------------------------------------------------------------------

def _raised(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001 - the point is to keep it
        return caught


def _search_failure() -> BaseException:
    """An httpx error from a search, caused by nothing, inside a wrapper
    raised ``from`` it, as a connector raises ``SearchFailed``."""
    request = httpx.Request("GET", "https://hn.algolia.com/api/v1/search?query=Zanzibar+quokka")
    response = httpx.Response(503, request=request)
    try:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as inner:
            raise RuntimeError(f"search for {QUERY!r} failed") from inner
    except RuntimeError as outer:
        return outer


def test_it_keeps_the_frames_and_types_and_drops_the_words():
    exc = _search_failure()
    text = traceback_without_text(exc)
    assert "httpx.HTTPStatusError" in text
    assert "RuntimeError" in text
    assert "The above exception was the direct cause of the following exception" in text
    assert "test_shared_url_log_words.py" in text, "the frames say where it failed"
    assert "_search_failure" in text
    lowered = text.lower()
    for word in WORDS:
        assert word not in lowered
    assert "algolia" not in lowered, "not the URL's host either: the words are the URL's"


def test_the_oldest_exception_comes_first_as_python_prints_it():
    text = traceback_without_text(_search_failure())
    assert text.index("httpx.HTTPStatusError") < text.index("RuntimeError")
    assert text.startswith("Traceback (most recent call last), what it said left out:")


def test_a_context_is_shown_and_a_suppressed_one_is_not():
    # The words come from variables: a frame shows its source line, which is
    # code, and a literal in it would be the test's own text.
    first, second = WORDS
    try:
        try:
            raise KeyError(first)
        except KeyError:
            raise ValueError(second)  # noqa: B904 - the implicit context is the point
    except ValueError as e:
        shown = traceback_without_text(e)
    assert "During handling of the above exception" in shown
    assert "KeyError" in shown and "ValueError" in shown
    assert first not in shown and second not in shown

    try:
        try:
            raise KeyError(first)
        except KeyError:
            raise ValueError(second) from None
    except ValueError as e:
        alone = traceback_without_text(e)
    assert "KeyError" not in alone and "ValueError" in alone


def test_an_httperror_keeps_its_type_and_loses_its_request():
    err = _raised(HttpError(
        httplib2.Response({"status": 400}),
        b'{"error": {"message": "Bad Request", "errors": [{"reason": "badRequest"}]}}',
        uri="https://youtube.googleapis.com/youtube/v3/search?q=Zanzibar+quokka&key=AIzaSyFAKEFAKEFAKE",
    ))
    text = traceback_without_text(err)
    assert "googleapiclient.errors.HttpError" in text
    assert "zanzibar" not in text.lower() and "googleapis" not in text


def test_an_exception_never_raised_is_its_type_alone():
    assert traceback_without_text(ValueError("Zanzibar quokka")) == "ValueError"


def test_a_cycle_ends():
    a, b = ValueError("Zanzibar"), KeyError("quokka")
    a.__cause__, b.__cause__ = b, a
    text = traceback_without_text(a)
    assert "ValueError" in text and "KeyError" in text and "Zanzibar" not in text


# ---------------------------------------------------------------------------
# loggable_channel_input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("channel_input, logged", [
    ("UCabcdefghijklmnopqrstuv", "UCabcdefghijklmnopqrstuv"),
    ("@stoatlab", "@stoatlab"),
    ("https://www.youtube.com/@stoatlab?si=SHAREtoken123", "a link on www.youtube.com"),
    ("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv/videos", "a link on www.youtube.com"),
    ("youtube.com/@stoatlab?si=SHAREtoken123", "a link on youtube.com"),
    ("Wombat Brewing Society", "a name of 22 characters"),
    ("@Wombat Brewing Society", "a name of 23 characters"),
    ("", "a name of 0 characters"),
    (None, "a name of 0 characters"),
    # 24 characters starting with "UC", and a name all the same.
    ("UC Berkeley Data Science", "a name of 24 characters"),
    ("UCéééééééééééééééééééééé", "a name of 24 characters"),
])
def test_a_channel_input_names_its_kind(channel_input, logged):
    assert loggable_channel_input(channel_input) == logged


@pytest.mark.parametrize("value, is_id", [
    ("UCabcdefghijklmnopqrstuv", True),
    ("UC_abc-defghijklmnopqrst", True),
    ("UC Berkeley Data Science", False),
    ("UCéééééééééééééééééééééé", False),
    ("UCabcdefghijklmnopqrstu", False),
    ("UCabcdefghijklmnopqrstuvw", False),
    (" UCabcdefghijklmnopqrstuv", False),
    ("ucabcdefghijklmnopqrstuv", False),
    (None, False),
])
def test_a_channel_id_is_its_exact_shape(value, is_id):
    assert is_channel_id(value) is is_id


# ---------------------------------------------------------------------------
# httpx's own request line: off for a search, on for anything else
# ---------------------------------------------------------------------------

@pytest.fixture
def worker_log():
    """A handler on the root logger at INFO, as the Celery worker has."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


@pytest.fixture
def network(monkeypatch):
    """``httpx.get`` and ``httpx.post`` through a real ``httpx.Client`` whose
    transport answers 200 with a body every client can read."""
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("access_token"):
            return httpx.Response(200, json={"access_token": "reddit-test-token"})
        if "lookup" in request.url.path or "search" in request.url.path:
            return httpx.Response(200, json={"results": [], "hits": [], "posts": [], "data": []})
        return httpx.Response(200, json=[] if "timelines" in request.url.path else {})

    real_client = httpx.Client

    def send(method):
        def call(url, **kwargs):
            kwargs.pop("timeout", None)
            follow = kwargs.pop("follow_redirects", False)
            with real_client(transport=httpx.MockTransport(answer), follow_redirects=follow) as client:
                return client.request(method, url, **kwargs)
        return call

    monkeypatch.setattr(httpx, "get", send("GET"))
    monkeypatch.setattr(httpx, "post", send("POST"))
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "x-test-token")
    monkeypatch.setattr(settings, "BRAVE_SEARCH_API_KEY", "brave-test-key")
    return seen


SEARCHES = {
    "hn": lambda: HNClient().search(QUERY),
    "reddit": lambda: RedditClient().search(QUERY),
    "reddit_subreddit": lambda: RedditClient().search_subreddit("science", QUERY),
    "bluesky": lambda: BlueskyClient().search_posts(QUERY),
    "mastodon": lambda: MastodonClient().timeline_tag("zanzibarquokka"),
    "twitter": lambda: TwitterClient().search_recent(QUERY),
    "brave": lambda: ArticleClient().brave_search(QUERY),
    "itunes": lambda: PodcastClient().itunes_search(QUERY),
}


@pytest.mark.parametrize("name", sorted(SEARCHES))
def test_a_search_request_writes_no_request_line(name, network, worker_log):
    SEARCHES[name]()

    assert any(word in url.lower() for url in network for word in WORDS), "the request did carry the words"
    written = worker_log.getvalue().lower()
    for word in WORDS:
        assert word not in written, written


def test_any_other_request_still_writes_its_line(network, worker_log):
    """The control: the handler above sees httpx's line, so the searches'
    silence is the context's doing."""
    HNClient().get_item(8863)

    assert "HTTP Request: GET https://hn.algolia.com/api/v1/items/8863" in worker_log.getvalue()

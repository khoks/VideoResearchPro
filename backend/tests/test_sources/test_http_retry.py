"""T-1.5.11.2: one retry before a source counts as failed.

``_http_retry.send`` on its own, then every connector HTTP client through it,
with HTTP faked at ``httpx.get`` / ``httpx.post`` (no network). The run-level
checks, where a failure becomes a note and a refusal a hold, are in
``tests/test_routers/test_source_retry.py``.
"""
from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.sources import _http_retry
from app.sources.article import client as article_client
from app.sources.bluesky import client as bluesky_client
from app.sources.hn import client as hn_client
from app.sources.mastodon import client as mastodon_client
from app.sources.podcast import client as podcast_client
from app.sources.reddit import client as reddit_client
from app.sources.twitter import client as twitter_client
from app.utils.rate_limiter import RateLimiter

URL = "https://api.example.org/search?q=tides&token=s3cr3t-in-the-query"


def _response(status: int, headers: dict | None = None, json: object | None = None) -> httpx.Response:
    return httpx.Response(
        status, headers=headers, json=json if json is not None else {}, request=httpx.Request("GET", URL)
    )


class _Script:
    """Answers each call with the next item: a response, or an exception to raise."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def sleeps(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(_http_retry, "_sleep", slept.append)
    return slept


class _Limiter:
    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_a_503_then_a_200_succeeds_after_one_short_wait(sleeps):
    script = _Script(_response(503), _response(200, json={"ok": True}))
    limiter = _Limiter()

    resp = _http_retry.send(script, url=URL, limiter=limiter)

    assert resp.status_code == 200
    assert script.calls == 2
    assert sleeps == [_http_retry.BACKOFF_SECONDS]
    assert limiter.waits == 2, "the retry waits its turn on the client's pacing"


def test_two_503s_hand_the_second_back_for_the_client_to_raise(sleeps):
    script = _Script(_response(503), _response(503))

    resp = _http_retry.send(script, url=URL, limiter=None)

    assert resp.status_code == 503
    assert script.calls == 2, "one retry, not more"
    with pytest.raises(httpx.HTTPStatusError):
        resp.raise_for_status()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422])
def test_a_4xx_other_than_429_never_retries(sleeps, status):
    script = _Script(_response(status), _response(200))

    resp = _http_retry.send(script, url=URL, limiter=None)

    assert resp.status_code == status
    assert script.calls == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("no route"),
        httpx.ConnectTimeout("slow to connect"),
        httpx.ReadTimeout("slow to answer"),
        httpx.ReadError("connection reset"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ],
    ids=lambda e: type(e).__name__,
)
def test_a_timeout_or_a_connection_error_is_retried_once(sleeps, exc):
    assert _http_retry.send(_Script(exc, _response(200)), url=URL, limiter=None).status_code == 200

    script = _Script(exc)
    with pytest.raises(type(exc)):
        _http_retry.send(script, url=URL, limiter=None)
    assert script.calls == 2


def test_an_error_that_is_not_the_network_is_not_retried(sleeps):
    script = _Script(ValueError("a bug"), _response(200))
    with pytest.raises(ValueError):
        _http_retry.send(script, url=URL, limiter=None)
    assert script.calls == 1


@pytest.mark.parametrize(
    "headers,retried,waited",
    [
        ({"Retry-After": "2"}, True, 2.0),
        ({"Retry-After": "0"}, True, _http_retry.BACKOFF_SECONDS),
        ({"Retry-After": str(_http_retry.RETRY_AFTER_CEILING_SECONDS)}, True, _http_retry.RETRY_AFTER_CEILING_SECONDS),
        ({"Retry-After": "6"}, False, None),
        ({"Retry-After": "3600"}, False, None),
        ({}, False, None),
        ({"Retry-After": "soon"}, False, None),
        ({"Retry-After": "inf"}, False, None),
    ],
)
def test_a_429_is_retried_only_when_retry_after_is_short(sleeps, headers, retried, waited):
    script = _Script(_response(429, headers), _response(200))

    resp = _http_retry.send(script, url=URL, limiter=None)

    assert (resp.status_code == 200) is retried
    assert script.calls == (2 if retried else 1)
    assert sleeps == ([waited] if retried else [])


def test_a_retry_after_given_as_a_date_counts():
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=3), usegmt=True)
    later = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=5), usegmt=True)
    assert _http_retry._retry_delay(_response(429, {"Retry-After": soon}), _http_retry.DEFAULT) <= 3.0
    assert _http_retry._retry_delay(_response(429, {"Retry-After": later}), _http_retry.DEFAULT) is None


def test_a_5xx_that_asks_for_a_long_pause_is_not_retried(sleeps):
    script = _Script(_response(503, {"Retry-After": "120"}), _response(200))
    assert _http_retry.send(script, url=URL, limiter=None).status_code == 503
    assert script.calls == 1


def test_the_paid_policy_retries_only_what_nothing_answered(sleeps):
    """X (D-139): a timeout or a connection that never opened, nothing else."""
    paid = _http_retry.UNANSWERED_ONLY
    for answered in (_response(503), _response(500), _response(429, {"Retry-After": "1"})):
        script = _Script(answered, _response(200))
        assert _http_retry.send(script, url=URL, limiter=None, policy=paid) is answered
        assert script.calls == 1
    for unanswered in (httpx.ConnectError("x"), httpx.ConnectTimeout("x"), httpx.ReadTimeout("x")):
        script = _Script(unanswered, _response(200))
        assert _http_retry.send(script, url=URL, limiter=None, policy=paid).status_code == 200
        assert script.calls == 2
    script = _Script(httpx.ReadError("broke mid-answer"), _response(200))
    with pytest.raises(httpx.ReadError):
        _http_retry.send(script, url=URL, limiter=None, policy=paid)
    assert script.calls == 1


def test_a_mock_response_without_an_int_status_is_returned_as_is(sleeps):
    resp = MagicMock()
    assert _http_retry.send(lambda: resp, url=URL, limiter=None) is resp


def test_the_log_line_names_the_host_and_never_the_address(sleeps):
    with patch.object(_http_retry, "logger") as log:
        _http_retry.send(_Script(_response(503), _response(200)), url=URL, limiter=None)
        _http_retry.send(_Script(httpx.ConnectError(f"cannot reach {URL}"), _response(200)), url=URL, limiter=None)

    lines = [call.args[0] % call.args[1:] for call in log.info.call_args_list]
    assert len(lines) == 2
    assert lines[0].startswith("api.example.org: 503;")
    assert lines[1].startswith("api.example.org: ConnectError;")
    assert not any("s3cr3t" in line or "/search" in line for line in lines)


# ---------------------------------------------------------------------------
# Every connector client goes through it
# ---------------------------------------------------------------------------


@pytest.fixture
def unpaced(monkeypatch):
    """Clients built now get a limiter that never sleeps but counts waits."""
    limiters: list[_Limiter] = []

    def build(rate=1.0, jitter=0.0):
        limiter = _Limiter()
        limiters.append(limiter)
        return limiter

    for module in (hn_client, mastodon_client, bluesky_client, reddit_client, twitter_client, article_client, podcast_client):
        monkeypatch.setattr(module, "RateLimiter", build)
    return limiters


def _hn():
    return hn_client.HNClient().get_json("/search")


def _mastodon():
    return mastodon_client.MastodonClient().get_json("/timelines/tag/tides")


def _bluesky():
    return bluesky_client.BlueskyClient().search_posts("tides")


def _reddit():
    return reddit_client.RedditClient().search("tides")


def _brave():
    return article_client.ArticleClient().brave_search("tides")


def _itunes():
    return podcast_client.PodcastClient().itunes_search("tides")


def _itunes_lookup():
    return podcast_client.PodcastClient().itunes_lookup("123")


FREE_CLIENTS = [
    pytest.param(hn_client, _hn, id="hn"),
    pytest.param(mastodon_client, _mastodon, id="mastodon"),
    pytest.param(bluesky_client, _bluesky, id="bluesky"),
    pytest.param(reddit_client, _reddit, id="reddit"),
    pytest.param(article_client, _brave, id="brave"),
    pytest.param(podcast_client, _itunes, id="itunes-search"),
    pytest.param(podcast_client, _itunes_lookup, id="itunes-lookup"),
]


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "id-for-test")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "secret-for-test")
    monkeypatch.setattr(settings, "BRAVE_SEARCH_API_KEY", "key-for-test")
    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "token-for-test")
    monkeypatch.setattr(
        reddit_client.httpx, "post", lambda *a, **kw: _response(200, json={"access_token": "t"})
    )


@pytest.mark.parametrize("module,call", FREE_CLIENTS)
def test_each_free_client_retries_a_503_once_within_its_pacing(module, call, keys, unpaced, sleeps, monkeypatch):
    script = _Script(_response(503), _response(200, json={"answered": True}))
    monkeypatch.setattr(module.httpx, "get", script)

    assert call() == {"answered": True}
    assert script.calls == 2
    assert unpaced[-1].waits == 2, "each try waits its turn on the client's limiter"


@pytest.mark.parametrize("module,call", FREE_CLIENTS)
def test_each_free_client_raises_after_two_503s_and_at_once_on_a_404(module, call, keys, unpaced, sleeps, monkeypatch):
    script = _Script(_response(503))
    monkeypatch.setattr(module.httpx, "get", script)
    with pytest.raises(httpx.HTTPStatusError) as failed:
        call()
    assert failed.value.response.status_code == 503
    assert script.calls == 2

    script = _Script(_response(404), _response(200))
    monkeypatch.setattr(module.httpx, "get", script)
    with pytest.raises(httpx.HTTPStatusError):
        call()
    assert script.calls == 1


@pytest.mark.parametrize(
    "module,call",
    [
        pytest.param(article_client, lambda: article_client.ArticleClient().fetch_feed("https://feeds.example.org/a.xml"), id="article-feed"),
        pytest.param(podcast_client, lambda: podcast_client.PodcastClient().fetch_feed("https://feeds.example.org/p.xml"), id="podcast-feed"),
    ],
)
def test_feed_fetches_retry_a_timeout(module, call, unpaced, sleeps, monkeypatch):
    feed = httpx.Response(200, content=b"<rss><channel><title>T</title></channel></rss>", request=httpx.Request("GET", URL))
    script = _Script(httpx.ReadTimeout("slow"), feed)
    monkeypatch.setattr(module.httpx, "get", script)

    assert call().feed.title == "T"
    assert script.calls == 2


def test_reddit_token_fetch_retries_a_503(keys, unpaced, sleeps, monkeypatch):
    post = _Script(_response(503), _response(200, json={"access_token": "t"}))
    monkeypatch.setattr(reddit_client.httpx, "post", post)
    assert reddit_client.RedditClient()._fetch_token() == "t"
    assert post.calls == 2


def test_reddit_401_refresh_still_happens_once_and_is_not_a_retry(keys, unpaced, sleeps, monkeypatch):
    get = _Script(_response(401), _response(200, json={"ok": 1}))
    monkeypatch.setattr(reddit_client.httpx, "get", get)
    assert reddit_client.RedditClient().get_json("/search") == {"ok": 1}
    assert get.calls == 2
    assert sleeps == [], "a 401 is answered by a new token, not by waiting"


def test_x_never_retries_an_answer_it_may_have_billed(keys, unpaced, sleeps, monkeypatch):
    """D-139: X bills what it serves. A 503 or a 429 is an answer."""
    for answer in (_response(503), _response(429, {"Retry-After": "1"})):
        script = _Script(answer, _response(200))
        monkeypatch.setattr(twitter_client.httpx, "get", script)
        with pytest.raises(httpx.HTTPStatusError):
            twitter_client.TwitterClient().search_recent("tides")
        assert script.calls == 1


def test_x_retries_a_request_nothing_answered(keys, unpaced, sleeps, monkeypatch):
    script = _Script(httpx.ConnectError("no route"), _response(200, json={"data": []}))
    monkeypatch.setattr(twitter_client.httpx, "get", script)

    assert twitter_client.TwitterClient().search_recent("tides") == {"data": []}
    assert script.calls == 2
    assert unpaced[-1].waits == 2


def test_a_real_limiter_spaces_the_retry_like_any_request(sleeps, monkeypatch):
    """The pacing holds across a retry: the second try waits out the
    client's spacing from the first, on top of the backoff."""
    waited: list[float] = []
    monkeypatch.setattr("app.utils.rate_limiter.time.sleep", waited.append)
    limiter = RateLimiter(rate=10.0)

    _http_retry.send(_Script(_response(503), _response(200)), url=URL, limiter=limiter)

    assert len(waited) == 1 and 9.0 < waited[0] <= 10.0

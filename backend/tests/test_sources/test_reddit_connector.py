"""Unit tests for the Reddit connector + flatten + client.

Strategy mirrors `test_youtube_connector.py`: mock the underlying client
so we lock down the *shape transformation* (Reddit JSON → typed
dataclasses) and *wiring* (which client method each connector method
calls), not Reddit's API behavior.

The connector reads the singleton via ``reddit_client.get_client()``;
tests patch that attribute on the imported module to inject a
``unittest.mock.Mock`` with the four wrapper methods.
"""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.sources import registry
from app.sources.reddit import client as reddit_client_mod
from app.sources.reddit import connector as rd_connector_mod
from app.sources.reddit import flatten as rd_flatten
from app.sources.reddit.client import (
    REDDIT_API_BASE,
    REDDIT_OAUTH_URL,
    RedditAuthError,
    RedditClient,
)
from app.sources.reddit.connector import RedditConnector
from app.sources.types import Candidate, ExtractedText, SourceMetadata


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def rd():
    return RedditConnector()


@pytest.fixture
def fake_client():
    """A Mock standing in for `RedditClient`. Patch `get_client` to return
    this fixture when the connector calls into the singleton."""
    return Mock(spec=RedditClient)


def _post(
    post_id: str = "abc123",
    title: str = "A title",
    author: str = "alice",
    selftext: str = "",
    score: int = 10,
    num_comments: int = 3,
    subreddit: str = "test",
    created_utc: float = 1_700_000_000.0,
    permalink: str = "/r/test/comments/abc123/a_title/",
    thumbnail: str = "",
    url: str = "https://www.reddit.com/r/test/comments/abc123",
) -> dict:
    """Build a Reddit `t3` post-data dict with sensible defaults."""
    return {
        "id": post_id,
        "title": title,
        "author": author,
        "selftext": selftext,
        "score": score,
        "num_comments": num_comments,
        "subreddit": subreddit,
        "created_utc": created_utc,
        "permalink": permalink,
        "thumbnail": thumbnail,
        "url": url,
    }


def _listing(*post_dicts: dict) -> dict:
    """Wrap post dicts as a Reddit `Listing` response."""
    return {
        "kind": "Listing",
        "data": {
            "children": [{"kind": "t3", "data": p} for p in post_dicts],
        },
    }


def _comment(
    body: str = "a comment",
    author: str = "bob",
    score: int = 5,
    cid: str = "c1",
    replies=None,
) -> dict:
    """Build a Reddit `t1` comment-data dict."""
    if replies is None:
        replies = ""  # Reddit returns "" (literal empty string) for childless comments
    return {
        "id": cid,
        "body": body,
        "author": author,
        "score": score,
        "replies": replies,
    }


def _comments_listing(*comments: dict) -> dict:
    return {
        "kind": "Listing",
        "data": {
            "children": [{"kind": "t1", "data": c} for c in comments],
        },
    }


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------
def test_search_site_wide_calls_client_search(rd, fake_client):
    fake_client.search.return_value = _listing(_post(post_id="xyz"))
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.search("monetary policy", instructions="ignored", limit=5)

    fake_client.search.assert_called_once_with("monetary policy", limit=5)
    fake_client.search_subreddit.assert_not_called()
    assert len(out) == 1
    c = out[0]
    assert isinstance(c, Candidate)
    assert c.source_type == "reddit_post"
    assert c.source_id == "reddit:xyz"
    assert c.title == "A title"
    assert c.creator_external_id == "alice"
    assert c.creator_name == "alice"
    assert c.source_url == "https://www.reddit.com/r/test/comments/abc123/a_title/"


def test_search_subreddit_prefix_calls_search_subreddit(rd, fake_client):
    fake_client.search_subreddit.return_value = _listing(_post(post_id="sub1"))
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.search("subreddit:economics tariffs in 2026", limit=10)

    fake_client.search_subreddit.assert_called_once_with("economics", "tariffs in 2026", limit=10)
    fake_client.search.assert_not_called()
    assert out[0].source_id == "reddit:sub1"


def test_search_returns_empty_when_no_children(rd, fake_client):
    fake_client.search.return_value = {"data": {"children": []}}
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        assert rd.search("nothing matches") == []


def test_search_skips_non_t3_children(rd, fake_client):
    """Reddit listings can include `more` ellipsis kinds — we only want posts."""
    fake_client.search.return_value = {
        "data": {
            "children": [
                {"kind": "more", "data": {"id": "skip"}},
                {"kind": "t3", "data": _post(post_id="keep")},
            ]
        }
    }
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.search("anything")
    assert [c.source_id for c in out] == ["reddit:keep"]


def test_search_handles_missing_optional_fields(rd, fake_client):
    """Search results sometimes omit thumbnails / permalink — must not crash."""
    sparse = {"id": "x", "title": "t", "author": "u"}
    fake_client.search.return_value = _listing(sparse)
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.search("anything")
    c = out[0]
    assert c.source_id == "reddit:x"
    assert c.published_at is None
    assert c.thumbnail_url is None
    # Falls back to /comments/<id> when permalink is missing.
    assert c.source_url == "https://www.reddit.com/comments/x"


def test_search_published_at_is_utc(rd, fake_client):
    """Reddit returns Unix epoch seconds; we promise tz-aware UTC."""
    p = _post(post_id="t1", created_utc=1_700_000_000.0)
    fake_client.search.return_value = _listing(p)
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.search("x")
    expected = datetime.fromtimestamp(1_700_000_000.0, tz=timezone.utc)
    assert out[0].published_at == expected


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------
def test_list_creator_items_yields_iterator(rd, fake_client):
    """Contract is `Iterable`; today it's a generator. Lock that in so we
    don't accidentally regress to a materialised list (memory blow-up on
    a prolific Redditor)."""
    fake_client.list_user_posts.return_value = _listing(_post(post_id="p1"))
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        gen = rd.list_creator_items("alice")
        assert hasattr(gen, "__next__")
        assert next(gen).source_id == "reddit:p1"


def test_list_creator_items_forwards_limit(rd, fake_client):
    fake_client.list_user_posts.return_value = _listing(_post(post_id="p1"))
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        list(rd.list_creator_items("alice", limit=7))
    fake_client.list_user_posts.assert_called_once_with("alice", limit=7)


def test_list_creator_items_default_limit_when_none(rd, fake_client):
    fake_client.list_user_posts.return_value = _listing()
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        list(rd.list_creator_items("alice"))
    # Default is 25 — a single Reddit page.
    fake_client.list_user_posts.assert_called_once_with("alice", limit=25)


# ---------------------------------------------------------------------------
# fetch_metadata()
# ---------------------------------------------------------------------------
def test_fetch_metadata_empty_short_circuits(rd, fake_client):
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        assert rd.fetch_metadata([]) == {}
    fake_client.get_json.assert_not_called()


def test_fetch_metadata_strips_prefix_and_prepends_t3(rd, fake_client):
    """`/api/info` accepts `t3_<id>,t3_<id>` — we must strip our `reddit:`
    prefix and add the `t3_` prefix Reddit expects."""
    fake_client.get_json.return_value = _listing(
        _post(post_id="abc"), _post(post_id="def")
    )
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.fetch_metadata(["reddit:abc", "reddit:def"])

    fake_client.get_json.assert_called_once_with("/api/info", params={"id": "t3_abc,t3_def"})
    assert set(out.keys()) == {"reddit:abc", "reddit:def"}
    sm = out["reddit:abc"]
    assert isinstance(sm, SourceMetadata)
    assert sm.title == "A title"
    assert sm.creator_external_id == "alice"
    assert sm.extra["subreddit"] == "test"
    assert sm.extra["score"] == 10


def test_fetch_metadata_tolerates_unprefixed_ids(rd, fake_client):
    """Forward-compat: if an upstream caller passes a bare `abc` ID we
    still accept it — but the response key is always namespaced."""
    fake_client.get_json.return_value = _listing(_post(post_id="abc"))
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.fetch_metadata(["abc"])

    fake_client.get_json.assert_called_once_with("/api/info", params={"id": "t3_abc"})
    assert "reddit:abc" in out


# ---------------------------------------------------------------------------
# fetch_text()
# ---------------------------------------------------------------------------
def _candidate(source_id: str = "reddit:abc") -> Candidate:
    return Candidate(
        source_type="reddit_post",
        source_id=source_id,
        title="t",
        source_url="https://www.reddit.com/comments/abc",
    )


def test_fetch_text_returns_extracted_text_on_success(rd, fake_client):
    post = _post(post_id="abc", title="Tariff debate", selftext="Body.")
    comments = _comments_listing(_comment(body="great point", score=10))
    fake_client.get_post_with_comments.return_value = [_listing(post), comments]

    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        out = rd.fetch_text(_candidate("reddit:abc"), job_id="job-7")

    fake_client.get_post_with_comments.assert_called_once()
    args, kwargs = fake_client.get_post_with_comments.call_args
    assert args == ("abc",)  # the prefix is stripped
    assert isinstance(out, ExtractedText)
    assert out.text_source == "reddit"
    assert out.language == "en"
    assert len(out.segments) == 2  # OP + 1 comment
    # OP segment carries the post's metadata in `extra`.
    assert out.segments[0]["extra"]["kind"] == "post"
    assert out.segments[1]["extra"]["kind"] == "comment"
    # ExtractedText.extra["classification"] is populated even with empty
    # query — fail-soft fallback (D-023). No LLM call when query is "".
    assert "classification" in out.extra
    assert out.extra["classification"]["stance"] == "unclear"
    assert out.extra["classification"]["topic_relevance"] == 0.0


def test_fetch_text_calls_classifier_when_query_is_present(rd, fake_client):
    """Per D-023: connector calls social_classify inline when the
    orchestrator passes a query. The classification result lands in
    ExtractedText.extra["classification"]."""
    post = _post(post_id="abc", title="Tariffs and trade", selftext="My take")
    comments = _comments_listing(_comment(body="agreed", score=10))
    fake_client.get_post_with_comments.return_value = [_listing(post), comments]

    fake_classification = {
        "stance": "for",
        "sentiment": "positive",
        "framing": "experiential",
        "topic_relevance": 0.85,
    }
    fake_classify_result = Mock()
    fake_classify_result.model_dump.return_value = fake_classification

    with (
        patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client),
        patch(
            "app.sources.reddit.connector.classify",
            return_value=fake_classify_result,
        ) as mock_classify,
    ):
        out = rd.fetch_text(
            _candidate("reddit:abc"), job_id="job-7", query="tariffs"
        )

    assert isinstance(out, ExtractedText)
    # Classifier was called with the OP+top-comment text and the query.
    mock_classify.assert_called_once()
    call_args = mock_classify.call_args
    assert call_args.kwargs.get("query", call_args.args[1] if len(call_args.args) > 1 else None) == "tariffs"
    # The classification round-trips into extra.
    assert out.extra["classification"] == fake_classification


def test_fetch_text_returns_none_on_client_exception(rd, fake_client):
    """Connector must report fetch failures as None, not crash the job."""
    fake_client.get_post_with_comments.side_effect = RuntimeError("boom")
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        assert rd.fetch_text(_candidate(), job_id="job-1") is None


def test_fetch_text_returns_none_on_empty_segments(rd, fake_client):
    """A post with no body and no comments yields no segments — orchestrator
    treats this as `text_status='unavailable'`."""
    post = _post(post_id="abc", title="", selftext="")
    fake_client.get_post_with_comments.return_value = [_listing(post), _comments_listing()]
    with patch.object(rd_connector_mod.reddit_client, "get_client", return_value=fake_client):
        assert rd.fetch_text(_candidate("reddit:abc")) is None


# ---------------------------------------------------------------------------
# Flatten module
# ---------------------------------------------------------------------------
def test_flatten_handles_malformed_listing():
    assert rd_flatten.flatten_post_with_comments([]) == ([], {})
    assert rd_flatten.flatten_post_with_comments([{"data": {"children": []}}, {}]) == ([], {})


def test_flatten_op_only_when_no_comments():
    post = _post(title="Hello", selftext="World")
    listing = [_listing(post), _comments_listing()]
    segments, post_data = rd_flatten.flatten_post_with_comments(listing)
    assert post_data["title"] == "Hello"
    assert len(segments) == 1
    assert "Hello" in segments[0]["text"]
    assert "World" in segments[0]["text"]
    assert segments[0]["extra"]["kind"] == "post"
    assert segments[0]["start"] == 0.0
    assert segments[0]["duration"] > 0


def test_flatten_sorts_comments_by_score_descending():
    post = _post(title="Q", selftext="")
    cs = _comments_listing(
        _comment(body="low", score=1, cid="a"),
        _comment(body="high", score=99, cid="b"),
        _comment(body="mid", score=10, cid="c"),
    )
    segments, _ = rd_flatten.flatten_post_with_comments([_listing(post), cs])
    # OP first, then comments by score desc.
    bodies = [s["text"] for s in segments]
    assert "Q" in bodies[0]
    assert "(score 99)" in bodies[1]
    assert "(score 10)" in bodies[2]
    assert "(score 1)" in bodies[3]


def test_flatten_truncates_to_top_n():
    post = _post(title="Q", selftext="")
    cs = _comments_listing(
        *[_comment(body=f"c{i}", score=i, cid=f"x{i}") for i in range(20)]
    )
    segments, _ = rd_flatten.flatten_post_with_comments([_listing(post), cs], top_n=5)
    # 1 OP + 5 comments = 6 segments
    assert len(segments) == 6


def test_flatten_renders_depth_markers_for_replies():
    """Replies retain ``↳`` markers so the reader sees threading even
    after score-sorting flattens the tree."""
    reply = _comment(body="reply", score=2, cid="r1")
    parent = _comment(
        body="parent",
        score=5,
        cid="p1",
        replies=_comments_listing(reply),
    )
    post = _post(title="Q", selftext="")
    segments, _ = rd_flatten.flatten_post_with_comments(
        [_listing(post), _comments_listing(parent)]
    )
    assert any("\u21b3" in s["text"] for s in segments if s["extra"].get("depth", 0) > 0)
    # Depth value tracked in extra.
    depths = [s["extra"].get("depth") for s in segments if s["extra"]["kind"] == "comment"]
    assert 1 in depths


def test_flatten_skips_more_placeholders():
    """`kind: more` collapsed-replies markers are skipped — expanding them
    would require extra API calls (deferred)."""
    listing = [
        _listing(_post(title="Q", selftext="")),
        {
            "data": {
                "children": [
                    {"kind": "more", "data": {"id": "m1"}},
                    {"kind": "t1", "data": _comment(body="real", score=1)},
                ]
            }
        },
    ]
    segments, _ = rd_flatten.flatten_post_with_comments(listing)
    # OP + 1 comment, the `more` was skipped.
    assert len(segments) == 2


def test_flatten_skips_empty_comment_bodies():
    """`[deleted]` comments often have empty body — drop them."""
    listing = [
        _listing(_post(title="Q", selftext="")),
        _comments_listing(
            _comment(body="", score=10, author="[deleted]"),
            _comment(body="real", score=1),
        ),
    ]
    segments, _ = rd_flatten.flatten_post_with_comments(listing)
    assert len(segments) == 2  # OP + the real comment only


def test_flatten_segments_have_monotonic_timestamps():
    post = _post(title="Q", selftext="body here")
    cs = _comments_listing(
        _comment(body="first", score=10),
        _comment(body="second longer comment text", score=5),
    )
    segments, _ = rd_flatten.flatten_post_with_comments([_listing(post), cs])
    # start values must be monotonic, durations positive.
    starts = [s["start"] for s in segments]
    durations = [s["duration"] for s in segments]
    assert starts == sorted(starts)
    assert all(d > 0 for d in durations)


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------
def test_connector_source_type_is_reddit_post():
    """Locks the discriminator — changing this would silently break
    every row in `documents` with `source_type='reddit_post'`."""
    assert RedditConnector.source_type == "reddit_post"


def test_connector_registers_under_reddit_post():
    """Importing the connector module at top of this file should have
    eagerly registered the connector. Verify the registry agrees."""
    from app.sources.reddit import connector as _  # noqa: F401  re-import is idempotent

    got = registry.connector_for("reddit_post")
    assert isinstance(got, RedditConnector)


# ---------------------------------------------------------------------------
# Client: token caching + 401 retry + missing creds
# ---------------------------------------------------------------------------
def test_client_raises_when_credentials_missing(monkeypatch):
    """Empty `REDDIT_CLIENT_ID`/`SECRET` → `RedditAuthError`. The
    config defaults are empty strings, so the unconfigured production
    state must surface a clear error (not a vague httpx failure)."""
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_ID", "")
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_SECRET", "")
    c = RedditClient()
    with pytest.raises(RedditAuthError, match="REDDIT_CLIENT_ID"):
        c._get_token()


def test_client_caches_token_across_calls(monkeypatch):
    """Two `get_json` calls in a row should fetch the token once."""
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_ID", "id")
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_SECRET", "secret")

    token_resp = Mock()
    token_resp.json.return_value = {"access_token": "TOK"}
    token_resp.raise_for_status = Mock()

    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"data": {"children": []}}
    api_resp.raise_for_status = Mock()

    with (
        patch.object(reddit_client_mod.httpx, "post", return_value=token_resp) as mock_post,
        patch.object(reddit_client_mod.httpx, "get", return_value=api_resp) as mock_get,
    ):
        c = RedditClient()
        c.get_json("/search", params={"q": "x"})
        c.get_json("/search", params={"q": "y"})

    # Token endpoint hit once; API endpoint hit twice.
    assert mock_post.call_count == 1
    assert mock_get.call_count == 2
    assert mock_post.call_args.args[0] == REDDIT_OAUTH_URL
    assert mock_get.call_args_list[0].args[0].startswith(REDDIT_API_BASE)


def test_client_refreshes_token_on_401(monkeypatch):
    """A 401 from the API endpoint forces a token re-fetch and a single retry."""
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_ID", "id")
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_SECRET", "secret")

    token_resp = Mock()
    token_resp.json.return_value = {"access_token": "TOK"}
    token_resp.raise_for_status = Mock()

    bad_resp = Mock(status_code=401)
    bad_resp.raise_for_status = Mock()
    good_resp = Mock(status_code=200)
    good_resp.json.return_value = {"ok": True}
    good_resp.raise_for_status = Mock()

    with (
        patch.object(reddit_client_mod.httpx, "post", return_value=token_resp) as mock_post,
        patch.object(
            reddit_client_mod.httpx,
            "get",
            side_effect=[bad_resp, good_resp],
        ) as mock_get,
    ):
        c = RedditClient()
        result = c.get_json("/search")

    assert result == {"ok": True}
    assert mock_post.call_count == 2  # initial + refresh
    assert mock_get.call_count == 2  # 401 then success


def test_client_raises_on_persistent_auth_failure(monkeypatch):
    """If the second attempt also returns 401, raise — don't loop forever."""
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_ID", "id")
    monkeypatch.setattr(reddit_client_mod.settings, "REDDIT_CLIENT_SECRET", "secret")

    token_resp = Mock()
    token_resp.json.return_value = {"access_token": "TOK"}
    token_resp.raise_for_status = Mock()

    # The second attempt's 401 reaches `raise_for_status` because the
    # retry guard only fires on the *first* attempt.
    persist_401 = Mock(status_code=401)
    import httpx as _httpx

    persist_401.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "401", request=Mock(), response=persist_401
    )

    with (
        patch.object(reddit_client_mod.httpx, "post", return_value=token_resp),
        patch.object(reddit_client_mod.httpx, "get", return_value=persist_401),
    ):
        c = RedditClient()
        with pytest.raises(_httpx.HTTPStatusError):
            c.get_json("/search")

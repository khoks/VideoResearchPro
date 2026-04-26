"""Unit tests for the Hacker News connector + flatten + client.

Strategy mirrors `test_reddit_connector.py`: mock the underlying client
so we lock down the *shape transformation* (Algolia JSON → typed
dataclasses) and *wiring* (which client method each connector method
calls), not Algolia's API behavior.

The connector reads the singleton via ``hn_client.get_client()``;
tests patch that attribute on the imported module to inject a
``unittest.mock.Mock`` with the four wrapper methods.
"""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.sources import registry
from app.sources.hn import client as hn_client_mod
from app.sources.hn import connector as hn_connector_mod
from app.sources.hn import flatten as hn_flatten
from app.sources.hn.client import HN_API_BASE, HNClient
from app.sources.hn.connector import HNConnector
from app.sources.types import Candidate, ExtractedText, SourceMetadata


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def hn():
    return HNConnector()


@pytest.fixture
def fake_client():
    """A Mock standing in for `HNClient`. Patch `get_client` to return
    this fixture when the connector calls into the singleton."""
    return Mock(spec=HNClient)


def _hit(
    object_id: str = "12345",
    title: str = "A title",
    author: str = "alice",
    story_text: str = "",
    points: int = 10,
    num_comments: int = 3,
    created_at_i: int = 1_700_000_000,
    url: str | None = "https://example.com/article",
) -> dict:
    """Build an Algolia search-hit dict with sensible defaults.

    Note: search hits use ``objectID`` (string) and store body text in
    ``story_text`` — different shape from the ``/items`` payload.
    """
    return {
        "objectID": object_id,
        "title": title,
        "author": author,
        "story_text": story_text,
        "points": points,
        "num_comments": num_comments,
        "created_at_i": created_at_i,
        "url": url,
    }


def _search_payload(*hits: dict) -> dict:
    return {"hits": list(hits), "nbHits": len(hits), "page": 0}


def _item(
    item_id: int = 12345,
    title: str = "A title",
    author: str = "alice",
    text: str = "",
    points: int = 10,
    created_at_i: int = 1_700_000_000,
    url: str | None = "https://example.com/article",
    children: list | None = None,
) -> dict:
    """Build an Algolia ``/items/<id>`` payload with sensible defaults.

    Note: items use ``id`` (int), store body text in ``text``, and
    nest the comment tree under ``children`` recursively.
    """
    return {
        "id": item_id,
        "type": "story",
        "title": title,
        "author": author,
        "text": text,
        "points": points,
        "created_at_i": created_at_i,
        "url": url,
        "children": children or [],
    }


def _comment(
    text: str = "a comment",
    author: str = "bob",
    points: int = 5,
    cid: int = 1,
    children: list | None = None,
) -> dict:
    """Build an Algolia comment-children dict."""
    return {
        "id": cid,
        "type": "comment",
        "author": author,
        "text": text,
        "points": points,
        "children": children or [],
    }


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------
def test_search_calls_client_search(hn, fake_client):
    fake_client.search.return_value = _search_payload(_hit(object_id="xyz"))
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.search("monetary policy", instructions="ignored", limit=5)

    fake_client.search.assert_called_once_with("monetary policy", limit=5)
    assert len(out) == 1
    c = out[0]
    assert isinstance(c, Candidate)
    assert c.source_type == "hn_story"
    assert c.source_id == "hn:xyz"
    assert c.title == "A title"
    assert c.creator_external_id == "alice"
    assert c.creator_name == "alice"
    # Canonical URL is the HN discussion page, not the linked article.
    assert c.source_url == "https://news.ycombinator.com/item?id=xyz"
    # The article URL lives in `extra` so callers can dereference if they want.
    assert c.extra["url"] == "https://example.com/article"


def test_search_returns_empty_when_no_hits(hn, fake_client):
    fake_client.search.return_value = _search_payload()
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        assert hn.search("nothing matches") == []


def test_search_handles_missing_optional_fields(hn, fake_client):
    """Search hits sometimes omit url / story_text — must not crash."""
    sparse = {"objectID": "x", "title": "t", "author": "u"}
    fake_client.search.return_value = _search_payload(sparse)
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.search("anything")
    c = out[0]
    assert c.source_id == "hn:x"
    assert c.published_at is None
    assert c.thumbnail_url is None
    assert c.source_url == "https://news.ycombinator.com/item?id=x"


def test_search_published_at_is_utc(hn, fake_client):
    """Algolia returns Unix epoch seconds in `created_at_i`; we promise tz-aware UTC."""
    fake_client.search.return_value = _search_payload(_hit(object_id="t1"))
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.search("x")
    expected = datetime.fromtimestamp(1_700_000_000.0, tz=timezone.utc)
    assert out[0].published_at == expected


def test_search_uses_story_text_for_description(hn, fake_client):
    """Self-posts (no url) carry their body in `story_text`. We surface the
    first 500 chars as `description`."""
    h = _hit(object_id="self1", story_text="A long Ask HN body.", url=None)
    fake_client.search.return_value = _search_payload(h)
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.search("ask hn")
    assert out[0].description == "A long Ask HN body."


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------
def test_list_creator_items_yields_iterator(hn, fake_client):
    """Contract is `Iterable`; today it's a generator. Lock that in so we
    don't accidentally regress to a materialised list (memory blow-up on
    a prolific submitter)."""
    fake_client.search_by_author.return_value = _search_payload(_hit(object_id="p1"))
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        gen = hn.list_creator_items("alice")
        assert hasattr(gen, "__next__")
        assert next(gen).source_id == "hn:p1"


def test_list_creator_items_forwards_limit(hn, fake_client):
    fake_client.search_by_author.return_value = _search_payload(_hit(object_id="p1"))
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        list(hn.list_creator_items("alice", limit=7))
    fake_client.search_by_author.assert_called_once_with("alice", limit=7)


def test_list_creator_items_default_limit_when_none(hn, fake_client):
    fake_client.search_by_author.return_value = _search_payload()
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        list(hn.list_creator_items("alice"))
    # Default is 25 — a single Algolia page.
    fake_client.search_by_author.assert_called_once_with("alice", limit=25)


# ---------------------------------------------------------------------------
# fetch_metadata()
# ---------------------------------------------------------------------------
def test_fetch_metadata_empty_short_circuits(hn, fake_client):
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        assert hn.fetch_metadata([]) == {}
    fake_client.get_item.assert_not_called()


def test_fetch_metadata_calls_get_item_per_id(hn, fake_client):
    """Algolia has no batch endpoint — connector iterates."""
    fake_client.get_item.side_effect = [
        _item(item_id=111, title="First"),
        _item(item_id=222, title="Second"),
    ]
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.fetch_metadata(["hn:111", "hn:222"])

    assert fake_client.get_item.call_count == 2
    assert {c.args[0] for c in fake_client.get_item.call_args_list} == {"111", "222"}
    assert set(out.keys()) == {"hn:111", "hn:222"}
    sm = out["hn:111"]
    assert isinstance(sm, SourceMetadata)
    assert sm.title == "First"
    assert sm.creator_external_id == "alice"
    assert sm.extra["points"] == 10


def test_fetch_metadata_tolerates_unprefixed_ids(hn, fake_client):
    """Forward-compat: if an upstream caller passes a bare id we still
    accept it — but the response key is always namespaced."""
    fake_client.get_item.return_value = _item(item_id=999, title="t")
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.fetch_metadata(["999"])

    fake_client.get_item.assert_called_once_with("999")
    assert "hn:999" in out


def test_fetch_metadata_skips_non_story_items(hn, fake_client):
    """If `/items/<id>` returns a comment (because the id was actually a
    comment, not a story), we skip silently rather than mis-typing it."""
    comment_payload = {"id": 1, "type": "comment", "text": "x"}
    fake_client.get_item.return_value = comment_payload
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.fetch_metadata(["hn:1"])
    assert out == {}


def test_fetch_metadata_swallows_per_item_failures(hn, fake_client):
    """One bad id mustn't poison the whole batch."""
    fake_client.get_item.side_effect = [
        RuntimeError("boom"),
        _item(item_id=222, title="ok"),
    ]
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.fetch_metadata(["hn:111", "hn:222"])
    assert list(out.keys()) == ["hn:222"]


# ---------------------------------------------------------------------------
# fetch_text()
# ---------------------------------------------------------------------------
def _candidate(source_id: str = "hn:12345") -> Candidate:
    return Candidate(
        source_type="hn_story",
        source_id=source_id,
        title="t",
        source_url="https://news.ycombinator.com/item?id=12345",
    )


def test_fetch_text_returns_extracted_text_on_success(hn, fake_client):
    item = _item(
        item_id=12345,
        title="Tariff debate",
        text="<p>Body paragraph.</p>",
        children=[_comment(text="<p>great point</p>", points=10, cid=1)],
    )
    fake_client.get_item.return_value = item

    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        out = hn.fetch_text(_candidate("hn:12345"), job_id="job-7")

    fake_client.get_item.assert_called_once()
    args, _kwargs = fake_client.get_item.call_args
    assert args == ("12345",)  # the prefix is stripped
    assert isinstance(out, ExtractedText)
    assert out.text_source == "hn"
    assert out.language == "en"
    assert len(out.segments) == 2  # OP + 1 comment
    assert out.segments[0]["extra"]["kind"] == "story"
    assert out.segments[1]["extra"]["kind"] == "comment"
    # HTML must be stripped from the rendered text.
    assert "<p>" not in out.segments[0]["text"]
    assert "<p>" not in out.segments[1]["text"]


def test_fetch_text_returns_none_on_client_exception(hn, fake_client):
    """Connector must report fetch failures as None, not crash the job."""
    fake_client.get_item.side_effect = RuntimeError("boom")
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        assert hn.fetch_text(_candidate(), job_id="job-1") is None


def test_fetch_text_returns_none_on_empty_segments(hn, fake_client):
    """A story with no body and no comments yields no segments."""
    item = _item(item_id=12345, title="", text="", children=[])
    fake_client.get_item.return_value = item
    with patch.object(hn_connector_mod.hn_client, "get_client", return_value=fake_client):
        assert hn.fetch_text(_candidate("hn:12345")) is None


# ---------------------------------------------------------------------------
# Flatten module
# ---------------------------------------------------------------------------
def test_flatten_handles_malformed_payload():
    assert hn_flatten.flatten_story_with_comments([]) == ([], {})  # type: ignore[arg-type]
    assert hn_flatten.flatten_story_with_comments({"type": "comment"}) == ([], {})
    assert hn_flatten.flatten_story_with_comments({}) == ([], {})


def test_flatten_op_only_when_no_comments():
    item = _item(title="Hello", text="World", children=[])
    segments, story_data = hn_flatten.flatten_story_with_comments(item)
    assert story_data["title"] == "Hello"
    assert len(segments) == 1
    assert "Hello" in segments[0]["text"]
    assert "World" in segments[0]["text"]
    assert segments[0]["extra"]["kind"] == "story"
    assert segments[0]["start"] == 0.0
    assert segments[0]["duration"] > 0


def test_flatten_sorts_comments_by_points_descending():
    item = _item(title="Q", text="", children=[
        _comment(text="low", points=1, cid=1),
        _comment(text="high", points=99, cid=2),
        _comment(text="mid", points=10, cid=3),
    ])
    segments, _ = hn_flatten.flatten_story_with_comments(item)
    bodies = [s["text"] for s in segments]
    assert "Q" in bodies[0]
    assert "(points 99)" in bodies[1]
    assert "(points 10)" in bodies[2]
    assert "(points 1)" in bodies[3]


def test_flatten_truncates_to_top_n():
    item = _item(title="Q", text="", children=[
        _comment(text=f"c{i}", points=i, cid=i) for i in range(20)
    ])
    segments, _ = hn_flatten.flatten_story_with_comments(item, top_n=5)
    # 1 OP + 5 comments = 6 segments
    assert len(segments) == 6


def test_flatten_renders_depth_markers_for_replies():
    """Replies retain ``↳`` markers so the reader sees threading even
    after points-sorting flattens the tree."""
    reply = _comment(text="reply", points=2, cid=2)
    parent = _comment(text="parent", points=5, cid=1, children=[reply])
    item = _item(title="Q", text="", children=[parent])
    segments, _ = hn_flatten.flatten_story_with_comments(item)
    assert any("\u21b3" in s["text"] for s in segments if s["extra"].get("depth", 0) > 0)
    depths = [s["extra"].get("depth") for s in segments if s["extra"]["kind"] == "comment"]
    assert 1 in depths


def test_flatten_skips_dead_comment_bodies():
    """Deleted/dead comments have empty text — drop them."""
    item = _item(title="Q", text="", children=[
        _comment(text="", points=10, author="[deleted]", cid=1),
        _comment(text="real", points=1, cid=2),
    ])
    segments, _ = hn_flatten.flatten_story_with_comments(item)
    assert len(segments) == 2  # OP + the real comment only


def test_flatten_strips_html_from_bodies():
    """HN delivers comment text as HTML (`<p>`, `<a>`, entities). We
    scrub it cheaply so the chunker sees plain prose."""
    item = _item(
        title="Q",
        text='<p>It&#x27;s &quot;great&quot;</p>',
        children=[
            _comment(
                text='<p>See <a href="https://x.com">link</a></p><p>and more</p>',
                points=5,
                cid=1,
            )
        ],
    )
    segments, _ = hn_flatten.flatten_story_with_comments(item)
    # Entities decoded, tags removed.
    assert "It's \"great\"" in segments[0]["text"]
    assert "<p>" not in segments[0]["text"]
    assert "See link" in segments[1]["text"]
    assert "and more" in segments[1]["text"]


def test_flatten_segments_have_monotonic_timestamps():
    item = _item(title="Q", text="body here", children=[
        _comment(text="first", points=10, cid=1),
        _comment(text="second longer comment text", points=5, cid=2),
    ])
    segments, _ = hn_flatten.flatten_story_with_comments(item)
    starts = [s["start"] for s in segments]
    durations = [s["duration"] for s in segments]
    assert starts == sorted(starts)
    assert all(d > 0 for d in durations)


def test_flatten_skips_non_comment_children():
    """Algolia trees can theoretically include non-comment children
    (e.g. nested polls). Filter them out, keep only `type=='comment'`."""
    item = _item(title="Q", text="", children=[
        {"id": 1, "type": "pollopt", "text": "ignored", "points": 100},
        _comment(text="real", points=1, cid=2),
    ])
    segments, _ = hn_flatten.flatten_story_with_comments(item)
    assert len(segments) == 2  # OP + the real comment


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------
def test_connector_source_type_is_hn_story():
    """Locks the discriminator — changing this would silently break
    every row in `documents` with `source_type='hn_story'`."""
    assert HNConnector.source_type == "hn_story"


def test_connector_registers_under_hn_story():
    """Importing the connector module at top of this file should have
    eagerly registered the connector. Verify the registry agrees."""
    from app.sources.hn import connector as _  # noqa: F401  re-import is idempotent

    got = registry.connector_for("hn_story")
    assert isinstance(got, HNConnector)


# ---------------------------------------------------------------------------
# Client: rate-limited GET against the public Algolia endpoint
# ---------------------------------------------------------------------------
def test_client_get_json_hits_algolia_base():
    """Smoke check: `get_json` calls `httpx.get` against `HN_API_BASE + path`
    with the expected User-Agent header."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"hits": []}
    api_resp.raise_for_status = Mock()

    with patch.object(hn_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = HNClient()
        result = c.get_json("/search", params={"query": "x"})

    assert result == {"hits": []}
    assert mock_get.call_count == 1
    called_url = mock_get.call_args.args[0]
    assert called_url.startswith(HN_API_BASE)
    headers = mock_get.call_args.kwargs["headers"]
    assert "User-Agent" in headers


def test_client_get_json_raises_on_http_error():
    """Non-2xx surfaces as `httpx.HTTPError` — there's no auth retry path
    because the endpoint is unauthenticated."""
    import httpx as _httpx

    bad_resp = Mock(status_code=500)
    bad_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "500", request=Mock(), response=bad_resp
    )

    with patch.object(hn_client_mod.httpx, "get", return_value=bad_resp):
        c = HNClient()
        with pytest.raises(_httpx.HTTPStatusError):
            c.get_json("/search")


def test_client_search_wrapper_sends_story_tag():
    """`search()` must restrict to `tags=story` so comments don't leak
    into discovery."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"hits": []}
    api_resp.raise_for_status = Mock()

    with patch.object(hn_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = HNClient()
        c.search("rust async", limit=15)

    params = mock_get.call_args.kwargs["params"]
    assert params == {"query": "rust async", "tags": "story", "hitsPerPage": 15}


def test_client_search_by_author_uses_search_by_date_endpoint():
    """`search_by_author` must use `/search_by_date` (recency order) with
    the `author_<name>` tag composite."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"hits": []}
    api_resp.raise_for_status = Mock()

    with patch.object(hn_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = HNClient()
        c.search_by_author("pg", limit=10)

    called_url = mock_get.call_args.args[0]
    params = mock_get.call_args.kwargs["params"]
    assert called_url.endswith("/search_by_date")
    assert params == {"tags": "story,author_pg", "hitsPerPage": 10}

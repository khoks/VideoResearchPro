"""Unit tests for the Bluesky connector + flatten + client.

Strategy mirrors `test_mastodon_connector.py` / `test_hn_connector.py`:
mock the underlying client so we lock down the *shape transformation*
(AT-Proto JSON → typed dataclasses) and *wiring* (which client method
each connector method calls), not the upstream API behavior.

The connector reads the singleton via ``bluesky_client.get_client()``;
tests patch that attribute on the imported module to inject a
``unittest.mock.Mock`` with the wrapper methods.
"""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.sources import registry
from app.sources.bluesky import client as bluesky_client_mod
from app.sources.bluesky import connector as bluesky_connector_mod
from app.sources.bluesky import flatten as bluesky_flatten
from app.sources.bluesky.client import BlueskyClient
from app.sources.bluesky.connector import BlueskyConnector
from app.sources.types import Candidate, ExtractedText, SourceMetadata


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def bsky():
    return BlueskyConnector()


@pytest.fixture
def fake_client():
    """A Mock standing in for `BlueskyClient`. Patch `get_client` to
    return this fixture when the connector calls into the singleton."""
    return Mock(spec=BlueskyClient)


def _author(
    handle: str = "alice.bsky.social",
    did: str = "did:plc:abc",
    display_name: str = "Alice",
) -> dict:
    return {"did": did, "handle": handle, "displayName": display_name}


def _post(
    uri: str = "at://did:plc:abc/app.bsky.feed.post/post1",
    cid: str = "cid-1",
    text: str = "A post body.",
    author: dict | None = None,
    created_at: str = "2024-01-15T12:00:00.000Z",
    likes: int = 5,
    reposts: int = 2,
    replies: int = 3,
    embed_image_thumb: str | None = None,
    langs: list[str] | None = None,
) -> dict:
    if author is None:
        author = _author()
    record: dict = {"text": text, "createdAt": created_at, "$type": "app.bsky.feed.post"}
    if langs:
        record["langs"] = langs
    p: dict = {
        "uri": uri,
        "cid": cid,
        "author": author,
        "record": record,
        "likeCount": likes,
        "repostCount": reposts,
        "replyCount": replies,
        "indexedAt": created_at,
    }
    if embed_image_thumb:
        p["embed"] = {
            "$type": "app.bsky.embed.images#view",
            "images": [{"thumb": embed_image_thumb, "fullsize": embed_image_thumb}],
        }
    return p


def _search_payload(*posts: dict) -> dict:
    return {"posts": list(posts)}


def _author_feed_payload(*posts: dict, with_repost: bool = False) -> dict:
    feed = []
    for p in posts:
        feed.append({"post": p})
    if with_repost:
        # Reposts carry a `reason.$type === '...#reasonRepost'` block.
        feed.append(
            {
                "post": _post(uri="at://did:plc:abc/app.bsky.feed.post/repost"),
                "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
            }
        )
    return {"feed": feed}


def _thread(post: dict, replies: list[dict] | None = None) -> dict:
    """Wrap a post in a thread shape, recursively turning replies into
    threadView nodes too."""
    node = {"post": post}
    if replies:
        node["replies"] = replies
    return node


def _thread_payload(post: dict, replies: list[dict] | None = None) -> dict:
    """Top-level getPostThread response shape."""
    return {"thread": _thread(post, replies)}


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------
def test_search_calls_search_posts(bsky, fake_client):
    fake_client.search_posts.return_value = _search_payload(
        _post(uri="at://did:plc:abc/app.bsky.feed.post/p1")
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.search("monetary policy", instructions="ignored", limit=5)

    fake_client.search_posts.assert_called_once_with("monetary policy", limit=5)
    assert len(out) == 1
    c = out[0]
    assert isinstance(c, Candidate)
    assert c.source_type == "bluesky_post"
    assert c.source_id == "bluesky:at://did:plc:abc/app.bsky.feed.post/p1"
    assert c.creator_external_id == "alice.bsky.social"
    assert c.creator_name == "Alice"
    # source_url is the bsky.app web URL (handle-based, browser-friendly).
    assert c.source_url == "https://bsky.app/profile/alice.bsky.social/post/p1"


def test_search_returns_empty_when_query_blank(bsky, fake_client):
    """Whitespace-only queries shouldn't trigger an HTTP call."""
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.search("   ")
    assert out == []
    fake_client.search_posts.assert_not_called()


def test_search_returns_empty_when_search_raises(bsky, fake_client):
    """Connector failures must degrade to empty list, not bubble."""
    fake_client.search_posts.side_effect = RuntimeError("503")
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.search("anything")
    assert out == []


def test_search_published_at_is_utc(bsky, fake_client):
    fake_client.search_posts.return_value = _search_payload(
        _post(uri="at://did:plc:abc/app.bsky.feed.post/t1")
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.search("x")
    expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert out[0].published_at == expected


def test_search_extracts_thumbnail_from_image_embed(bsky, fake_client):
    fake_client.search_posts.return_value = _search_payload(
        _post(
            uri="at://did:plc:abc/app.bsky.feed.post/m",
            embed_image_thumb="https://cdn.bsky.app/thumb.jpg",
        )
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.search("x")
    assert out[0].thumbnail_url == "https://cdn.bsky.app/thumb.jpg"


def test_search_handles_empty_record(bsky, fake_client):
    """Posts with no record shouldn't crash — defensive shape handling."""
    sparse = {
        "uri": "at://did:plc:abc/app.bsky.feed.post/x",
        "author": {"handle": "alice.bsky.social", "did": "did:plc:abc"},
    }
    fake_client.search_posts.return_value = _search_payload(sparse)
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.search("anything")
    c = out[0]
    assert c.source_id == "bluesky:at://did:plc:abc/app.bsky.feed.post/x"
    assert c.published_at is None


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------
def test_list_creator_items_yields_iterator(bsky, fake_client):
    """Contract is `Iterable`; today it's a generator."""
    fake_client.get_author_feed.return_value = _author_feed_payload(
        _post(uri="at://did:plc:abc/app.bsky.feed.post/p1")
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        gen = bsky.list_creator_items("alice.bsky.social")
        assert hasattr(gen, "__next__")
        first = next(gen)
        assert first.source_id == "bluesky:at://did:plc:abc/app.bsky.feed.post/p1"


def test_list_creator_items_forwards_limit(bsky, fake_client):
    fake_client.get_author_feed.return_value = _author_feed_payload()
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        list(bsky.list_creator_items("alice.bsky.social", limit=7))
    fake_client.get_author_feed.assert_called_once_with("alice.bsky.social", limit=7)


def test_list_creator_items_default_limit_when_none(bsky, fake_client):
    fake_client.get_author_feed.return_value = _author_feed_payload()
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        list(bsky.list_creator_items("alice.bsky.social"))
    fake_client.get_author_feed.assert_called_once_with(
        "alice.bsky.social", limit=25
    )


def test_list_creator_items_skips_reposts(bsky, fake_client):
    """Reposts inflate creator-feed candidates without adding new
    authored content — connector skips them."""
    fake_client.get_author_feed.return_value = _author_feed_payload(
        _post(uri="at://did:plc:abc/app.bsky.feed.post/p1"),
        _post(uri="at://did:plc:abc/app.bsky.feed.post/p2"),
        with_repost=True,
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = list(bsky.list_creator_items("alice.bsky.social"))
    assert len(out) == 2  # repost excluded
    assert {c.source_id for c in out} == {
        "bluesky:at://did:plc:abc/app.bsky.feed.post/p1",
        "bluesky:at://did:plc:abc/app.bsky.feed.post/p2",
    }


def test_list_creator_items_returns_nothing_when_feed_raises(bsky, fake_client):
    fake_client.get_author_feed.side_effect = RuntimeError("404")
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = list(bsky.list_creator_items("ghost.bsky.social"))
    assert out == []


# ---------------------------------------------------------------------------
# resolve_creator_id()
# ---------------------------------------------------------------------------
def test_resolve_creator_id_strips_at_prefix(bsky, fake_client):
    fake_client.get_profile.return_value = {
        "did": "did:plc:abc",
        "handle": "alice.bsky.social",
    }
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        got = bsky.resolve_creator_id("@alice.bsky.social")
    fake_client.get_profile.assert_called_once_with("alice.bsky.social")
    assert got == "alice.bsky.social"


def test_resolve_creator_id_parses_profile_url(bsky, fake_client):
    fake_client.get_profile.return_value = {
        "did": "did:plc:abc",
        "handle": "alice.bsky.social",
    }
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        got = bsky.resolve_creator_id("https://bsky.app/profile/alice.bsky.social")
    fake_client.get_profile.assert_called_once_with("alice.bsky.social")
    assert got == "alice.bsky.social"


def test_resolve_creator_id_accepts_did(bsky, fake_client):
    fake_client.get_profile.return_value = {
        "did": "did:plc:abc",
        "handle": "alice.bsky.social",
    }
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        got = bsky.resolve_creator_id("did:plc:abc")
    fake_client.get_profile.assert_called_once_with("did:plc:abc")
    # Connector returns the canonical handle when the profile carries one.
    assert got == "alice.bsky.social"


def test_resolve_creator_id_returns_none_on_lookup_error(bsky, fake_client):
    fake_client.get_profile.side_effect = RuntimeError("404")
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        assert bsky.resolve_creator_id("@ghost.bsky.social") is None


def test_resolve_creator_id_returns_none_on_empty_hint(bsky, fake_client):
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        assert bsky.resolve_creator_id("") is None
    fake_client.get_profile.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_metadata()
# ---------------------------------------------------------------------------
def test_fetch_metadata_empty_short_circuits(bsky, fake_client):
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        assert bsky.fetch_metadata([]) == {}
    fake_client.get_post_thread.assert_not_called()


def test_fetch_metadata_calls_get_post_thread_per_uri(bsky, fake_client):
    """AT-Proto has no batch endpoint — connector iterates."""
    p1 = _post(uri="at://did:plc:abc/app.bsky.feed.post/111", text="First")
    p2 = _post(uri="at://did:plc:abc/app.bsky.feed.post/222", text="Second")
    fake_client.get_post_thread.side_effect = [
        _thread_payload(p1),
        _thread_payload(p2),
    ]
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.fetch_metadata([
            "bluesky:at://did:plc:abc/app.bsky.feed.post/111",
            "bluesky:at://did:plc:abc/app.bsky.feed.post/222",
        ])

    assert fake_client.get_post_thread.call_count == 2
    assert set(out.keys()) == {
        "bluesky:at://did:plc:abc/app.bsky.feed.post/111",
        "bluesky:at://did:plc:abc/app.bsky.feed.post/222",
    }
    sm = out["bluesky:at://did:plc:abc/app.bsky.feed.post/111"]
    assert isinstance(sm, SourceMetadata)
    assert sm.creator_external_id == "alice.bsky.social"
    assert sm.extra["likeCount"] == 5


def test_fetch_metadata_skips_malformed_uris(bsky, fake_client):
    """Forward-compat: bare/legacy IDs that don't match the AT-URI
    shape are skipped rather than crashing the batch."""
    fake_client.get_post_thread.return_value = _thread_payload(
        _post(uri="at://did:plc:abc/app.bsky.feed.post/ok")
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.fetch_metadata([
            "not-an-at-uri",
            "bluesky:at://did:plc:abc/app.bsky.feed.post/ok",
        ])
    fake_client.get_post_thread.assert_called_once()
    assert "bluesky:at://did:plc:abc/app.bsky.feed.post/ok" in out


def test_fetch_metadata_swallows_per_item_failures(bsky, fake_client):
    fake_client.get_post_thread.side_effect = [
        RuntimeError("boom"),
        _thread_payload(_post(uri="at://did:plc:abc/app.bsky.feed.post/222")),
    ]
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.fetch_metadata([
            "bluesky:at://did:plc:abc/app.bsky.feed.post/111",
            "bluesky:at://did:plc:abc/app.bsky.feed.post/222",
        ])
    assert list(out.keys()) == ["bluesky:at://did:plc:abc/app.bsky.feed.post/222"]


# ---------------------------------------------------------------------------
# fetch_text()
# ---------------------------------------------------------------------------
def _candidate(
    source_id: str = "bluesky:at://did:plc:abc/app.bsky.feed.post/100",
) -> Candidate:
    return Candidate(
        source_type="bluesky_post",
        source_id=source_id,
        title="t",
        source_url="https://bsky.app/profile/alice.bsky.social/post/100",
    )


def test_fetch_text_returns_extracted_text_on_success(bsky, fake_client):
    op = _post(
        uri="at://did:plc:abc/app.bsky.feed.post/100",
        text="Tariff debate",
    )
    reply = _post(
        uri="at://did:plc:bob/app.bsky.feed.post/r1",
        text="great point",
        author=_author(handle="bob.bsky.social", did="did:plc:bob"),
        likes=10,
    )
    fake_client.get_post_thread.return_value = _thread_payload(
        op, replies=[_thread(reply)]
    )

    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.fetch_text(_candidate(), job_id="job-7")

    fake_client.get_post_thread.assert_called_once()
    args, _ = fake_client.get_post_thread.call_args
    assert args == ("at://did:plc:abc/app.bsky.feed.post/100",)
    assert isinstance(out, ExtractedText)
    assert out.text_source == "bluesky"
    assert out.language == "en"
    assert len(out.segments) == 2  # OP + 1 reply
    assert out.segments[0]["extra"]["kind"] == "post"
    assert out.segments[1]["extra"]["kind"] == "reply"
    # Empty query → fail-soft fallback classification populated (D-023).
    assert "classification" in out.extra
    assert out.extra["classification"]["stance"] == "unclear"


def test_fetch_text_calls_classifier_when_query_is_present(bsky, fake_client):
    op = _post(text="Caching strategies")
    fake_client.get_post_thread.return_value = _thread_payload(op)

    fake_classification = {
        "stance": "for",
        "sentiment": "positive",
        "framing": "technical",
        "topic_relevance": 0.85,
    }
    fake_classify_result = Mock()
    fake_classify_result.model_dump.return_value = fake_classification

    with (
        patch.object(
            bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
        ),
        patch(
            "app.sources.bluesky.connector.classify",
            return_value=fake_classify_result,
        ) as mock_classify,
    ):
        out = bsky.fetch_text(_candidate(), job_id="job-7", query="caching")

    assert isinstance(out, ExtractedText)
    mock_classify.assert_called_once()
    call_args = mock_classify.call_args
    assert call_args.args[1] == "caching"
    assert out.extra["classification"] == fake_classification


def test_fetch_text_returns_none_on_get_post_thread_exception(bsky, fake_client):
    fake_client.get_post_thread.side_effect = RuntimeError("boom")
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        assert bsky.fetch_text(_candidate(), job_id="job-1") is None


def test_fetch_text_returns_none_on_malformed_uri(bsky, fake_client):
    """Candidate with a non-AT-URI source_id short-circuits to None."""
    bad = Candidate(
        source_type="bluesky_post",
        source_id="bluesky:not-an-at-uri",
        title="t",
        source_url="",
    )
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        assert bsky.fetch_text(bad) is None
    fake_client.get_post_thread.assert_not_called()


def test_fetch_text_returns_none_on_empty_segments(bsky, fake_client):
    """A post with no body and no replies yields no segments."""
    op = _post(text="")
    fake_client.get_post_thread.return_value = _thread_payload(op)
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        assert bsky.fetch_text(_candidate()) is None


def test_fetch_text_uses_record_langs_for_extracted_text(bsky, fake_client):
    """When the AT-Proto post record carries a `langs` array, surface
    the first one on ExtractedText so multilingual indexing knows
    what it's storing."""
    op = _post(text="Hola mundo", langs=["es"])
    fake_client.get_post_thread.return_value = _thread_payload(op)
    with patch.object(
        bluesky_connector_mod.bluesky_client, "get_client", return_value=fake_client
    ):
        out = bsky.fetch_text(_candidate())
    assert out is not None
    assert out.language == "es"


# ---------------------------------------------------------------------------
# Flatten module
# ---------------------------------------------------------------------------
def test_flatten_handles_malformed_payload():
    assert bluesky_flatten.flatten_thread([]) == ([], {})  # type: ignore[arg-type]
    assert bluesky_flatten.flatten_thread({}) == ([], {})
    assert bluesky_flatten.flatten_thread({"thread": "not a dict"}) == ([], {})


def test_flatten_op_only_when_no_replies():
    op = _post(text="Hello world")
    payload = _thread_payload(op)
    segments, op_data = bluesky_flatten.flatten_thread(payload)
    assert op_data["uri"] == op["uri"]
    assert len(segments) == 1
    assert "Hello world" in segments[0]["text"]
    assert segments[0]["extra"]["kind"] == "post"
    assert segments[0]["start"] == 0.0
    assert segments[0]["duration"] > 0


def test_flatten_sorts_replies_by_likes_descending():
    op = _post(text="Question?")
    payload = _thread_payload(op, replies=[
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/r1", text="low", likes=1)),
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/r2", text="high", likes=99)),
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/r3", text="mid", likes=10)),
    ])
    segments, _ = bluesky_flatten.flatten_thread(payload)
    bodies = [s["text"] for s in segments]
    assert "Question" in bodies[0]
    assert "(likes 99)" in bodies[1]
    assert "(likes 10)" in bodies[2]
    assert "(likes 1)" in bodies[3]


def test_flatten_truncates_to_top_n():
    op = _post(text="q")
    replies = [
        _thread(_post(
            uri=f"at://did:plc:abc/app.bsky.feed.post/r{i}",
            text=f"c{i}",
            likes=i,
        ))
        for i in range(20)
    ]
    payload = _thread_payload(op, replies=replies)
    segments, _ = bluesky_flatten.flatten_thread(payload, top_n=5)
    assert len(segments) == 6  # 1 OP + 5 replies


def test_flatten_renders_depth_markers_for_nested_replies():
    """Nested replies-of-replies retain `↳ ↳ ` markers."""
    op = _post(text="q")
    parent_post = _post(
        uri="at://did:plc:abc/app.bsky.feed.post/parent",
        text="parent",
        likes=5,
    )
    child_post = _post(
        uri="at://did:plc:abc/app.bsky.feed.post/child",
        text="child",
        likes=2,
    )
    payload = _thread_payload(
        op,
        replies=[
            _thread(parent_post, replies=[_thread(child_post)]),
        ],
    )
    segments, _ = bluesky_flatten.flatten_thread(payload)
    reply_segments = [s for s in segments if s["extra"]["kind"] == "reply"]
    parent_seg = next(
        s for s in reply_segments
        if s["extra"]["comment_id"].endswith("/parent")
    )
    child_seg = next(
        s for s in reply_segments
        if s["extra"]["comment_id"].endswith("/child")
    )
    assert parent_seg["extra"]["depth"] == 1
    assert child_seg["extra"]["depth"] == 2
    assert "↳ " in parent_seg["text"]
    assert "↳ ↳ " in child_seg["text"]


def test_flatten_skips_empty_reply_bodies():
    op = _post(text="q")
    payload = _thread_payload(op, replies=[
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/empty", text="", likes=10)),
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/real", text="real", likes=1)),
    ])
    segments, _ = bluesky_flatten.flatten_thread(payload)
    assert len(segments) == 2  # OP + the real reply


def test_flatten_emits_comment_url_for_replies():
    """Each reply segment carries its own ``comment_url`` so the
    reference enricher can deep-link to that exact reply when chunks
    of its body get cited."""
    op = _post(text="q")
    reply = _post(
        uri="at://did:plc:abc/app.bsky.feed.post/r1",
        text="reply body",
        author=_author(handle="bob.bsky.social"),
        likes=5,
    )
    payload = _thread_payload(op, replies=[_thread(reply)])
    segments, _ = bluesky_flatten.flatten_thread(payload)
    reply_seg = next(s for s in segments if s["extra"]["kind"] == "reply")
    assert reply_seg["extra"]["comment_id"] == "at://did:plc:abc/app.bsky.feed.post/r1"
    assert reply_seg["extra"]["comment_url"] == (
        "https://bsky.app/profile/bob.bsky.social/post/r1"
    )


def test_flatten_segments_have_monotonic_timestamps():
    op = _post(text="body here")
    payload = _thread_payload(op, replies=[
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/r1", text="first reply", likes=10)),
        _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/r2", text="second longer reply text", likes=5)),
    ])
    segments, _ = bluesky_flatten.flatten_thread(payload)
    starts = [s["start"] for s in segments]
    durations = [s["duration"] for s in segments]
    assert starts == sorted(starts)
    assert all(d > 0 for d in durations)


def test_flatten_skips_blocked_or_not_found_replies():
    """`#notFoundPost` / `#blockedPost` thread nodes carry no `post`
    key. Walking continues past them rather than raising."""
    op = _post(text="q")
    blocked = {"$type": "app.bsky.feed.defs#blockedPost", "uri": "at://x"}
    real = _thread(_post(uri="at://did:plc:abc/app.bsky.feed.post/real", text="real", likes=1))
    payload = _thread_payload(op, replies=[blocked, real])
    segments, _ = bluesky_flatten.flatten_thread(payload)
    assert len(segments) == 2  # OP + real reply (blocked skipped)


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------
def test_connector_source_type_is_bluesky_post():
    """Locks the discriminator — changing this would silently break
    every row in `documents` with `source_type='bluesky_post'`."""
    assert BlueskyConnector.source_type == "bluesky_post"


def test_connector_registers_under_bluesky_post():
    """Importing the connector module at top of this file should have
    eagerly registered the connector. Verify the registry agrees."""
    from app.sources.bluesky import connector as _  # noqa: F401  re-import is idempotent

    got = registry.connector_for("bluesky_post")
    assert isinstance(got, BlueskyConnector)


# ---------------------------------------------------------------------------
# Client: rate-limited GET against the public XRPC endpoint
# ---------------------------------------------------------------------------
def test_client_get_json_hits_xrpc_base():
    """Smoke check: `get_json` calls `httpx.get` against the configured
    XRPC base + `/xrpc<path>` with the expected User-Agent header."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {}
    api_resp.raise_for_status = Mock()

    with patch.object(bluesky_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = BlueskyClient()
        c.get_json("/app.bsky.feed.searchPosts", params={"q": "x"})

    assert mock_get.call_count == 1
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/xrpc/app.bsky.feed.searchPosts")
    headers = mock_get.call_args.kwargs["headers"]
    assert "User-Agent" in headers


def test_client_get_json_raises_on_http_error():
    import httpx as _httpx

    bad_resp = Mock(status_code=500)
    bad_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "500", request=Mock(), response=bad_resp
    )

    with patch.object(bluesky_client_mod.httpx, "get", return_value=bad_resp):
        c = BlueskyClient()
        with pytest.raises(_httpx.HTTPStatusError):
            c.get_json("/app.bsky.feed.searchPosts")


def test_client_search_posts_clamps_limit_to_100():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"posts": []}
    api_resp.raise_for_status = Mock()

    with patch.object(bluesky_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = BlueskyClient()
        c.search_posts("rust", limit=500)

    params = mock_get.call_args.kwargs["params"]
    assert params == {"q": "rust", "limit": 100}


def test_client_get_post_thread_default_depth():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {}
    api_resp.raise_for_status = Mock()

    with patch.object(bluesky_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = BlueskyClient()
        c.get_post_thread("at://did:plc:abc/app.bsky.feed.post/1")

    params = mock_get.call_args.kwargs["params"]
    assert params == {
        "uri": "at://did:plc:abc/app.bsky.feed.post/1",
        "depth": 6,
    }


def test_client_get_profile_passes_actor_param():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"did": "did:plc:abc"}
    api_resp.raise_for_status = Mock()

    with patch.object(bluesky_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = BlueskyClient()
        c.get_profile("alice.bsky.social")

    params = mock_get.call_args.kwargs["params"]
    assert params == {"actor": "alice.bsky.social"}


def test_client_get_author_feed_clamps_limit():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"feed": []}
    api_resp.raise_for_status = Mock()

    with patch.object(bluesky_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = BlueskyClient()
        c.get_author_feed("alice.bsky.social", limit=500)

    params = mock_get.call_args.kwargs["params"]
    assert params == {"actor": "alice.bsky.social", "limit": 100}

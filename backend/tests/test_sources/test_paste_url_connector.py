"""Unit tests for paste-URL connectors + URL→source_type resolver.

Covers:
- `resolve_source_type(url)` — host-based routing for the five paste
  source types.
- `hash_url(url)` — canonical-URL hashing (drops tracking params).
- `_PasteURLBaseConnector.fetch_text` — delegates to extract_text and
  builds canonical-shape segments.
- All five connector subclasses register correctly.
- search() / list_creator_items() raise NotImplementedError.

`extract_text` is mocked throughout — no network calls.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.article_extraction import ExtractionResult
from app.services.paste_url_resolver import is_recognised_paste_source, resolve_source_type
from app.sources import registry
from app.sources.paste_url.connector import (
    ArticleConnector,
    FBPostConnector,
    IGPostConnector,
    LIPostConnector,
    TweetConnector,
    hash_url,
)
from app.sources.types import Candidate, ExtractedText


# ---------------------------------------------------------------------------
# resolve_source_type — host-based routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # Facebook
        ("https://www.facebook.com/zuck/posts/123", "fb_post"),
        ("https://m.facebook.com/zuck/posts/123", "fb_post"),
        ("https://facebook.com/zuck/posts/123", "fb_post"),
        ("https://www.fb.com/zuck/posts/123", "fb_post"),
        # Instagram
        ("https://www.instagram.com/p/ABC123/", "ig_post"),
        ("https://instagram.com/reel/XYZ789/", "ig_post"),
        ("https://m.instagram.com/p/abc/", "ig_post"),
        # LinkedIn
        ("https://www.linkedin.com/posts/jane-doe_activity-123", "li_post"),
        ("https://linkedin.com/feed/update/urn:li:activity:7", "li_post"),
        # Twitter / X
        ("https://twitter.com/elonmusk/status/123", "tweet"),
        ("https://www.twitter.com/user/status/456", "tweet"),
        ("https://x.com/user/status/789", "tweet"),
        ("https://mobile.x.com/user/status/789", "tweet"),
        # Generic — falls through to article
        ("https://nytimes.com/2024/some-article", "article"),
        ("https://substack.example.com/p/post", "article"),
        ("https://medium.com/@author/post-abc", "article"),
        ("https://example.com/blog/post", "article"),
    ],
)
def test_resolve_source_type_routes_correctly(url: str, expected: str):
    assert resolve_source_type(url) == expected


def test_resolve_source_type_handles_empty_or_invalid():
    assert resolve_source_type("") == "article"
    assert resolve_source_type("   ") == "article"
    assert resolve_source_type(None) == "article"  # type: ignore[arg-type]
    assert resolve_source_type(123) == "article"  # type: ignore[arg-type]
    # Schemeless URL — urlparse still parses it, no host extracted
    assert resolve_source_type("not a url") == "article"


def test_is_recognised_paste_source():
    for st in ("article", "fb_post", "ig_post", "li_post", "tweet"):
        assert is_recognised_paste_source(st)
    assert not is_recognised_paste_source("video")
    assert not is_recognised_paste_source("podcast_episode")


# ---------------------------------------------------------------------------
# hash_url — canonical hashing
# ---------------------------------------------------------------------------


def test_hash_url_is_deterministic():
    a = hash_url("https://example.com/page")
    b = hash_url("https://example.com/page")
    assert a == b
    assert len(a) == 64  # SHA-256 hex


def test_hash_url_drops_fragment():
    """`#section-A` and no fragment should hash the same — fragments
    are client-side scroll markers, not content identity."""
    assert hash_url("https://example.com/page") == hash_url(
        "https://example.com/page#section-2"
    )


def test_hash_url_drops_utm_tracking_params():
    """`?utm_source=twitter&utm_campaign=foo` should hash the same as
    no query — UTM params are tracking, not content identity."""
    assert hash_url("https://example.com/page") == hash_url(
        "https://example.com/page?utm_source=twitter&utm_campaign=foo"
    )


def test_hash_url_drops_fbclid_and_friends():
    """Common click-tracking IDs (`fbclid`, `igshid`, `gclid`) get
    dropped before hashing."""
    base = hash_url("https://example.com/page")
    assert hash_url("https://example.com/page?fbclid=abc") == base
    assert hash_url("https://example.com/page?igshid=xyz") == base
    assert hash_url("https://example.com/page?gclid=123") == base


def test_hash_url_preserves_meaningful_query_params():
    """`?id=42` IS content-identifying (different posts) — hashes differ."""
    assert hash_url("https://example.com/page?id=42") != hash_url(
        "https://example.com/page?id=43"
    )


def test_hash_url_distinguishes_different_urls():
    assert hash_url("https://example.com/a") != hash_url("https://example.com/b")
    assert hash_url("https://a.example.com/x") != hash_url("https://b.example.com/x")


# ---------------------------------------------------------------------------
# Connector subclass registration + identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls,expected_source_type",
    [
        (ArticleConnector, "article"),
        (FBPostConnector, "fb_post"),
        (IGPostConnector, "ig_post"),
        (LIPostConnector, "li_post"),
        (TweetConnector, "tweet"),
    ],
)
def test_connector_source_type_set(cls, expected_source_type):
    assert cls.source_type == expected_source_type


@pytest.mark.parametrize(
    "source_type,cls",
    [
        ("article", ArticleConnector),
        ("fb_post", FBPostConnector),
        ("ig_post", IGPostConnector),
        ("li_post", LIPostConnector),
        ("tweet", TweetConnector),
    ],
)
def test_connectors_register_under_their_source_types(source_type: str, cls):
    """All five subclasses register at import time; registry dispatch
    resolves to the right one."""
    from app.sources.paste_url import connector as _  # noqa: F401

    got = registry.connector_for(source_type)
    assert isinstance(got, cls)


# ---------------------------------------------------------------------------
# Discovery methods raise NotImplementedError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [ArticleConnector, FBPostConnector, IGPostConnector, LIPostConnector, TweetConnector],
)
def test_search_raises(cls):
    conn = cls()
    with pytest.raises(NotImplementedError):
        conn.search("anything")


@pytest.mark.parametrize(
    "cls",
    [ArticleConnector, FBPostConnector, IGPostConnector, LIPostConnector, TweetConnector],
)
def test_list_creator_items_raises(cls):
    conn = cls()
    with pytest.raises(NotImplementedError):
        list(conn.list_creator_items("creator-id"))


def test_fetch_metadata_returns_empty_for_all_paste_connectors():
    for cls in (
        ArticleConnector,
        FBPostConnector,
        IGPostConnector,
        LIPostConnector,
        TweetConnector,
    ):
        assert cls().fetch_metadata(["any:id"]) == {}


# ---------------------------------------------------------------------------
# fetch_text — delegates to extract_text, builds canonical segments
# ---------------------------------------------------------------------------


def _candidate(source_type: str, url: str) -> Candidate:
    from app.sources.paste_url.connector import hash_url

    return Candidate(
        source_type=source_type,
        source_id=f"{source_type}:{hash_url(url)}",
        title=url,
        source_url=url,
    )


def test_fetch_text_delegates_to_extract_text_and_returns_extracted_text():
    fake_extract = ExtractionResult(
        text="Article body content. Substantial enough to be useful.",
        title="Test Article",
        author="Jane Doe",
        published_at=None,
        language="en",
        word_count=8,
        source="trafilatura",
    )

    with patch(
        "app.sources.paste_url.connector.extract_text",
        return_value=fake_extract,
    ) as mock_ext:
        out = ArticleConnector().fetch_text(
            _candidate("article", "https://example.com/post")
        )

    mock_ext.assert_called_once_with("https://example.com/post")
    assert isinstance(out, ExtractedText)
    assert out.language == "en"
    assert out.word_count == 8
    assert out.text_source == "paste_extract_trafilatura"
    # Single-segment shape — articles don't have natural sub-segments
    assert len(out.segments) == 1
    assert "Article body content" in out.segments[0]["text"]
    # Per-segment extra carries author, comment_id (== source_id),
    # comment_url (== source URL).
    extra = out.segments[0]["extra"]
    assert extra["author"] == "Jane Doe"
    assert extra["kind"] == "article_body"  # ArticleConnector specific
    assert extra["comment_id"].startswith("article:")
    assert extra["comment_url"] == "https://example.com/post"
    # Outer extra surfaces title / author / source for the caller.
    assert out.extra["extracted_title"] == "Test Article"
    assert out.extra["extracted_author"] == "Jane Doe"
    assert out.extra["url"] == "https://example.com/post"


def test_fetch_text_returns_none_when_extract_text_fails():
    with patch(
        "app.sources.paste_url.connector.extract_text", return_value=None
    ):
        out = ArticleConnector().fetch_text(
            _candidate("article", "https://example.com/post")
        )
    assert out is None


def test_fetch_text_returns_none_when_candidate_has_no_url():
    cand = Candidate(
        source_type="article",
        source_id="article:abc",
        title="t",
        source_url="",  # empty
    )
    out = ArticleConnector().fetch_text(cand)
    assert out is None


def test_fetch_text_for_social_post_uses_kind_post():
    """All non-article social paste types tag segments with kind='post'."""
    fake_extract = ExtractionResult(
        text="x" * 100,
        title="t",
        word_count=1,
        source="playwright",
    )
    with patch(
        "app.sources.paste_url.connector.extract_text",
        return_value=fake_extract,
    ):
        for cls, source_type in [
            (FBPostConnector, "fb_post"),
            (IGPostConnector, "ig_post"),
            (LIPostConnector, "li_post"),
            (TweetConnector, "tweet"),
        ]:
            out = cls().fetch_text(_candidate(source_type, "https://example.com/x"))
            assert out is not None
            assert out.segments[0]["extra"]["kind"] == "post"
            assert out.text_source == "paste_extract_playwright"


def test_fetch_text_synthesises_pseudo_timestamp_at_3wps():
    """Per D-013, paste segments use 3-words-per-second pseudo-timestamps
    so the chunker — which expects monotonic non-negative timestamps —
    works without a paste-specific branch."""
    fake_extract = ExtractionResult(
        text="x " * 30,  # 30 words
        word_count=30,
        source="trafilatura",
    )
    with patch(
        "app.sources.paste_url.connector.extract_text",
        return_value=fake_extract,
    ):
        out = ArticleConnector().fetch_text(
            _candidate("article", "https://example.com/post")
        )
    assert out is not None
    seg = out.segments[0]
    assert seg["start"] == 0.0
    # 30 words / 3 wps = 10 seconds duration
    assert seg["duration"] == pytest.approx(10.0)

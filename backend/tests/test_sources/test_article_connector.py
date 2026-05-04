"""Tests for the search-having ArticleConnector + Brave + RSS client.

The base paste-mode `ArticleConnector` is covered in
`test_paste_url_connector.py`; this file specifically tests the
search + RSS additions.

Strategy mirrors the other connectors — mock the underlying client
+ httpx so we lock down shape transformation (Brave JSON / RSS feed
→ Candidates) and wiring (which client method each connector method
calls). No network calls.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import feedparser
import httpx
import pytest

from app.sources import registry
from app.sources.article import client as article_client_mod
from app.sources.article import connector as article_connector_mod
from app.sources.article.client import ArticleClient
from app.sources.article.connector import ArticleConnector
from app.sources.types import Candidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def article():
    return ArticleConnector()


@pytest.fixture
def fake_client():
    return Mock(spec=ArticleClient)


def _brave_result(
    url: str = "https://example.com/article",
    title: str = "Sample Article",
    description: str = "A sample article body excerpt.",
    age: str = "3 hours ago",
) -> dict:
    return {
        "url": url,
        "title": title,
        "description": description,
        "age": age,
    }


def _brave_payload(*results: dict) -> dict:
    return {
        "query": {"original": "sample query"},
        "web": {"results": list(results)},
    }


RSS_ARTICLE_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Blog</title>
    <link>https://example.com/</link>
    <item>
      <title>Article One</title>
      <link>https://example.com/article-one</link>
      <pubDate>Mon, 15 Jan 2024 12:00:00 GMT</pubDate>
      <description>First article summary.</description>
      <author>jane@example.com (Jane Doe)</author>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/article-two</link>
      <pubDate>Tue, 16 Jan 2024 12:00:00 GMT</pubDate>
      <description>Second article summary.</description>
    </item>
  </channel>
</rss>
"""


def _parse(rss_xml: str) -> dict:
    return feedparser.parse(rss_xml)


# ---------------------------------------------------------------------------
# Identity / re-registration
# ---------------------------------------------------------------------------


def test_article_connector_is_registered_under_article():
    """Importing this module re-registers the search-having
    ArticleConnector for source_type='article' — overwriting the
    paste-only base from app.sources.paste_url."""
    from app.sources.article import connector as _  # noqa: F401

    got = registry.connector_for("article")
    # Class-name check rather than `isinstance(ArticleConnector)` —
    # the paste-mode base class IS the parent here, so isinstance
    # returns True for both. We need to verify the *actual* class.
    assert got.__class__.__name__ == "ArticleConnector"
    assert got.__class__.__module__ == "app.sources.article.connector"


# ---------------------------------------------------------------------------
# search() — Brave Search
# ---------------------------------------------------------------------------


def test_search_returns_empty_when_query_blank(article, fake_client):
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        assert article.search("   ") == []
    fake_client.brave_search.assert_not_called()


def test_search_returns_empty_when_brave_key_unset(article, fake_client, monkeypatch):
    monkeypatch.setattr(
        article_connector_mod.settings, "BRAVE_SEARCH_API_KEY", ""
    )
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = article.search("anything")
    assert out == []
    fake_client.brave_search.assert_not_called()


def test_search_returns_candidates_from_brave(article, fake_client, monkeypatch):
    monkeypatch.setattr(
        article_connector_mod.settings, "BRAVE_SEARCH_API_KEY", "fake-key"
    )
    fake_client.brave_search.return_value = _brave_payload(
        _brave_result(url="https://example.com/a", title="Title A"),
        _brave_result(url="https://example.com/b", title="Title B"),
    )
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = article.search("software", limit=5)
    fake_client.brave_search.assert_called_once_with("software", limit=5)
    assert len(out) == 2
    assert all(isinstance(c, Candidate) for c in out)
    assert all(c.source_type == "article" for c in out)
    assert {c.title for c in out} == {"Title A", "Title B"}
    assert {c.source_url for c in out} == {
        "https://example.com/a",
        "https://example.com/b",
    }


def test_search_skips_results_without_url(article, fake_client, monkeypatch):
    """Some Brave results omit `url` (rare; usually due to broken
    backends). Skip them rather than crashing."""
    monkeypatch.setattr(
        article_connector_mod.settings, "BRAVE_SEARCH_API_KEY", "fake-key"
    )
    fake_client.brave_search.return_value = _brave_payload(
        {"title": "No URL Here"},  # missing url
        _brave_result(url="https://example.com/real", title="Real"),
    )
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = article.search("x")
    assert len(out) == 1
    assert out[0].source_url == "https://example.com/real"


def test_search_returns_empty_when_brave_raises(article, fake_client, monkeypatch):
    """Network errors / rate limits / 5xx must degrade to empty list."""
    monkeypatch.setattr(
        article_connector_mod.settings, "BRAVE_SEARCH_API_KEY", "fake-key"
    )
    fake_client.brave_search.side_effect = httpx.ConnectError("DNS")
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = article.search("anything")
    assert out == []


def test_search_caps_at_limit(article, fake_client, monkeypatch):
    monkeypatch.setattr(
        article_connector_mod.settings, "BRAVE_SEARCH_API_KEY", "fake-key"
    )
    # Brave returns more than `limit`; we cap.
    fake_client.brave_search.return_value = _brave_payload(
        *(_brave_result(url=f"https://example.com/{i}", title=f"T{i}") for i in range(10))
    )
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = article.search("x", limit=3)
    assert len(out) == 3


def test_search_candidate_carries_brave_age_in_extra(article, fake_client, monkeypatch):
    monkeypatch.setattr(
        article_connector_mod.settings, "BRAVE_SEARCH_API_KEY", "fake-key"
    )
    fake_client.brave_search.return_value = _brave_payload(
        _brave_result(url="https://example.com/a", age="5 days ago")
    )
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = article.search("x")
    assert out[0].extra["brave_age"] == "5 days ago"


# ---------------------------------------------------------------------------
# list_creator_items() — RSS feed
# ---------------------------------------------------------------------------


def test_list_creator_items_yields_iterator(article, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_ARTICLE_FEED)
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        gen = article.list_creator_items("https://example.com/feed.rss")
        assert hasattr(gen, "__next__")
        first = next(gen)
        assert first.title == "Article One"
        assert first.source_url == "https://example.com/article-one"


def test_list_creator_items_empty_creator_id(article, fake_client):
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(article.list_creator_items(""))
    assert out == []
    fake_client.fetch_feed.assert_not_called()


def test_list_creator_items_respects_limit(article, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_ARTICLE_FEED)
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(
            article.list_creator_items("https://example.com/feed.rss", limit=1)
        )
    assert len(out) == 1


def test_list_creator_items_returns_nothing_on_feed_failure(article, fake_client):
    fake_client.fetch_feed.side_effect = httpx.ConnectError("DNS")
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(article.list_creator_items("https://broken.example.com/f"))
    assert out == []


def test_list_creator_items_carries_published_at_when_pubdate_present(article, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_ARTICLE_FEED)
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(article.list_creator_items("https://example.com/feed.rss"))
    assert out[0].published_at is not None
    assert out[0].published_at.year == 2024


def test_list_creator_items_pulls_author_from_feed(article, fake_client):
    fake_client.fetch_feed.return_value = _parse(RSS_ARTICLE_FEED)
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(article.list_creator_items("https://example.com/feed.rss"))
    assert any(c.creator_name for c in out)


def test_list_creator_items_skips_entries_without_link(article, fake_client):
    """Entries missing `<link>` are dropped — no URL means no Document."""
    bad_feed = {
        "entries": [
            {"title": "No Link", "summary": "No link present"},
            {"title": "Has Link", "link": "https://example.com/ok", "summary": "ok"},
        ]
    }
    fake_client.fetch_feed.return_value = bad_feed
    with patch.object(
        article_connector_mod.article_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(article.list_creator_items("https://example.com/feed.rss"))
    assert len(out) == 1
    assert out[0].source_url == "https://example.com/ok"


# ---------------------------------------------------------------------------
# Client: Brave HTTP smoke test
# ---------------------------------------------------------------------------


def test_client_brave_search_raises_when_key_unset(monkeypatch):
    monkeypatch.setattr(
        article_client_mod.settings, "BRAVE_SEARCH_API_KEY", ""
    )
    c = ArticleClient()
    with pytest.raises(RuntimeError):
        c.brave_search("anything")


def test_client_brave_search_sends_subscription_token(monkeypatch):
    monkeypatch.setattr(
        article_client_mod.settings, "BRAVE_SEARCH_API_KEY", "secret-key-123"
    )
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"web": {"results": []}}
    api_resp.raise_for_status = Mock()

    with patch.object(
        article_client_mod.httpx, "get", return_value=api_resp
    ) as mock_get:
        c = ArticleClient()
        c.brave_search("rust async", limit=15)

    headers = mock_get.call_args.kwargs["headers"]
    assert headers["X-Subscription-Token"] == "secret-key-123"
    assert headers["Accept"] == "application/json"
    params = mock_get.call_args.kwargs["params"]
    assert params == {"q": "rust async", "count": 15}


def test_client_brave_search_clamps_count_to_20(monkeypatch):
    monkeypatch.setattr(
        article_client_mod.settings, "BRAVE_SEARCH_API_KEY", "k"
    )
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"web": {"results": []}}
    api_resp.raise_for_status = Mock()
    with patch.object(
        article_client_mod.httpx, "get", return_value=api_resp
    ) as mock_get:
        c = ArticleClient()
        c.brave_search("x", limit=999)
    assert mock_get.call_args.kwargs["params"]["count"] == 20


def test_client_fetch_feed_returns_parsed():
    api_resp = Mock(status_code=200)
    api_resp.content = RSS_ARTICLE_FEED.encode("utf-8")
    api_resp.raise_for_status = Mock()

    with patch.object(article_client_mod.httpx, "get", return_value=api_resp):
        c = ArticleClient()
        feed = c.fetch_feed("https://example.com/f.rss")

    assert feed["feed"]["title"] == "Example Blog"
    assert len(feed["entries"]) == 2

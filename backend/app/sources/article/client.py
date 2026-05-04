"""Article-connector HTTP clients: Brave Search API + RSS feeds.

Two surfaces:

1. **Brave Search** at ``https://api.search.brave.com/res/v1/web/search``.
   Free-tier API key + ``X-Subscription-Token`` header. Returns
   ranked web results with title, URL, description, age. We use it
   for topic-search discovery — a topic query yields up to 20
   article URLs which then flow through the same article-extraction
   primitives as paste-mode.

2. **RSS feeds** via feedparser (already a dependency from M-1.7
   podcast). The user supplies a feed URL via
   `list_creator_items(feed_url)`; we parse the feed and yield
   article entries.

Tests should mock `get_client()` rather than monkey-patching httpx.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import feedparser
import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class ArticleClient:
    """Thread-safe HTTP client for Brave Search + RSS feed fetch."""

    def __init__(self) -> None:
        rpm = max(1, settings.ARTICLE_SEARCH_RATE_LIMIT_RPM)
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # Brave Search
    # ------------------------------------------------------------------
    def brave_search(self, query: str, limit: int = 10) -> dict:
        """Search Brave Search and return parsed JSON.

        Free-tier requires `X-Subscription-Token` header with the API
        key. Brave caps `count` at 20; we clamp defensively.
        Returns the raw response shape `{web: {results: [...]}}` so
        callers can apply additional filters.
        """
        if not settings.BRAVE_SEARCH_API_KEY:
            raise RuntimeError(
                "BRAVE_SEARCH_API_KEY is unset; cannot run Brave search"
            )
        self._limiter.wait()
        params = {
            "q": query,
            "count": max(1, min(20, limit)),
        }
        headers = {
            "User-Agent": settings.ARTICLE_USER_AGENT,
            "X-Subscription-Token": settings.BRAVE_SEARCH_API_KEY,
            "Accept": "application/json",
        }
        resp = httpx.get(
            settings.BRAVE_SEARCH_BASE,
            params=params,
            headers=headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # RSS feeds
    # ------------------------------------------------------------------
    def fetch_feed(self, feed_url: str) -> Any:
        """GET an RSS / Atom feed and return the feedparser-parsed dict.

        feedparser tolerates virtually every feed variant (RSS 2.0,
        Atom, RSS 1.0 RDF, malformed-but-mostly-valid). We download
        via httpx so the User-Agent is consistent with the rest of
        the connector and transient failures surface as
        ``httpx.HTTPError`` rather than feedparser's less-actionable
        exception shapes.
        """
        self._limiter.wait()
        headers = {"User-Agent": settings.ARTICLE_USER_AGENT}
        resp = httpx.get(
            feed_url,
            headers=headers,
            timeout=self._timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return feedparser.parse(resp.content)


_INSTANCE: ArticleClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> ArticleClient:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ArticleClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    global _INSTANCE
    _INSTANCE = None

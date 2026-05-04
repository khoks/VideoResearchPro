"""HTTP client for podcast discovery + RSS-feed fetching.

Two surfaces:

1. iTunes Search API for show discovery
   (``https://itunes.apple.com/search?term=<q>&entity=podcast``).
   Free, unauthenticated, no rate-limit documented but generous in
   practice. Returns show-level metadata including the canonical
   ``feedUrl`` we use for episode iteration.
2. Direct RSS-feed fetch — pull the feed body via httpx, hand to
   feedparser. Per-feed rate limit handled by the same token-bucket
   used elsewhere.

Tests should mock `get_client` rather than monkey-patching httpx.
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

ITUNES_SEARCH_BASE = "https://itunes.apple.com/search"


class PodcastClient:
    """Thread-safe HTTP client for podcast discovery + RSS fetching."""

    def __init__(self) -> None:
        rpm = max(1, settings.PODCAST_RATE_LIMIT_RPM)
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # iTunes Search
    # ------------------------------------------------------------------
    def itunes_search(self, query: str, limit: int = 10) -> dict:
        """Search iTunes for podcast shows matching `query`.

        Returns the parsed JSON response: ``{resultCount, results: [...]}``.
        Each result is a show dict with keys including ``collectionId``,
        ``collectionName``, ``artistName``, ``feedUrl``, ``artworkUrl600``,
        ``primaryGenreName``, ``releaseDate``.
        """
        self._limiter.wait()
        params = {
            "term": query,
            "entity": "podcast",
            "limit": max(1, min(200, limit)),  # iTunes caps at 200
        }
        headers = {"User-Agent": settings.PODCAST_USER_AGENT}
        resp = httpx.get(
            ITUNES_SEARCH_BASE,
            params=params,
            headers=headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def itunes_lookup(self, collection_id: str | int) -> dict:
        """Resolve an iTunes ``collectionId`` to a show record.

        Used by ``resolve_creator_id`` when the user pastes an iTunes
        show URL like
        ``https://podcasts.apple.com/us/podcast/.../id1234567890`` —
        we extract the trailing ID and resolve it to the show's
        ``feedUrl`` for ingest.
        """
        self._limiter.wait()
        params = {"id": str(collection_id), "entity": "podcast"}
        headers = {"User-Agent": settings.PODCAST_USER_AGENT}
        resp = httpx.get(
            "https://itunes.apple.com/lookup",
            params=params,
            headers=headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # RSS feed
    # ------------------------------------------------------------------
    def fetch_feed(self, feed_url: str) -> dict:
        """GET a podcast RSS feed and return the feedparser-parsed dict.

        feedparser tolerates virtually every RSS variant in the wild
        (including the iTunes namespace extensions, podcast: 2.0
        extensions, and most malformed-but-mostly-valid feeds). We
        download the body via httpx so the User-Agent is consistent
        with the rest of the connector and so transient network
        failures surface as ``httpx.HTTPError`` rather than feedparser's
        less-actionable exception shapes.
        """
        self._limiter.wait()
        headers = {"User-Agent": settings.PODCAST_USER_AGENT}
        resp = httpx.get(feed_url, headers=headers, timeout=self._timeout, follow_redirects=True)
        resp.raise_for_status()
        # feedparser returns a special FeedParserDict; we coerce to a
        # plain dict shape for typing simplicity at the call site, but
        # FeedParserDict supports both attribute and dict access so
        # downstream code can use either form.
        return feedparser.parse(resp.content)

    # ------------------------------------------------------------------
    # Audio enclosure
    # ------------------------------------------------------------------
    def fetch_audio(self, audio_url: str) -> bytes:
        """Download an audio file (typically an MP3) and return its bytes.

        Used by the Whisper-fallback path. Generous timeout
        (``PODCAST_AUDIO_FETCH_TIMEOUT_SEC``) because podcast episodes
        are often 50-150MB. Caller is responsible for writing the
        bytes to a temp file before handing to OpenAI Whisper.
        """
        # Per-fetch timeout — read-side longer than the iTunes/RSS calls
        # because audio is large.
        timeout = httpx.Timeout(
            settings.PODCAST_AUDIO_FETCH_TIMEOUT_SEC, connect=5.0
        )
        self._limiter.wait()
        headers = {"User-Agent": settings.PODCAST_USER_AGENT}
        resp = httpx.get(audio_url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


# Module-level singleton — lazy init.
_INSTANCE: PodcastClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> PodcastClient:
    """Return the process-global ``PodcastClient`` (lazy init)."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = PodcastClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    """Drop the cached singleton so the next ``get_client()`` rebuilds."""
    global _INSTANCE
    _INSTANCE = None


def _itunes_id_from_url(url: str) -> str | None:
    """Extract the trailing iTunes show ID from a `podcasts.apple.com`
    URL of the form ``.../podcast/<slug>/id1234567890`` (with or
    without trailing slash / locale prefix).

    Returns the bare numeric ID, or None when the URL doesn't match.
    """
    import re

    m = re.search(r"/id(\d+)(?:/|$|\?)", url)
    if not m:
        return None
    return m.group(1)

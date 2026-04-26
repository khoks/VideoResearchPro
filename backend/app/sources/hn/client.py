"""Hacker News API client — unauthenticated Algolia HN endpoints.

What this module provides:

- A singleton `HNClient` accessed via `get_client()`.
- Token-bucket rate limiting against `HN_RATE_LIMIT_RPM` (default 60
  req/min → 1.0 sec spacing). Algolia's HN endpoints are generous and
  unmetered in practice, but we throttle politely so we don't trip
  any soft caps.
- Convenience wrappers for the three endpoints the connector uses:
  `/search` (story search + author-scoped listing), `/items/<id>`
  (full story + comment tree), `/users/<name>` (user metadata).

Algolia returns JSON directly — no OAuth, no Bearer token, no
``access_token`` plumbing. We still send `HN_USER_AGENT` so the
operator can identify us if Algolia ever decides to throttle.

Tests should mock `get_client` to return a `unittest.mock.Mock` rather
than monkey-patching httpx — see `tests/test_sources/test_hn_connector.py`.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hn.algolia.com/api/v1"


class HNClient:
    """Thread-safe HTTP client for the public HN Algolia API."""

    def __init__(self) -> None:
        rpm = max(1, settings.HN_RATE_LIMIT_RPM)
        # secs_between_requests = 60 / RPM. Default 60 RPM → 1.0s spacing.
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``HN_API_BASE + path`` and return the parsed JSON.

        Rate-limited per `HN_RATE_LIMIT_RPM`. Any HTTP failure raises
        ``httpx.HTTPError``. There is no auth retry path because the
        endpoint is unauthenticated.
        """
        url = f"{HN_API_BASE}{path}"
        self._limiter.wait()
        headers = {"User-Agent": settings.HN_USER_AGENT}
        resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 25) -> dict:
        """Story search. Returns the raw Algolia response JSON.

        The Algolia endpoint sorts by relevance (Algolia's tuned
        ranking, which weights points/comments/recency). We restrict
        to story-typed hits via ``tags=story`` so comments don't
        leak into discovery.
        """
        return self.get_json(
            "/search",
            params={"query": query, "tags": "story", "hitsPerPage": limit},
        )

    def search_by_author(self, username: str, limit: int = 25) -> dict:
        """List stories submitted by a given author.

        Implemented as a tagged search rather than a dedicated
        endpoint — Algolia exposes ``tags=story,author_<name>`` for
        this exact purpose. ``search_by_date`` orders by recency,
        which is what a "latest submissions" creator-feed wants.
        """
        return self.get_json(
            "/search_by_date",
            params={
                "tags": f"story,author_{username}",
                "hitsPerPage": limit,
            },
        )

    def get_item(self, item_id: str | int) -> dict:
        """Fetch a single item (story or comment) with its full
        recursive ``children`` tree."""
        return self.get_json(f"/items/{item_id}")

    def get_user(self, username: str) -> dict:
        """Fetch user metadata (karma, about, created_at)."""
        return self.get_json(f"/users/{username}")


# Module-level singleton — built lazily so importing the module is cheap
# and tests can swap the instance via `_reset_for_tests()`.
_INSTANCE: HNClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> HNClient:
    """Return the process-global ``HNClient`` (lazy init)."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = HNClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    """Drop the cached singleton so the next ``get_client()`` rebuilds."""
    global _INSTANCE
    _INSTANCE = None

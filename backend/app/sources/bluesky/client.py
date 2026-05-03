"""Bluesky AT-Protocol XRPC client — unauthenticated public endpoints.

What this module provides:

- A singleton `BlueskyClient` accessed via `get_client()`.
- Token-bucket rate limiting against `BLUESKY_RATE_LIMIT_RPM`
  (default 60 req/min → 1.0 sec spacing). Bluesky's public XRPC
  caps are generous; we throttle politely so we don't trip soft caps.
- Convenience wrappers for the four endpoints the connector uses:
  `app.bsky.feed.searchPosts` (text search),
  `app.bsky.feed.getPostThread` (full post + replies tree),
  `app.bsky.actor.getProfile` (handle → DID + profile),
  `app.bsky.feed.getAuthorFeed` (creator's recent posts).

AT-Protocol XRPC returns JSON directly — no Bearer token, no app
password plumbing for these public read endpoints. We still send
`BLUESKY_USER_AGENT` so the operator can identify us if Bluesky
ever decides to throttle.

Tests should mock `get_client` to return a `unittest.mock.Mock`
rather than monkey-patching httpx — see
`tests/test_sources/test_bluesky_connector.py`.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _xrpc_base() -> str:
    """Strip any trailing slash from the configured XRPC base."""
    return (settings.BLUESKY_XRPC_BASE or "").rstrip("/")


class BlueskyClient:
    """Thread-safe HTTP client for Bluesky's public XRPC API."""

    def __init__(self) -> None:
        rpm = max(1, settings.BLUESKY_RATE_LIMIT_RPM)
        # secs_between_requests = 60 / RPM. Default 60 RPM → 1.0s spacing.
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``<xrpc_base>/xrpc<path>`` and return the parsed JSON.

        Rate-limited per `BLUESKY_RATE_LIMIT_RPM`. Any HTTP failure
        raises ``httpx.HTTPError``. There is no auth retry path
        because the public read endpoints are unauthenticated.
        """
        url = f"{_xrpc_base()}/xrpc{path}"
        self._limiter.wait()
        headers = {"User-Agent": settings.BLUESKY_USER_AGENT}
        resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------
    def search_posts(self, query: str, limit: int = 25) -> dict:
        """Text search across Bluesky posts.

        Returns the raw XRPC response JSON: ``{posts: [...], cursor: "..."}``.
        Bluesky caps `limit` at 100; we clamp at 25 by default to stay
        in line with the per-source `limit_per_type` the orchestrator
        passes (typically 10-25).
        """
        page_limit = max(1, min(100, limit))
        return self.get_json(
            "/app.bsky.feed.searchPosts",
            params={"q": query, "limit": page_limit},
        )

    def get_post_thread(self, uri: str, depth: int = 6) -> dict:
        """Fetch the full post-thread tree for an AT-URI.

        ``depth`` controls how many levels of replies are returned.
        Bluesky's default is 6, matching most clients; we expose it
        so a future PR can drill deeper when needed.
        """
        return self.get_json(
            "/app.bsky.feed.getPostThread",
            params={"uri": uri, "depth": depth},
        )

    def get_profile(self, actor: str) -> dict:
        """Resolve a handle (or DID) to a profile dict.

        ``actor`` accepts the bare handle (``alice.bsky.social``) or a
        DID (``did:plc:abc...``). Returns ``{did, handle, displayName,
        description, ...}``.
        """
        return self.get_json(
            "/app.bsky.actor.getProfile",
            params={"actor": actor},
        )

    def get_author_feed(self, actor: str, limit: int = 25) -> dict:
        """List a creator's recent posts.

        Used for `list_creator_items()`. Bluesky caps `limit` at 100;
        we clamp + return whatever the API gives us. Today we don't
        paginate via `cursor` — a future PR can walk it if creator-
        feed depth becomes important.
        """
        page_limit = max(1, min(100, limit))
        return self.get_json(
            "/app.bsky.feed.getAuthorFeed",
            params={"actor": actor, "limit": page_limit},
        )


# Module-level singleton — built lazily so importing the module is cheap
# and tests can swap the instance via `_reset_for_tests()`.
_INSTANCE: BlueskyClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> BlueskyClient:
    """Return the process-global ``BlueskyClient`` (lazy init)."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = BlueskyClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    """Drop the cached singleton so the next ``get_client()`` rebuilds."""
    global _INSTANCE
    _INSTANCE = None

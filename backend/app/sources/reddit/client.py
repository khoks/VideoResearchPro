"""Reddit API client — OAuth (`client_credentials`) + rate-limited HTTP.

What this module provides:

- A singleton `RedditClient` accessed via `get_client()`.
- Script-app OAuth: `POST /api/v1/access_token` with HTTP Basic auth
  using `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. Token is cached
  in-process and refreshed lazily on a 401.
- Token-bucket rate limiting against `REDDIT_RATE_LIMIT_RPM` (default
  100 req/min on Reddit's free OAuth tier → ~0.6 sec spacing).
- Convenience wrappers for the four endpoints the connector uses today:
  `/search`, `/r/<sub>/search`, `/user/<name>/submitted`, `/comments/<id>`.

Reddit's User-Agent rules are stricter than most APIs — bad/empty UA
strings get aggressively rate-limited. We send `REDDIT_USER_AGENT`
(default `pratidhvani/0.1 (by u/anonymous)`) on every request including
the OAuth handshake.

Tests should mock `get_client` to return a `unittest.mock.Mock` rather
than monkey-patching httpx — see `tests/test_sources/test_reddit_connector.py`.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

REDDIT_OAUTH_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"


class RedditAuthError(RuntimeError):
    """Raised when OAuth token retrieval fails (bad credentials, network)."""


class RedditClient:
    """Thread-safe HTTP client for Reddit's read-only OAuth API."""

    def __init__(self) -> None:
        rpm = max(1, settings.REDDIT_RATE_LIMIT_RPM)
        # secs_between_requests = 60 / RPM. Default 100 RPM → 0.6s spacing.
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._token: str | None = None
        self._token_lock = threading.Lock()
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    def _fetch_token(self) -> str:
        client_id = settings.REDDIT_CLIENT_ID
        client_secret = settings.REDDIT_CLIENT_SECRET
        if not client_id or not client_secret:
            raise RedditAuthError(
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET must be set"
            )
        try:
            resp = httpx.post(
                REDDIT_OAUTH_URL,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"User-Agent": settings.REDDIT_USER_AGENT},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RedditAuthError(f"Reddit OAuth token fetch failed: {e}") from e
        token = resp.json().get("access_token")
        if not token:
            raise RedditAuthError("Reddit OAuth response missing access_token")
        return token

    def _get_token(self, force: bool = False) -> str:
        with self._token_lock:
            if force or self._token is None:
                self._token = self._fetch_token()
            return self._token

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``REDDIT_API_BASE + path`` and return the parsed JSON.

        Rate-limited per `REDDIT_RATE_LIMIT_RPM`. On a 401 the cached
        token is dropped and the request is retried exactly once. Any
        other HTTP failure raises ``httpx.HTTPError``.
        """
        url = f"{REDDIT_API_BASE}{path}"
        for attempt in (0, 1):
            self._limiter.wait()
            token = self._get_token(force=(attempt == 1))
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": settings.REDDIT_USER_AGENT,
            }
            resp = httpx.get(
                url, params=params, headers=headers, timeout=self._timeout
            )
            if resp.status_code == 401 and attempt == 0:
                logger.info("Reddit token rejected (401); refreshing")
                continue
            resp.raise_for_status()
            return resp.json()
        # Unreachable: the loop body either returns or raises.
        raise RuntimeError("Unreachable: Reddit get_json retry loop fell through")

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 25, sort: str = "relevance") -> dict:
        """Site-wide post search. Returns the raw `Listing` JSON."""
        return self.get_json(
            "/search",
            params={"q": query, "limit": limit, "sort": sort, "type": "link"},
        )

    def search_subreddit(
        self,
        subreddit: str,
        query: str,
        limit: int = 25,
        sort: str = "relevance",
    ) -> dict:
        """Subreddit-scoped post search."""
        return self.get_json(
            f"/r/{subreddit}/search",
            params={
                "q": query,
                "limit": limit,
                "sort": sort,
                "restrict_sr": "true",
                "type": "link",
            },
        )

    def list_user_posts(
        self, username: str, limit: int = 25, sort: str = "new"
    ) -> dict:
        """List a user's submitted posts (no comments)."""
        return self.get_json(
            f"/user/{username}/submitted",
            params={"limit": limit, "sort": sort},
        )

    def get_post_with_comments(
        self, post_id: str, limit: int | None = None, depth: int | None = None
    ) -> list:
        """Fetch the post + comment tree from `/comments/<post_id>`.

        Returns Reddit's two-element response: `[post_listing, comments_listing]`.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if depth is not None:
            params["depth"] = depth
        return self.get_json(f"/comments/{post_id}", params=params or None)


# Module-level singleton — built lazily so importing the module is cheap
# and tests can swap the instance via `_reset_for_tests()`.
_INSTANCE: RedditClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> RedditClient:
    """Return the process-global ``RedditClient`` (lazy init)."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = RedditClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    """Drop the cached singleton so the next ``get_client()`` rebuilds."""
    global _INSTANCE
    _INSTANCE = None

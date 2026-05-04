"""Twitter API v2 client — bearer-auth, rate-limited.

What this module provides:

- A singleton `TwitterClient` accessed via `get_client()`.
- Token-bucket rate limiting against `TWITTER_RATE_LIMIT_RPM`
  (default 60 req/min — under the Pro tier's 50 req/15min cap on
  most search endpoints).
- Convenience wrappers for the three v2 endpoints the connector uses:
  `/2/tweets/search/recent` (topic search),
  `/2/tweets/{id}` + `/2/tweets/{id}` with `expansions` (single tweet
  + author), and `/2/users/by/username/{handle}` +
  `/2/users/{id}/tweets` (creator-feed listing).

Auth: ``Authorization: Bearer <TWITTER_BEARER_TOKEN>``. Bearer-only
auth (app-only) is enough for read paths; we never write or act on
behalf of users. Tests mock `get_client` rather than monkey-patching
httpx.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class TwitterClient:
    """Thread-safe bearer-auth client for Twitter API v2."""

    def __init__(self) -> None:
        rpm = max(1, settings.TWITTER_RATE_LIMIT_RPM)
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``<TWITTER_API_BASE><path>`` and return parsed JSON.

        Rate-limited; raises `RuntimeError` when no bearer token is
        configured (caller must check `is_enabled()` first).
        """
        if not settings.TWITTER_BEARER_TOKEN:
            raise RuntimeError(
                "TWITTER_BEARER_TOKEN unset — Twitter API path is gated"
            )
        url = f"{settings.TWITTER_API_BASE}{path}"
        self._limiter.wait()
        headers = {
            "Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}",
            "User-Agent": settings.TWITTER_USER_AGENT,
        }
        resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------
    def search_recent(self, query: str, limit: int = 10) -> dict:
        """Recent (last 7 days) tweets matching `query`.

        v2 endpoint: ``/2/tweets/search/recent``. Returns the raw
        envelope ``{data: [...], includes: {users: [...]}, meta: {...}}``.
        We request `tweet.fields=created_at,author_id,public_metrics`
        and `expansions=author_id` so the connector can build proper
        Candidate metadata without a second roundtrip.
        """
        # v2 caps `max_results` at 100 (paid) / 10 (free); clamp to 100.
        page_limit = max(10, min(100, limit))
        return self.get_json(
            "/tweets/search/recent",
            params={
                "query": query,
                "max_results": page_limit,
                "tweet.fields": "created_at,author_id,public_metrics,lang",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            },
        )

    def get_tweet(self, tweet_id: str | int) -> dict:
        """Fetch a single tweet by ID with full metadata + author."""
        return self.get_json(
            f"/tweets/{tweet_id}",
            params={
                "tweet.fields": "created_at,author_id,public_metrics,lang,conversation_id",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            },
        )

    def get_user_by_username(self, username: str) -> dict:
        """Resolve a `@handle` to a user record (id, username, name)."""
        return self.get_json(
            f"/users/by/username/{username}",
            params={"user.fields": "username,name,verified"},
        )

    def get_user_tweets(self, user_id: str, limit: int = 25) -> dict:
        """List a user's recent tweets (chronological).

        Used for `list_creator_items`. v2 caps `max_results` at 100
        on Pro tier; we use 25 as a reasonable default.
        """
        page_limit = max(5, min(100, limit))
        return self.get_json(
            f"/users/{user_id}/tweets",
            params={
                "max_results": page_limit,
                "tweet.fields": "created_at,public_metrics,lang",
                "exclude": "retweets,replies",
            },
        )

    def get_conversation_replies(
        self, conversation_id: str, limit: int = 50
    ) -> dict:
        """Fetch top replies in a conversation thread.

        Uses the recent-search endpoint with a `conversation_id:`
        operator — this is the canonical v2 way to traverse a thread.
        Replies sorted by Twitter's relevance ranking which already
        weights engagement.
        """
        return self.get_json(
            "/tweets/search/recent",
            params={
                "query": f"conversation_id:{conversation_id}",
                "max_results": max(10, min(100, limit)),
                "tweet.fields": "created_at,author_id,public_metrics,in_reply_to_user_id",
                "expansions": "author_id",
                "user.fields": "username,name",
            },
        )

    # ------------------------------------------------------------------
    # Capability flag
    # ------------------------------------------------------------------
    @staticmethod
    def is_enabled() -> bool:
        """True iff the operator has supplied a bearer token."""
        return bool(settings.TWITTER_BEARER_TOKEN)


_INSTANCE: TwitterClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> TwitterClient:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TwitterClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    global _INSTANCE
    _INSTANCE = None

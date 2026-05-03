"""Mastodon API client — unauthenticated public ActivityPub endpoints.

What this module provides:

- A singleton `MastodonClient` accessed via `get_client()`.
- Token-bucket rate limiting against `MASTODON_RATE_LIMIT_RPM`
  (default 60 req/min → 1.0 sec spacing). Mastodon's per-IP unauth
  limit is 300 req/5min ≈ 60 rpm, so we sit comfortably under the
  cap even with bursty discovery.
- Convenience wrappers for the three endpoints the connector uses:
  `/api/v1/timelines/tag/<hashtag>` (hashtag-tagged status discovery),
  `/api/v1/statuses/<id>` (single status metadata + body),
  `/api/v1/statuses/<id>/context` (replies + ancestors thread tree).
- A `/api/v1/accounts/lookup` wrapper used by `resolve_creator_id`
  to translate `@user@instance` handles to numeric account IDs, plus
  `/api/v1/accounts/<id>/statuses` for creator-feed listing.

Mastodon returns JSON directly — no OAuth, no Bearer token, no
`access_token` plumbing for these public read endpoints. We still
send `MASTODON_USER_AGENT` so the operator can identify us if a
host instance ever decides to throttle.

The instance base is configured via `MASTODON_INSTANCE_BASE`
(default `https://mastodon.social`). Self-hosters running on a
private instance can override this to a different ActivityPub host
without code changes.

Tests should mock `get_client` to return a `unittest.mock.Mock`
rather than monkey-patching httpx — see
`tests/test_sources/test_mastodon_connector.py`.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _api_base() -> str:
    """Strip any trailing slash from the configured instance base.

    Mastodon URLs are always `<instance>/api/v1/...`; we tolerate the
    operator setting `MASTODON_INSTANCE_BASE` either with or without
    a trailing slash.
    """
    return (settings.MASTODON_INSTANCE_BASE or "").rstrip("/")


class MastodonClient:
    """Thread-safe HTTP client for Mastodon's public read API."""

    def __init__(self) -> None:
        rpm = max(1, settings.MASTODON_RATE_LIMIT_RPM)
        # secs_between_requests = 60 / RPM. Default 60 RPM → 1.0s spacing.
        self._limiter = RateLimiter(rate=60.0 / rpm)
        self._timeout = httpx.Timeout(15.0, connect=5.0)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``<instance>/api/v1<path>`` and return the parsed JSON.

        Rate-limited per `MASTODON_RATE_LIMIT_RPM`. Any HTTP failure
        raises ``httpx.HTTPError``. There is no auth retry path —
        these endpoints are unauthenticated.
        """
        url = f"{_api_base()}/api/v1{path}"
        self._limiter.wait()
        headers = {"User-Agent": settings.MASTODON_USER_AGENT}
        resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------
    def timeline_tag(self, hashtag: str, limit: int = 25) -> list[dict]:
        """Fetch the public hashtag timeline.

        Mastodon's `/api/v1/timelines/tag/<tag>` returns up to `limit`
        statuses (max 40 per page) ordered by recency. The tag is
        passed without the leading `#`. We don't paginate today —
        a single page of 25 statuses is plenty for topic discovery
        and matches the per-source `limit_per_type` the orchestrator
        passes (10-25 in practice).
        """
        # Mastodon caps `limit` at 40; clamp defensively.
        page_limit = max(1, min(40, limit))
        return self.get_json(f"/timelines/tag/{hashtag}", params={"limit": page_limit})

    def get_status(self, status_id: str | int) -> dict:
        """Fetch a single status by id.

        Returns the full status payload including `content` (HTML),
        `account`, `tags`, counts (`replies_count`, `favourites_count`,
        `reblogs_count`), and the canonical `url`.
        """
        return self.get_json(f"/statuses/{status_id}")

    def get_context(self, status_id: str | int) -> dict:
        """Fetch the conversation context — `{ancestors, descendants}`.

        Replies (descendants) are flattened by Mastodon into a single
        list (not nested) but each reply carries `in_reply_to_id` so
        we can reconstruct depth in the flatten layer.
        """
        return self.get_json(f"/statuses/{status_id}/context")

    def lookup_account(self, acct: str) -> dict:
        """Resolve a `@user@instance` handle (or local `@user`) to an
        account dict. Used by ``resolve_creator_id`` to translate user
        hints to numeric account IDs for creator-feed listing.
        """
        return self.get_json("/accounts/lookup", params={"acct": acct})

    def list_account_statuses(
        self, account_id: str, limit: int = 25
    ) -> list[dict]:
        """List a creator's recent statuses.

        Used for `list_creator_items()`. Mastodon caps `limit` at 40;
        we clamp + return whatever the instance gives us. Today we
        don't paginate — a future PR can walk `Link: rel="next"` if
        creator-feed depth becomes important.
        """
        page_limit = max(1, min(40, limit))
        return self.get_json(
            f"/accounts/{account_id}/statuses",
            params={"limit": page_limit, "exclude_reblogs": "true"},
        )


# Module-level singleton — built lazily so importing the module is cheap
# and tests can swap the instance via `_reset_for_tests()`.
_INSTANCE: MastodonClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_client() -> MastodonClient:
    """Return the process-global ``MastodonClient`` (lazy init)."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = MastodonClient()
    return _INSTANCE


def _reset_for_tests() -> None:
    """Drop the cached singleton so the next ``get_client()`` rebuilds."""
    global _INSTANCE
    _INSTANCE = None

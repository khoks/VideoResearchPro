"""Twitter / X connector — search-having subclass on top of paste-mode TweetConnector.

Re-registers `source_type='tweet'` with a connector that can `search()`
and `list_creator_items()` via Twitter API v2 when a bearer token is
configured. The paste-mode base class continues to handle individual
tweet URL extraction (via trafilatura → Playwright → fail), and this
subclass adds the discovery surface.

Same operator-opt-in pattern as E-1.6's article connector
re-registration: when `TWITTER_BEARER_TOKEN` is unset, the search
methods return ``[]`` gracefully rather than raising. Topic jobs
that include `source_types=['tweet']` don't fail; they just yield
zero search candidates until the operator configures the token.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import settings
from app.sources import registry
from app.sources.paste_url.connector import (
    TweetConnector as _PasteTweetConnector,
)
from app.sources.twitter import client as twitter_client
from app.sources.types import Candidate

logger = logging.getLogger(__name__)


def _expansions_users(payload: dict) -> dict[str, dict]:
    """Index `includes.users` by user_id for cross-reference."""
    users = (
        payload.get("includes", {}).get("users")
        if isinstance(payload, dict)
        else None
    ) or []
    out: dict[str, dict] = {}
    for u in users:
        if isinstance(u, dict) and u.get("id"):
            out[str(u["id"])] = u
    return out


def _parse_iso(value: str | None) -> datetime | None:
    """Parse Twitter v2's ISO-8601 timestamps to UTC datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _tweet_url(username: str | None, tweet_id: str) -> str:
    """Canonical x.com URL for a tweet — what the user pastes."""
    if username:
        return f"https://x.com/{username}/status/{tweet_id}"
    return f"https://x.com/i/status/{tweet_id}"


def _tweet_to_candidate(
    tweet: dict, users_by_id: dict[str, dict]
) -> Candidate | None:
    """Convert a v2 tweet dict to a Candidate.

    `users_by_id` is the indexed `includes.users` from the same
    payload — lets us resolve `author_id` to a username + name
    without a second API call.
    """
    if not isinstance(tweet, dict):
        return None
    tid = str(tweet.get("id") or "")
    if not tid:
        return None
    body = tweet.get("text") or ""
    author_id = str(tweet.get("author_id") or "")
    user = users_by_id.get(author_id) if author_id else None
    username = (user.get("username") if user else None) or None
    display_name = (user.get("name") if user else None) or username
    metrics = tweet.get("public_metrics") or {}
    return Candidate(
        source_type="tweet",
        source_id=f"tweet:{tid}",
        title=body[:120] or display_name or tid,
        source_url=_tweet_url(username, tid),
        creator_external_id=username or author_id or None,
        creator_name=display_name or None,
        published_at=_parse_iso(tweet.get("created_at")),
        thumbnail_url=None,
        description=(body[:500] or None) if body else None,
        extra={
            k: metrics[k]
            for k in (
                "like_count",
                "retweet_count",
                "reply_count",
                "quote_count",
                "impression_count",
            )
            if k in metrics and metrics[k] is not None
        },
    )


class TwitterConnector(_PasteTweetConnector):
    """`source_type='tweet'` with discovery surface (Twitter API v2)."""

    source_type = "tweet"

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        """Recent-search via Twitter API v2.

        Returns ``[]`` when:
        - `query` is empty.
        - No bearer token configured (operator hasn't opted in).
        - The HTTP call fails (rate limit, 5xx, network error).
        """
        if not query.strip():
            return []
        if not settings.TWITTER_BEARER_TOKEN:
            logger.info(
                "TwitterConnector.search: TWITTER_BEARER_TOKEN unset; "
                "returning empty (paste-mode for individual tweets still works)"
            )
            return []
        try:
            payload = twitter_client.get_client().search_recent(
                query, limit=limit
            )
        except Exception as e:
            logger.warning(
                "TwitterConnector.search: API call failed for %r: %s",
                query,
                e,
            )
            return []
        users_by_id = _expansions_users(payload)
        tweets = (
            payload.get("data") if isinstance(payload, dict) else None
        ) or []
        candidates: list[Candidate] = []
        for tweet in tweets:
            cand = _tweet_to_candidate(tweet, users_by_id)
            if cand is not None:
                candidates.append(cand)
            if len(candidates) >= limit:
                break
        return candidates

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        """List a user's recent tweets.

        `creator_external_id` is the `@handle` (without the `@`) or a
        numeric user ID. We resolve handles via `/users/by/username/`
        first when needed, then call `/users/{id}/tweets`.

        Returns nothing when the bearer token is unset or any API call
        fails.
        """
        if not creator_external_id:
            return
        if not settings.TWITTER_BEARER_TOKEN:
            logger.info(
                "TwitterConnector.list_creator_items: TWITTER_BEARER_TOKEN "
                "unset for creator %r; returning empty",
                creator_external_id,
            )
            return
        client = twitter_client.get_client()
        actor = creator_external_id.lstrip("@")
        # If actor isn't all digits, treat as a handle and resolve
        # to numeric user_id first.
        user_id = actor
        username_for_url = actor
        if not actor.isdigit():
            try:
                user_payload = client.get_user_by_username(actor)
            except Exception as e:
                logger.warning(
                    "TwitterConnector.list_creator_items: handle resolution "
                    "failed for @%s: %s",
                    actor,
                    e,
                    extra={"job_id": job_id},
                )
                return
            user_data = (
                user_payload.get("data") if isinstance(user_payload, dict) else None
            )
            if not isinstance(user_data, dict):
                return
            user_id = str(user_data.get("id") or "")
            username_for_url = user_data.get("username") or actor
            if not user_id:
                return

        page_limit = limit if limit is not None else 25
        try:
            payload = client.get_user_tweets(user_id, limit=page_limit)
        except Exception as e:
            logger.warning(
                "TwitterConnector.list_creator_items: tweet listing failed "
                "for user_id=%s: %s",
                user_id,
                e,
                extra={"job_id": job_id},
            )
            return
        tweets = (
            payload.get("data") if isinstance(payload, dict) else None
        ) or []
        # Fake users index — we don't get expansions on this endpoint,
        # but we know the username from the prior lookup, so we can
        # synthesise a single-entry users_by_id mapping.
        synthetic_users = {user_id: {"username": username_for_url}}
        for tweet in tweets:
            tweet["author_id"] = user_id  # ensure author_id is set
            cand = _tweet_to_candidate(tweet, synthetic_users)
            if cand is not None:
                yield cand

    def resolve_creator_id(
        self, hint: str, *, job_id: str = ""
    ) -> str | None:
        """Translate user-supplied hints to a canonical handle.

        Accepts:
        - bare handle: ``alice``, ``@alice``
        - profile URL: ``https://x.com/alice`` or ``twitter.com/alice``
        - numeric user_id: ``123456789`` (passed through)

        Returns the resolved handle (without `@`) or None when the
        bearer is unset or lookup fails.
        """
        if not hint:
            return None
        if not settings.TWITTER_BEARER_TOKEN:
            return None
        cleaned = hint.strip()
        # Profile URL → handle.
        for prefix in ("https://x.com/", "https://www.x.com/", "https://twitter.com/", "https://www.twitter.com/"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].split("/", 1)[0].split("?", 1)[0]
                break
        cleaned = cleaned.lstrip("@")
        if cleaned.isdigit():
            return cleaned  # numeric user_id, pass through
        client = twitter_client.get_client()
        try:
            payload = client.get_user_by_username(cleaned)
        except Exception as e:
            logger.warning(
                "TwitterConnector.resolve_creator_id: lookup failed for @%s: %s",
                cleaned,
                e,
                extra={"job_id": job_id},
            )
            return None
        user = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            return None
        return user.get("username") or cleaned


# Re-register under `tweet`. The registry's `register()` is
# idempotent (last-write-wins per source_type), so the paste-mode
# TweetConnector originally registered in app/sources/paste_url
# gets replaced with this search-having subclass. Same E-1.6
# pattern used to upgrade the article connector.
_INSTANCE = TwitterConnector()
registry.register(_INSTANCE)

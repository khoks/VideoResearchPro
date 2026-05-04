"""Article connector — Brave Search discovery + RSS-feed iteration on top
of paste-mode primitives.

Subclasses :class:`app.sources.paste_url.connector.ArticleConnector` (the
paste-only article connector) and adds `search()` + `list_creator_items()`.
The base class's `fetch_text` (which delegates to
`article_extraction.extract_text`) is reused unchanged — discovery
yields URLs, the same extractor handles the rest.

When `BRAVE_SEARCH_API_KEY` is unset, `search()` returns ``[]``
gracefully rather than raising — operators who haven't opted into
search can still use paste-mode and RSS without per-call errors.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterator

from app.config import settings
from app.sources import registry
from app.sources.article import client as article_client
from app.sources.paste_url.connector import (
    ArticleConnector as _PasteArticleConnector,
    hash_url,
)
from app.sources.types import Candidate

logger = logging.getLogger(__name__)


def _brave_result_to_candidate(result: dict) -> Candidate | None:
    """Convert a Brave Search result row to a Candidate, or None if shape-broken."""
    if not isinstance(result, dict):
        return None
    url = result.get("url") or ""
    if not url:
        return None
    title = (result.get("title") or url)[:500]
    desc = (result.get("description") or "")[:500]
    age = result.get("age") or ""  # Brave's relative-time string
    return Candidate(
        source_type="article",
        source_id=f"article:{hash_url(url)}",
        title=title,
        source_url=url,
        creator_external_id=None,  # Brave doesn't expose author at search-result level
        creator_name=None,
        published_at=None,  # `age` is a relative string ("3 hours ago"); not parsed for now
        thumbnail_url=None,
        description=desc or None,
        extra={"brave_age": age} if age else {},
    )


def _entry_to_candidate(entry: Any, feed_url: str) -> Candidate | None:
    """Convert a feedparser RSS entry to a Candidate.

    Mirrors the podcast `_entry_to_candidate` but for article entries
    — picks `link` as the canonical URL, pulls title / summary /
    author / published from feedparser-normalised fields.
    """
    # feedparser entries support both attr and dict access on
    # FeedParserDict; tolerate plain dicts in tests.
    def _get(e, key, default=None):
        v = getattr(e, key, None)
        if v is None and hasattr(e, "get"):
            try:
                v = e.get(key)
            except (TypeError, AttributeError):
                v = None
        return v if v is not None else default

    url = _get(entry, "link", "")
    if not url:
        return None
    title = _get(entry, "title", "") or url
    summary = _get(entry, "summary", "") or _get(entry, "description", "") or ""
    author = _get(entry, "author", "")
    published = None
    parsed = _get(entry, "published_parsed", None) or _get(entry, "updated_parsed", None)
    if parsed:
        try:
            from datetime import timezone
            published = datetime(*parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            published = None
    return Candidate(
        source_type="article",
        source_id=f"article:{hash_url(url)}",
        title=title[:500],
        source_url=url,
        creator_external_id=feed_url,  # feed URL = canonical creator id
        creator_name=author or None,
        published_at=published,
        thumbnail_url=None,
        description=(summary[:500] or None) if summary else None,
        extra={"feed_url": feed_url},
    )


class ArticleConnector(_PasteArticleConnector):
    """`source_type='article'` with discovery surface.

    Search via Brave; creator-feed iteration via RSS. Inherits
    paste-mode `fetch_text` from the base class so the extraction
    pipeline stays identical regardless of how the URL was discovered.
    """

    source_type = "article"

    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        """Brave Search → article candidates.

        Returns ``[]`` when:
        - `query` is empty.
        - No Brave API key is configured (operator hasn't opted in).
        - Brave returns no web results.
        - The HTTP call raises (network error, 5xx, rate limit, etc.).

        The `[]` return on no-key is a deliberate design choice (per
        D-035-style "graceful empty" rather than NotImplementedError):
        the article connector *has* a search surface — it's just
        gated on operator opt-in. Topic jobs that include
        `source_types=['article']` don't fail; they just yield zero
        article candidates until the key is configured.
        """
        if not query.strip():
            return []
        if not settings.BRAVE_SEARCH_API_KEY:
            logger.info(
                "ArticleConnector.search: BRAVE_SEARCH_API_KEY unset; "
                "returning empty (configure to enable web-search discovery)"
            )
            return []
        try:
            payload = article_client.get_client().brave_search(query, limit=limit)
        except Exception as e:
            logger.warning(
                "ArticleConnector.search: Brave call failed for %r: %s",
                query,
                e,
            )
            return []
        web = payload.get("web") if isinstance(payload, dict) else None
        results = (
            web.get("results") if isinstance(web, dict) else None
        ) or []
        candidates: list[Candidate] = []
        for r in results:
            cand = _brave_result_to_candidate(r)
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
        """RSS feed → article candidates.

        `creator_external_id` is the RSS feed URL — opaque to the
        connector; treated as the canonical id for this "creator"
        (the publication / blog).
        """
        if not creator_external_id:
            return
        try:
            feed = article_client.get_client().fetch_feed(creator_external_id)
        except Exception as e:
            logger.warning(
                "ArticleConnector.list_creator_items: feed fetch failed for %s: %s",
                creator_external_id,
                e,
                extra={"job_id": job_id},
            )
            return
        entries = (
            feed.get("entries") if isinstance(feed, dict) else getattr(feed, "entries", None)
        ) or []
        page_limit = limit if limit is not None else 25
        for entry in entries[:page_limit]:
            cand = _entry_to_candidate(entry, creator_external_id)
            if cand is not None:
                yield cand


# Re-register under `article` — the registry's `register()` is
# idempotent (last-write-wins per source_type), so the paste-mode
# ArticleConnector originally registered in app/sources/paste_url
# gets replaced with this search-having subclass.
_INSTANCE = ArticleConnector()
registry.register(_INSTANCE)

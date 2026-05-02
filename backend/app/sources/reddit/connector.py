"""Reddit connector — exposes the `BaseConnector` contract for
``source_type='reddit_post'``.

What it covers:

- Discovery via `/search` and subreddit-scoped `/r/<sub>/search`. The
  search agent can prefix a query with ``subreddit:<name> ...`` to scope.
- Listing a user's submitted posts via `/user/<name>/submitted`.
- Batch metadata via `/api/info?id=t3_<id>,t3_<id>...`.
- Full text via `/comments/<post_id>`, flattened by :mod:`flatten` into
  the OP body + top-N comments by score with explicit depth markers.

Identity convention: ``Candidate.source_id`` is namespaced
``f"reddit:{post_id}"``. The legacy ``video_id`` PK column is shared
across source types until the L1 schema migration promotes it to a
UUID, so namespacing prevents collisions with YouTube's 11-char IDs.

Sentiment / stance classification is not done here — it lives in the
`social_classify_stance` LLM use case (S-1.5.3) which the orchestrator
may invoke after the connector returns.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterator

from app.config import settings
from app.services.social_classify import classify
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.reddit import client as reddit_client
from app.sources.reddit import flatten as reddit_flatten
from app.sources.types import Candidate, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)

SOURCE_TYPE = "reddit_post"
SOURCE_ID_PREFIX = "reddit:"
REDDIT_PERMALINK_BASE = "https://www.reddit.com"

# Recognised inline scope prefix the search agent may emit:
#   "subreddit:economics tariffs in 2026"
# captures (sub, real_query). Matches the leading prefix only.
_SUBREDDIT_QUERY = re.compile(
    r"^\s*subreddit\s*:\s*([A-Za-z0-9_]+)\s+(.+)$", re.IGNORECASE
)


def _parse_created_utc(value: float | int | None) -> datetime | None:
    """Reddit returns Unix epoch seconds. Convert to a UTC ``datetime``."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _thumbnail_or_none(thumb: str | None) -> str | None:
    """Reddit's ``thumbnail`` field is sometimes a sentinel like
    ``"self"`` / ``"default"`` / ``"nsfw"``. Only real URLs are useful."""
    if not thumb or not isinstance(thumb, str) or not thumb.startswith("http"):
        return None
    return thumb


def _strip_prefix(source_id: str) -> str:
    """``reddit:abc123`` → ``abc123``. Tolerates IDs without the prefix."""
    if source_id.startswith(SOURCE_ID_PREFIX):
        return source_id[len(SOURCE_ID_PREFIX):]
    return source_id


def _post_url(post_data: dict) -> str:
    """Build a `https://www.reddit.com/...` URL for the post."""
    permalink = post_data.get("permalink") or ""
    if permalink:
        return f"{REDDIT_PERMALINK_BASE}{permalink}"
    post_id = post_data.get("id") or ""
    return f"{REDDIT_PERMALINK_BASE}/comments/{post_id}"


def _post_to_candidate(post_data: dict) -> Candidate:
    """Convert a Reddit ``t3`` post-data dict to a ``Candidate``."""
    post_id = post_data.get("id") or ""
    selftext = post_data.get("selftext") or ""
    return Candidate(
        source_type=SOURCE_TYPE,
        source_id=f"{SOURCE_ID_PREFIX}{post_id}",
        title=post_data.get("title") or "",
        source_url=_post_url(post_data),
        creator_external_id=post_data.get("author") or None,
        creator_name=post_data.get("author") or None,
        published_at=_parse_created_utc(post_data.get("created_utc")),
        thumbnail_url=_thumbnail_or_none(post_data.get("thumbnail")),
        description=(selftext[:500] or None) if selftext else None,
        extra={
            k: post_data[k]
            for k in ("subreddit", "score", "num_comments", "url", "permalink")
            if k in post_data and post_data[k] is not None
        },
    )


def _post_to_metadata(post_data: dict) -> SourceMetadata:
    selftext = post_data.get("selftext") or ""
    return SourceMetadata(
        title=post_data.get("title") or None,
        creator_external_id=post_data.get("author") or None,
        creator_name=post_data.get("author") or None,
        published_at=_parse_created_utc(post_data.get("created_utc")),
        description=(selftext[:500] or None) if selftext else None,
        thumbnail_url=_thumbnail_or_none(post_data.get("thumbnail")),
        extra={
            k: post_data[k]
            for k in ("subreddit", "score", "num_comments", "url", "permalink")
            if k in post_data and post_data[k] is not None
        },
    )


def _children_to_post_dicts(listing: dict) -> list[dict]:
    """Pull the ``data`` payloads out of a Reddit listing, filtering to
    `t3` posts only (excludes `more`/`t1` cruft)."""
    children = (listing or {}).get("data", {}).get("children", [])
    return [c.get("data") or {} for c in children if c.get("kind") == "t3"]


class RedditConnector(BaseConnector):
    """`BaseConnector` for ``source_type='reddit_post'``."""

    source_type = SOURCE_TYPE

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        # `instructions` is interpreted upstream by the search agent when
        # planning query reformulations. The connector just runs each query.
        client = reddit_client.get_client()
        m = _SUBREDDIT_QUERY.match(query)
        if m:
            sub, real_query = m.group(1), m.group(2)
            listing = client.search_subreddit(sub, real_query, limit=limit)
        else:
            listing = client.search(query, limit=limit)
        return [_post_to_candidate(p) for p in _children_to_post_dicts(listing)]

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        # `since` is not yet honored — orchestrator filters via channel
        # `last_synced_at` (parity with the YouTube connector).
        client = reddit_client.get_client()
        page_limit = limit if limit is not None else 25
        listing = client.list_user_posts(creator_external_id, limit=page_limit)
        for post in _children_to_post_dicts(listing):
            yield _post_to_candidate(post)

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------
    def fetch_metadata(
        self,
        source_ids: list[str],
        *,
        job_id: str = "",
    ) -> dict[str, SourceMetadata]:
        if not source_ids:
            return {}
        # /api/info accepts a comma-separated list of fullnames. Strip
        # our `reddit:` prefix and prepend `t3_` (the post fullname).
        fullnames = ",".join(f"t3_{_strip_prefix(sid)}" for sid in source_ids)
        client = reddit_client.get_client()
        listing = client.get_json("/api/info", params={"id": fullnames})
        out: dict[str, SourceMetadata] = {}
        for post in _children_to_post_dicts(listing):
            post_id = post.get("id")
            if not post_id:
                continue
            out[f"{SOURCE_ID_PREFIX}{post_id}"] = _post_to_metadata(post)
        return out

    # ------------------------------------------------------------------
    # Text payload
    # ------------------------------------------------------------------
    def fetch_text(
        self,
        candidate: Candidate,
        *,
        job_id: str = "",
        query: str = "",
    ) -> ExtractedText | None:
        post_id = _strip_prefix(candidate.source_id)
        client = reddit_client.get_client()
        try:
            listing = client.get_post_with_comments(
                post_id,
                limit=settings.REDDIT_COMMENT_DEPTH_DEFAULT,
            )
        except Exception as e:
            # Match the BaseConnector contract — any failure is reported
            # as `None` so the orchestrator marks the doc unavailable
            # rather than crashing the job.
            logger.warning(
                "Reddit fetch_text failed for post %s: %s",
                post_id,
                e,
                extra={"job_id": job_id},
            )
            return None

        segments, _post_data = reddit_flatten.flatten_post_with_comments(
            listing, top_n=settings.REDDIT_COMMENT_DEPTH_DEFAULT
        )
        if not segments:
            return None

        word_count = sum(len(seg.get("text", "").split()) for seg in segments)

        # Inline classification per D-023. Build the classifier input
        # from the OP segment plus a short summary of top-comment text.
        # The classifier itself fail-softs on empty query / LLM error,
        # so we don't need to guard here.
        classifier_text = _build_classifier_input(segments)
        classification = classify(classifier_text, query)

        return ExtractedText(
            segments=segments,
            language="en",  # Reddit doesn't expose language; assume EN.
            text_source="reddit",
            word_count=word_count,
            extra={"classification": classification.model_dump()},
        )


def _build_classifier_input(segments: list[dict]) -> str:
    """Assemble the text the classifier sees for a Reddit thread.

    Concatenate OP body + the top 3 comments (by score) so the
    classifier sees both the post register and the conversation tone.
    Per the D-023 rationale, the connector is the natural owner of
    this decision because the connector knows the segment shape.
    """
    if not segments:
        return ""
    op_text = segments[0].get("text", "") or ""
    # Reddit segments include extra={"score": int, ...}; sort comments
    # by score (descending) and take top 3. Defensive: if no scores,
    # take first 3 comments after OP.
    comments = segments[1:]
    comments_sorted = sorted(
        comments,
        key=lambda s: s.get("extra", {}).get("score", 0) or 0,
        reverse=True,
    )
    top_comments = comments_sorted[:3]
    parts = [op_text] + [c.get("text", "") or "" for c in top_comments]
    return "\n\n".join(p for p in parts if p)


# Module-level instance + eager registration. Importing this module
# registers the connector for `source_type="reddit_post"`.
_INSTANCE = RedditConnector()
registry.register(_INSTANCE)

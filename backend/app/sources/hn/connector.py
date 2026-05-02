"""Hacker News connector — exposes the `BaseConnector` contract for
``source_type='hn_story'``.

What it covers:

- Discovery via Algolia's ``/search`` (story-tagged hits, sorted by
  Algolia relevance which already weights points + recency).
- Listing a user's submitted stories via
  ``/search_by_date?tags=story,author_<name>``.
- Per-id metadata via ``/items/<id>`` (one call per id — Algolia has
  no batch endpoint, but typical metadata batches are small).
- Full text via ``/items/<id>``, flattened by :mod:`flatten` into the
  OP body + top-N comments by points with explicit depth markers.

Identity convention: ``Candidate.source_id`` is namespaced
``f"hn:{story_id}"``. The legacy ``video_id`` PK column is shared
across source types until the L1 schema migration promotes it to a
UUID, so namespacing prevents collisions with YouTube's 11-char IDs
and Reddit's base36 IDs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

from app.config import settings
from app.services.social_classify import classify
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.hn import client as hn_client
from app.sources.hn import flatten as hn_flatten
from app.sources.types import Candidate, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)

SOURCE_TYPE = "hn_story"
SOURCE_ID_PREFIX = "hn:"
HN_ITEM_URL_BASE = "https://news.ycombinator.com/item?id="


def _parse_created_at_i(value: float | int | None) -> datetime | None:
    """Algolia returns Unix epoch seconds in ``created_at_i``. Convert
    to a UTC ``datetime``."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _strip_prefix(source_id: str) -> str:
    """``hn:12345`` → ``12345``. Tolerates IDs without the prefix."""
    if source_id.startswith(SOURCE_ID_PREFIX):
        return source_id[len(SOURCE_ID_PREFIX):]
    return source_id


def _hn_item_url(story_id: str | int) -> str:
    """Canonical HN URL is the discussion page, not the linked article."""
    return f"{HN_ITEM_URL_BASE}{story_id}"


def _hit_to_candidate(hit: dict) -> Candidate:
    """Convert an Algolia search hit to a ``Candidate``.

    Algolia hits use ``objectID`` (string) for the item id and a
    flattened metadata shape — different from the ``/items/<id>``
    response (which nests ``children`` and uses ``id`` as int).
    """
    story_id = str(hit.get("objectID") or "")
    title = hit.get("title") or hit.get("story_title") or ""
    body = hit.get("story_text") or ""
    return Candidate(
        source_type=SOURCE_TYPE,
        source_id=f"{SOURCE_ID_PREFIX}{story_id}",
        title=title,
        source_url=_hn_item_url(story_id),
        creator_external_id=hit.get("author") or None,
        creator_name=hit.get("author") or None,
        published_at=_parse_created_at_i(hit.get("created_at_i")),
        thumbnail_url=None,  # HN has no thumbnails.
        description=(body[:500] or None) if body else None,
        extra={
            k: hit[k]
            for k in ("url", "points", "num_comments")
            if k in hit and hit[k] is not None
        },
    )


def _item_to_candidate(item: dict) -> Candidate:
    """Convert an Algolia ``/items/<id>`` payload to a ``Candidate``.

    Differs from `_hit_to_candidate` because ``/items`` uses ``id``
    (int) and stores body text under ``text``, not ``story_text``.
    """
    story_id = str(item.get("id") or "")
    title = item.get("title") or ""
    body = item.get("text") or ""
    return Candidate(
        source_type=SOURCE_TYPE,
        source_id=f"{SOURCE_ID_PREFIX}{story_id}",
        title=title,
        source_url=_hn_item_url(story_id),
        creator_external_id=item.get("author") or None,
        creator_name=item.get("author") or None,
        published_at=_parse_created_at_i(item.get("created_at_i")),
        thumbnail_url=None,
        description=(body[:500] or None) if body else None,
        extra={
            k: item[k]
            for k in ("url", "points")
            if k in item and item[k] is not None
        },
    )


def _item_to_metadata(item: dict) -> SourceMetadata:
    body = item.get("text") or ""
    return SourceMetadata(
        title=item.get("title") or None,
        creator_external_id=item.get("author") or None,
        creator_name=item.get("author") or None,
        published_at=_parse_created_at_i(item.get("created_at_i")),
        description=(body[:500] or None) if body else None,
        thumbnail_url=None,
        extra={
            k: item[k]
            for k in ("url", "points")
            if k in item and item[k] is not None
        },
    )


def _hits(payload: dict) -> list[dict]:
    """Pull the ``hits`` list out of an Algolia search response."""
    if not isinstance(payload, dict):
        return []
    return [h for h in (payload.get("hits") or []) if isinstance(h, dict)]


class HNConnector(BaseConnector):
    """`BaseConnector` for ``source_type='hn_story'``."""

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
        client = hn_client.get_client()
        payload = client.search(query, limit=limit)
        return [_hit_to_candidate(h) for h in _hits(payload)]

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        # `since` is not yet honored — orchestrator filters via channel
        # `last_synced_at` (parity with the YouTube and Reddit connectors).
        client = hn_client.get_client()
        page_limit = limit if limit is not None else 25
        payload = client.search_by_author(creator_external_id, limit=page_limit)
        for hit in _hits(payload):
            yield _hit_to_candidate(hit)

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
        client = hn_client.get_client()
        out: dict[str, SourceMetadata] = {}
        # Algolia has no batch endpoint; one /items/<id> call per id.
        # Typical metadata batches are tens, not hundreds, so this is fine.
        for sid in source_ids:
            story_id = _strip_prefix(sid)
            try:
                item = client.get_item(story_id)
            except Exception as e:
                logger.warning(
                    "HN fetch_metadata failed for story %s: %s",
                    story_id,
                    e,
                    extra={"job_id": job_id},
                )
                continue
            if not isinstance(item, dict) or item.get("type") != "story":
                continue
            out[f"{SOURCE_ID_PREFIX}{story_id}"] = _item_to_metadata(item)
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
        story_id = _strip_prefix(candidate.source_id)
        client = hn_client.get_client()
        try:
            item = client.get_item(story_id)
        except Exception as e:
            # Match the BaseConnector contract — any failure is reported
            # as `None` so the orchestrator marks the doc unavailable
            # rather than crashing the job.
            logger.warning(
                "HN fetch_text failed for story %s: %s",
                story_id,
                e,
                extra={"job_id": job_id},
            )
            return None

        segments, _story_data = hn_flatten.flatten_story_with_comments(
            item, top_n=settings.HN_COMMENT_DEPTH_DEFAULT
        )
        if not segments:
            return None

        word_count = sum(len(seg.get("text", "").split()) for seg in segments)

        # Inline classification per D-023. Same shape as Reddit: OP
        # + top-3-by-score comments fed to the classifier. Fail-soft
        # inside the classifier itself.
        classifier_text = _build_classifier_input(segments)
        classification = classify(classifier_text, query)

        return ExtractedText(
            segments=segments,
            language="en",  # HN is English-dominant; assume EN.
            text_source="hn",
            word_count=word_count,
            extra={"classification": classification.model_dump()},
        )


def _build_classifier_input(segments: list[dict]) -> str:
    """Assemble the text the classifier sees for an HN thread.

    Same approach as Reddit: OP (story title + body) + top-3 comments
    by score. Per D-023, the connector decides what text to classify
    because it knows the segment shape best.
    """
    if not segments:
        return ""
    op_text = segments[0].get("text", "") or ""
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
# registers the connector for `source_type="hn_story"`.
_INSTANCE = HNConnector()
registry.register(_INSTANCE)

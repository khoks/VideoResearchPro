"""Bluesky connector — exposes the `BaseConnector` contract for
``source_type='bluesky_post'``.

What it covers:

- Discovery via ``app.bsky.feed.searchPosts``. Bluesky has real
  text search on the public XRPC API (unlike Mastodon, which only
  exposes hashtag timelines), so the search query is forwarded
  verbatim — no normalisation needed.
- Listing a creator's recent posts via ``app.bsky.feed.getAuthorFeed``
  (after resolving handles to DIDs through ``app.bsky.actor.getProfile``).
- Per-uri metadata via ``app.bsky.feed.getPostThread`` (one call per
  uri — Bluesky has no batch endpoint, but typical metadata batches
  are small).
- Full text via ``app.bsky.feed.getPostThread`` with depth=6,
  flattened by :mod:`flatten` into the OP body + top-N replies by
  likes with explicit depth markers.

Identity convention. ``Candidate.source_id`` is namespaced
``f"bluesky:{at_uri}"``. We carry the AT-URI rather than the rkey
because the AT-URI is the only stable identifier (DID+collection+rkey)
that round-trips into ``getPostThread``. The web URL
(``https://bsky.app/profile/<handle>/post/<rkey>``) goes into
``Candidate.source_url`` for browser-friendly citations.

Discovery rationale: AT-Proto's ``searchPosts`` returns posts ranked
by Bluesky's relevance scoring (currently keyword + recency + light
engagement weighting). We don't combine multiple searches — that's
the orchestrator's job via the search-agent's plan-queries step.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterator

from app.config import settings
from app.services.social_classify import classify
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.bluesky import client as bluesky_client
from app.sources.bluesky import flatten as bluesky_flatten
from app.sources.types import Candidate, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)

SOURCE_TYPE = "bluesky_post"
SOURCE_ID_PREFIX = "bluesky:"

# AT-URI regex: at://<did>/<collection>/<rkey>. The `did` part is
# of the form `did:plc:abc...` or `did:web:...`. We match permissively
# because the validator's job is structural, not semantic.
_AT_URI_RE = re.compile(r"^at://[^/]+/[^/]+/[^/]+$")
# bsky.app web URL: https://bsky.app/profile/<handle-or-did>/post/<rkey>.
_BSKY_WEB_URL_RE = re.compile(
    r"^https?://(?:www\.)?bsky\.app/profile/([^/]+)/post/([^/]+)/?$"
)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an AT-Proto ISO-8601 timestamp string to a UTC datetime."""
    if not value:
        return None
    try:
        # AT-Proto uses `Z` suffix; Python 3.11+ handles it natively
        # but we normalise defensively.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _strip_prefix(source_id: str) -> str:
    """``bluesky:at://...`` → ``at://...``. Tolerates IDs without the prefix."""
    if source_id.startswith(SOURCE_ID_PREFIX):
        return source_id[len(SOURCE_ID_PREFIX):]
    return source_id


def _post_web_url_from_components(handle: str | None, uri: str) -> str:
    """Build the ``https://bsky.app/profile/<handle>/post/<rkey>`` URL.

    Used at the candidate-building layer where we have the post's
    author handle from ``record.author`` but want the human-readable
    web URL alongside the AT-URI.
    """
    if not handle or not uri:
        return ""
    parts = uri.rsplit("/", 1)
    if len(parts) != 2:
        return ""
    rkey = parts[1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def _post_to_candidate(post: dict) -> Candidate:
    """Convert an AT-Proto post dict to a `Candidate`.

    Used for both ``searchPosts.posts[]`` and ``getAuthorFeed.feed[].post``
    results — the post shape is identical. Body lives under
    ``record.text``; like count under ``likeCount``.
    """
    uri = str(post.get("uri") or "")
    record = post.get("record") if isinstance(post.get("record"), dict) else {}
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    handle = author.get("handle") or ""
    display_name = author.get("displayName") or handle or None
    body = record.get("text") if isinstance(record.get("text"), str) else ""
    return Candidate(
        source_type=SOURCE_TYPE,
        source_id=f"{SOURCE_ID_PREFIX}{uri}",
        title=(body[:120] or display_name or uri or "(empty post)"),
        source_url=_post_web_url_from_components(handle, uri),
        creator_external_id=handle or author.get("did") or None,
        creator_name=display_name or None,
        published_at=_parse_iso(record.get("createdAt") if isinstance(record, dict) else None),
        thumbnail_url=_first_embed_thumbnail(post),
        description=(body[:500] or None) if body else None,
        extra={
            k: post[k]
            for k in (
                "likeCount",
                "repostCount",
                "replyCount",
                "indexedAt",
            )
            if k in post and post[k] is not None
        },
    )


def _first_embed_thumbnail(post: dict) -> str | None:
    """Extract the first image thumbnail from a post's ``embed`` block.

    AT-Proto embeds come in several shapes; we handle the common
    ``app.bsky.embed.images#view`` case (carries a list of
    ``{thumb, fullsize, alt}`` items). Other embed types (external
    links, quotes, video) are skipped — they don't have a meaningful
    thumbnail at this layer.
    """
    embed = post.get("embed")
    if not isinstance(embed, dict):
        return None
    images = embed.get("images")
    if not isinstance(images, list) or not images:
        return None
    first = images[0]
    if not isinstance(first, dict):
        return None
    return first.get("thumb") or first.get("fullsize") or None


def _post_to_metadata(post: dict) -> SourceMetadata:
    record = post.get("record") if isinstance(post.get("record"), dict) else {}
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    handle = author.get("handle") or ""
    display_name = author.get("displayName") or handle or None
    body = record.get("text") if isinstance(record.get("text"), str) else ""
    return SourceMetadata(
        title=(body[:120] or display_name) or None,
        creator_external_id=handle or author.get("did") or None,
        creator_name=display_name or None,
        published_at=_parse_iso(record.get("createdAt") if isinstance(record, dict) else None),
        description=(body[:500] or None) if body else None,
        thumbnail_url=_first_embed_thumbnail(post),
        extra={
            k: post[k]
            for k in (
                "likeCount",
                "repostCount",
                "replyCount",
                "indexedAt",
            )
            if k in post and post[k] is not None
        },
    )


def _posts_from_search(payload: dict) -> list[dict]:
    """Pull the ``posts`` list out of a searchPosts response."""
    if not isinstance(payload, dict):
        return []
    return [p for p in (payload.get("posts") or []) if isinstance(p, dict)]


def _posts_from_feed(payload: dict) -> list[dict]:
    """Pull the underlying posts out of a getAuthorFeed response.

    The feed payload is ``{feed: [{post: {...}, reason: ...}, ...]}``;
    each ``post`` is the same shape as ``searchPosts.posts[]``. We
    skip reposts (``reason.$type === 'app.bsky.feed.defs#reasonRepost'``)
    so the creator-feed only carries originally-authored content —
    parity with how the Mastodon connector excludes reblogs.
    """
    if not isinstance(payload, dict):
        return []
    out: list[dict] = []
    for entry in payload.get("feed") or []:
        if not isinstance(entry, dict):
            continue
        reason = entry.get("reason")
        if isinstance(reason, dict) and (
            reason.get("$type", "").endswith("#reasonRepost")
        ):
            continue
        post = entry.get("post")
        if isinstance(post, dict):
            out.append(post)
    return out


class BlueskyConnector(BaseConnector):
    """`BaseConnector` for ``source_type='bluesky_post'``."""

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
        # `instructions` is interpreted upstream by the search agent
        # when planning query reformulations. The connector just runs
        # each query as-written.
        if not query.strip():
            return []
        client = bluesky_client.get_client()
        try:
            payload = client.search_posts(query, limit=limit)
        except Exception as e:
            logger.warning("Bluesky search failed for %r: %s", query, e)
            return []
        return [_post_to_candidate(p) for p in _posts_from_search(payload)]

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        # `since` is not yet honored — orchestrator filters via
        # channel `last_synced_at` (parity with the YouTube/Reddit/HN/
        # Mastodon connectors).
        # `creator_external_id` is the handle (or DID); ``getAuthorFeed``
        # accepts either, so no separate resolution step is needed.
        client = bluesky_client.get_client()
        page_limit = limit if limit is not None else 25
        try:
            payload = client.get_author_feed(creator_external_id, limit=page_limit)
        except Exception as e:
            logger.warning(
                "Bluesky list_creator_items failed for %r: %s",
                creator_external_id,
                e,
                extra={"job_id": job_id},
            )
            return
        for post in _posts_from_feed(payload):
            yield _post_to_candidate(post)

    def resolve_creator_id(
        self, hint: str, *, job_id: str = ""
    ) -> str | None:
        """Translate a free-text hint to a canonical Bluesky handle.

        Accepts:
          - bare handle: ``alice.bsky.social``
          - prefixed handle: ``@alice.bsky.social``
          - profile URL: ``https://bsky.app/profile/alice.bsky.social``
          - DID: ``did:plc:abc...``

        Returns the handle (preferred) or DID as the canonical
        ``creator_external_id``. Returns None when the hint can't be
        resolved.
        """
        if not hint:
            return None
        cleaned = hint.strip()
        # Profile URL → handle.
        m = re.match(
            r"^https?://(?:www\.)?bsky\.app/profile/([^/]+)/?$", cleaned
        )
        if m:
            cleaned = m.group(1)
        cleaned = cleaned.lstrip("@")
        client = bluesky_client.get_client()
        try:
            profile = client.get_profile(cleaned)
        except Exception as e:
            logger.warning(
                "Bluesky resolve_creator_id failed for %r: %s",
                cleaned,
                e,
                extra={"job_id": job_id},
            )
            return None
        if not isinstance(profile, dict):
            return None
        return profile.get("handle") or profile.get("did") or None

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
        client = bluesky_client.get_client()
        out: dict[str, SourceMetadata] = {}
        # AT-Proto has no batch metadata endpoint; one
        # /getPostThread call per uri (we use depth=0 to skip the
        # reply tree). Typical metadata batches are tens, not hundreds.
        for sid in source_ids:
            uri = _strip_prefix(sid)
            if not _AT_URI_RE.match(uri):
                # Forward-compat: tolerate plain rkey-shaped IDs by
                # skipping rather than raising.
                continue
            try:
                payload = client.get_post_thread(uri, depth=0)
            except Exception as e:
                logger.warning(
                    "Bluesky fetch_metadata failed for %s: %s",
                    uri,
                    e,
                    extra={"job_id": job_id},
                )
                continue
            thread = payload.get("thread") if isinstance(payload, dict) else None
            post = thread.get("post") if isinstance(thread, dict) else None
            if not isinstance(post, dict):
                continue
            out[f"{SOURCE_ID_PREFIX}{uri}"] = _post_to_metadata(post)
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
        uri = _strip_prefix(candidate.source_id)
        if not _AT_URI_RE.match(uri):
            logger.warning(
                "Bluesky fetch_text: malformed AT-URI %r, skipping",
                uri,
                extra={"job_id": job_id},
            )
            return None
        client = bluesky_client.get_client()
        try:
            payload = client.get_post_thread(uri)
        except Exception as e:
            # Match the BaseConnector contract — any failure is
            # reported as `None` so the orchestrator marks the doc
            # unavailable rather than crashing the job.
            logger.warning(
                "Bluesky fetch_text: get_post_thread failed for %s: %s",
                uri,
                e,
                extra={"job_id": job_id},
            )
            return None

        segments, op_post = bluesky_flatten.flatten_thread(
            payload, top_n=settings.BLUESKY_COMMENT_DEPTH_DEFAULT
        )
        if not segments:
            return None

        word_count = sum(len(seg.get("text", "").split()) for seg in segments)

        # Bluesky records expose ``langs`` (list) on the record; we
        # take the first as the primary language. Default to "en"
        # when unset.
        record = op_post.get("record") if isinstance(op_post, dict) else {}
        langs = record.get("langs") if isinstance(record, dict) else None
        language = (
            (langs[0] if isinstance(langs, list) and langs else None)
            or "en"
        )

        # Inline classification per D-023. Same shape as Reddit/HN/
        # Mastodon: OP + top-3 replies by likes fed to the classifier.
        # Fail-soft inside the classifier itself.
        classifier_text = _build_classifier_input(segments)
        classification = classify(classifier_text, query)

        return ExtractedText(
            segments=segments,
            language=language,
            text_source="bluesky",
            word_count=word_count,
            extra={"classification": classification.model_dump()},
        )


def _build_classifier_input(segments: list[dict]) -> str:
    """Assemble the text the classifier sees for a Bluesky thread.

    Same approach as Reddit/HN/Mastodon: OP + top-3 replies by likes.
    Per D-023, the connector decides what text to classify because it
    knows the segment shape best.
    """
    if not segments:
        return ""
    op_text = segments[0].get("text", "") or ""
    replies = segments[1:]
    replies_sorted = sorted(
        replies,
        key=lambda s: s.get("extra", {}).get("likes", 0) or 0,
        reverse=True,
    )
    top_replies = replies_sorted[:3]
    parts = [op_text] + [r.get("text", "") or "" for r in top_replies]
    return "\n\n".join(p for p in parts if p)


# Module-level instance + eager registration. Importing this module
# registers the connector for ``source_type="bluesky_post"``.
_INSTANCE = BlueskyConnector()
registry.register(_INSTANCE)

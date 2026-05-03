"""Mastodon connector — exposes the `BaseConnector` contract for
``source_type='mastodon_post'``.

What it covers:

- Discovery via Mastodon's public hashtag-timeline endpoint
  (`/api/v1/timelines/tag/<hashtag>`). The query is normalised to a
  hashtag-friendly form (lowercase, alphanumerics only) since Mastodon
  hashtags don't tolerate spaces or punctuation.
- Listing a creator's recent statuses via `/api/v1/accounts/<id>/statuses`
  (after resolving `@user@instance` handles to numeric account IDs
  through `/api/v1/accounts/lookup`).
- Per-id metadata via `/api/v1/statuses/<id>` (one call per id —
  Mastodon has no batch endpoint; typical metadata batches are small).
- Full text via `/api/v1/statuses/<id>` + `/api/v1/statuses/<id>/context`,
  flattened by :mod:`flatten` into the OP body + top-N replies by
  favourites with explicit depth markers.

Identity convention: ``Candidate.source_id`` is namespaced
``f"mastodon:{status_id}"``. The legacy ``video_id`` PK column is
shared across source types until the L1 schema migration promotes it
to a UUID, so namespacing prevents collisions with YouTube IDs,
Reddit base36 IDs, and HN integer IDs.

Rationale for hashtag-as-discovery: Mastodon has no global keyword
search by default (most instances disable full-text search to honour
user privacy). The hashtag timeline is the only public, federation-
aware discovery surface that doesn't require an account. We map the
topic query to a single hashtag rather than splitting into multiple
words because hashtag conventions are single-token (e.g.
`#climatechange`, not `#climate #change`).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Iterator

from app.config import settings
from app.services.social_classify import classify
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.mastodon import client as mastodon_client
from app.sources.mastodon import flatten as mastodon_flatten
from app.sources.types import Candidate, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)

SOURCE_TYPE = "mastodon_post"
SOURCE_ID_PREFIX = "mastodon:"

# Mastodon's API returns ISO-8601 with `Z` suffix; Python's
# `datetime.fromisoformat` only learned to parse `Z` in 3.11. We're on
# 3.12, so it's safe — but we still guard against malformed strings.
_ISO_Z_RE = re.compile(r"Z$")


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a Mastodon ISO-8601 timestamp string to a UTC datetime."""
    if not value:
        return None
    try:
        # Normalise `Z` → `+00:00` for older Pythons (defensive — 3.12
        # handles it natively but cheaper than catching the exception).
        return datetime.fromisoformat(_ISO_Z_RE.sub("+00:00", value))
    except (ValueError, TypeError):
        return None


def _strip_prefix(source_id: str) -> str:
    """``mastodon:abc123`` → ``abc123``. Tolerates IDs without the prefix."""
    if source_id.startswith(SOURCE_ID_PREFIX):
        return source_id[len(SOURCE_ID_PREFIX):]
    return source_id


def _topic_to_hashtag(query: str) -> str:
    """Normalise a free-text topic query to a Mastodon hashtag.

    Mastodon hashtags accept Unicode letters, digits, and combining
    marks (necessary for Devanagari, Arabic, Thai, etc.) but not
    spaces, punctuation, or the leading `#`. We strip everything
    outside Unicode `L*` (Letter), `N*` (Number), and `M*` (Mark)
    categories and lowercase the rest.

    `str.isalnum()` is too aggressive — it rejects combining marks
    like `ि` (Devanagari vowel sign i) and `्` (Devanagari
    sign virama), which would mangle Hindi/Marathi/Bengali queries.
    Going through `unicodedata.category` keeps the writing-system
    integrity Mastodon's own parser preserves.

    Returns an empty string if nothing survives normalisation —
    callers should treat that as "no candidates" rather than calling
    the timeline endpoint with a bad path.
    """
    if not query:
        return ""
    out: list[str] = []
    for ch in query.lower():
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N", "M"):
            out.append(ch)
    return "".join(out)


def _status_to_candidate(status: dict) -> Candidate:
    """Convert a Mastodon status dict to a `Candidate`.

    Used for both timeline-tag results and account-statuses results
    (the shape is identical — Mastodon returns the same status object
    everywhere). Body is HTML; we surface the first 500 raw characters
    as `description` for display, leaving the proper HTML scrub for
    the full text-fetch path so we don't pay strip_html twice.
    """
    status_id = str(status.get("id") or "")
    account = status.get("account") or {}
    acct = account.get("acct") or account.get("username") or ""
    display_name = account.get("display_name") or acct or None
    body = status.get("content") or ""
    return Candidate(
        source_type=SOURCE_TYPE,
        source_id=f"{SOURCE_ID_PREFIX}{status_id}",
        title=(body[:120] or display_name or status_id),
        source_url=status.get("url") or "",
        creator_external_id=acct or None,
        creator_name=display_name or None,
        published_at=_parse_iso(status.get("created_at")),
        thumbnail_url=_first_media_url(status),
        description=(body[:500] or None) if body else None,
        extra={
            k: status[k]
            for k in (
                "favourites_count",
                "reblogs_count",
                "replies_count",
                "language",
            )
            if k in status and status[k] is not None
        },
    )


def _first_media_url(status: dict) -> str | None:
    """Return the URL of the first media attachment, if any.

    Mastodon attaches images/video as `media_attachments` — a list of
    objects with `preview_url` (smaller, faster) and `url` (full size).
    Use the preview for thumbnails; fall back to `url` if the preview
    is missing.
    """
    media = status.get("media_attachments") or []
    if not isinstance(media, list) or not media:
        return None
    first = media[0]
    if not isinstance(first, dict):
        return None
    return first.get("preview_url") or first.get("url") or None


def _status_to_metadata(status: dict) -> SourceMetadata:
    body = status.get("content") or ""
    account = status.get("account") or {}
    acct = account.get("acct") or account.get("username") or ""
    display_name = account.get("display_name") or acct or None
    return SourceMetadata(
        title=(body[:120] or display_name) or None,
        creator_external_id=acct or None,
        creator_name=display_name or None,
        published_at=_parse_iso(status.get("created_at")),
        description=(body[:500] or None) if body else None,
        thumbnail_url=_first_media_url(status),
        extra={
            k: status[k]
            for k in (
                "favourites_count",
                "reblogs_count",
                "replies_count",
                "language",
            )
            if k in status and status[k] is not None
        },
    )


class MastodonConnector(BaseConnector):
    """`BaseConnector` for ``source_type='mastodon_post'``."""

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
        # each query as a hashtag.
        hashtag = _topic_to_hashtag(query)
        if not hashtag:
            logger.info(
                "Mastodon search: query %r normalised to empty hashtag, skipping",
                query,
            )
            return []
        client = mastodon_client.get_client()
        try:
            statuses = client.timeline_tag(hashtag, limit=limit)
        except Exception as e:
            logger.warning(
                "Mastodon search failed for hashtag %r: %s", hashtag, e
            )
            return []
        if not isinstance(statuses, list):
            return []
        return [_status_to_candidate(s) for s in statuses if isinstance(s, dict)]

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        # `since` is not yet honored — orchestrator filters via channel
        # `last_synced_at` (parity with the YouTube/Reddit/HN connectors).
        # `creator_external_id` is the Mastodon `acct` (e.g.
        # "user@instance"); we resolve it to a numeric account_id first
        # and then list statuses.
        client = mastodon_client.get_client()
        try:
            account = client.lookup_account(creator_external_id)
        except Exception as e:
            logger.warning(
                "Mastodon list_creator_items: lookup_account failed for %r: %s",
                creator_external_id,
                e,
                extra={"job_id": job_id},
            )
            return
        if not isinstance(account, dict):
            return
        account_id = str(account.get("id") or "")
        if not account_id:
            return
        page_limit = limit if limit is not None else 25
        try:
            statuses = client.list_account_statuses(account_id, limit=page_limit)
        except Exception as e:
            logger.warning(
                "Mastodon list_creator_items: list_account_statuses failed for %s: %s",
                account_id,
                e,
                extra={"job_id": job_id},
            )
            return
        if not isinstance(statuses, list):
            return
        for status in statuses:
            if isinstance(status, dict):
                yield _status_to_candidate(status)

    def resolve_creator_id(
        self, hint: str, *, job_id: str = ""
    ) -> str | None:
        """Translate a free-text creator hint to the canonical `acct`.

        Accepts:
          - bare handle: ``@user@instance`` or ``user@instance``
          - account URL: ``https://mastodon.social/@user``

        Returns the canonical `acct` form (no leading `@`) or None
        when the hint can't be resolved.
        """
        if not hint:
            return None
        # Strip leading `@` and a possible URL prefix.
        cleaned = hint.strip().lstrip("@")
        # If they pasted a profile URL, pull the handle out.
        m = re.match(r"^https?://([^/]+)/@([^/]+)/?$", cleaned)
        if m:
            host, user = m.group(1), m.group(2)
            cleaned = f"{user}@{host}"
        client = mastodon_client.get_client()
        try:
            account = client.lookup_account(cleaned)
        except Exception as e:
            logger.warning(
                "Mastodon resolve_creator_id: lookup failed for %r: %s",
                cleaned,
                e,
                extra={"job_id": job_id},
            )
            return None
        if not isinstance(account, dict):
            return None
        return account.get("acct") or None

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
        client = mastodon_client.get_client()
        out: dict[str, SourceMetadata] = {}
        # Mastodon has no batch endpoint; one /statuses/<id> call per id.
        # Typical metadata batches are tens, not hundreds, so this is fine.
        for sid in source_ids:
            status_id = _strip_prefix(sid)
            try:
                status = client.get_status(status_id)
            except Exception as e:
                logger.warning(
                    "Mastodon fetch_metadata failed for status %s: %s",
                    status_id,
                    e,
                    extra={"job_id": job_id},
                )
                continue
            if not isinstance(status, dict):
                continue
            out[f"{SOURCE_ID_PREFIX}{status_id}"] = _status_to_metadata(status)
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
        status_id = _strip_prefix(candidate.source_id)
        client = mastodon_client.get_client()
        try:
            status = client.get_status(status_id)
        except Exception as e:
            # Match the BaseConnector contract — any failure is reported
            # as `None` so the orchestrator marks the doc unavailable
            # rather than crashing the job.
            logger.warning(
                "Mastodon fetch_text: get_status failed for %s: %s",
                status_id,
                e,
                extra={"job_id": job_id},
            )
            return None
        # Context is best-effort — if it fails, we still try to flatten
        # the OP body alone rather than dropping the whole status.
        try:
            context = client.get_context(status_id)
        except Exception as e:
            logger.warning(
                "Mastodon fetch_text: get_context failed for %s, "
                "falling back to OP-only: %s",
                status_id,
                e,
                extra={"job_id": job_id},
            )
            context = {"ancestors": [], "descendants": []}

        segments, _status_data = mastodon_flatten.flatten_status_with_context(
            status,
            context,
            top_n=settings.MASTODON_COMMENT_DEPTH_DEFAULT,
        )
        if not segments:
            return None

        word_count = sum(len(seg.get("text", "").split()) for seg in segments)

        language = (status.get("language") or "en") if isinstance(status, dict) else "en"

        # Inline classification per D-023. Same shape as Reddit/HN: OP
        # + top-3-by-favourites replies fed to the classifier. Fail-soft
        # inside the classifier itself.
        classifier_text = _build_classifier_input(segments)
        classification = classify(classifier_text, query)

        return ExtractedText(
            segments=segments,
            language=language,
            text_source="mastodon",
            word_count=word_count,
            extra={"classification": classification.model_dump()},
        )


def _build_classifier_input(segments: list[dict]) -> str:
    """Assemble the text the classifier sees for a Mastodon thread.

    Same approach as Reddit/HN: OP + top-3 replies by favourites. Per
    D-023, the connector decides what text to classify because it
    knows the segment shape best.
    """
    if not segments:
        return ""
    op_text = segments[0].get("text", "") or ""
    replies = segments[1:]
    replies_sorted = sorted(
        replies,
        key=lambda s: s.get("extra", {}).get("favourites", 0) or 0,
        reverse=True,
    )
    top_replies = replies_sorted[:3]
    parts = [op_text] + [r.get("text", "") or "" for r in top_replies]
    return "\n\n".join(p for p in parts if p)


# Module-level instance + eager registration. Importing this module
# registers the connector for `source_type="mastodon_post"`.
_INSTANCE = MastodonConnector()
registry.register(_INSTANCE)

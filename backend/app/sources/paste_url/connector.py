"""Paste-URL connectors — five source types, one shared extractor.

All five connectors (`article`, `fb_post`, `ig_post`, `li_post`,
`tweet`) share a single base class that delegates fetch_text to
``app.services.article_extraction.extract_text``. The only thing
that varies per connector is the ``source_type`` discriminator.

Per [D-035](../../../docs/decisions.md#d-035--connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03),
discovery is not supported (paste-only), so ``search()`` and
``list_creator_items()`` raise NotImplementedError.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import ClassVar, Iterator
from urllib.parse import urlparse

from app.services.article_extraction import extract_text
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)


def hash_url(url: str) -> str:
    """Stable identifier for a URL — full SHA-256 of normalised form.

    Normalisation strips tracking-parameter clutter: drop fragments,
    drop common UTM-style query params (utm_*, fbclid, igshid, gclid,
    etc.). What remains is the canonical URL that two pastes of "the
    same post with different sharing tags" should dedup against.
    """
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return hashlib.sha256(url.encode()).hexdigest()
    # Drop fragment.
    canonical = parsed._replace(fragment="")
    # Drop tracking params from the query string.
    if canonical.query:
        keep = []
        for part in canonical.query.split("&"):
            if not part:
                continue
            key = part.split("=", 1)[0].lower()
            if key in _TRACKING_PARAMS or key.startswith("utm_"):
                continue
            keep.append(part)
        canonical = canonical._replace(query="&".join(keep))
    canonical_str = canonical.geturl()
    return hashlib.sha256(canonical_str.encode()).hexdigest()


# Common tracking params that don't affect content identity. Lowercase
# matched against the raw query-string key.
_TRACKING_PARAMS = {
    "fbclid",
    "igshid",
    "gclid",
    "yclid",
    "msclkid",
    "ref",
    "ref_src",
    "_ga",
    "share_token",
    "si",  # YouTube share-tracking
    "feature",
}


class _PasteURLBaseConnector(BaseConnector):
    """Shared base for all paste-URL source types.

    Subclasses set ``source_type`` to one of: `article` / `fb_post` /
    `ig_post` / `li_post` / `tweet`. Behaviour is identical apart from
    that discriminator — the extraction path runs through the same
    article-extraction primitives.
    """

    source_type: ClassVar[str] = ""  # subclasses must override

    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        raise NotImplementedError(
            f"{self.source_type} connector has no search surface — "
            "use POST /api/v1/library/paste-urls"
        )

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        raise NotImplementedError(
            f"{self.source_type} connector has no creator concept"
        )

    def fetch_metadata(
        self,
        source_ids: list[str],
        *,
        job_id: str = "",
    ) -> dict[str, SourceMetadata]:
        # Paste connectors don't re-fetch — the upload endpoint already
        # captured everything from the initial extract.
        return {}

    def fetch_text(
        self,
        candidate: Candidate,
        *,
        job_id: str = "",
        query: str = "",
    ) -> ExtractedText | None:
        """Run extract_text against the candidate's URL.

        The URL lives in `candidate.source_url` (the paste endpoint
        stored it there when creating the Document). We delegate
        entirely to the article-extraction primitives — trafilatura
        primary, Playwright fallback when the operator opts in.

        Per-segment provenance: synthesise one segment for the whole
        article body. The chunker's dominant-segment heuristic is a
        no-op for single-segment inputs (one segment, one chunk-level
        identity). Each chunk in Chroma carries `comment_id =
        source_id` and `comment_url = source_url` so citations
        deep-link to the original post.
        """
        url = candidate.source_url
        if not url:
            logger.warning(
                "%s fetch_text: candidate has no source_url",
                self.source_type,
                extra={"job_id": job_id},
            )
            return None

        result = extract_text(url)
        if result is None:
            return None

        # Convert ExtractionResult to canonical-shape segments. We
        # synthesise ONE segment for the whole body — articles /
        # social posts don't have natural sub-segment boundaries
        # like videos (timestamps) or threads (replies). The
        # chunker handles segment-to-chunk packing per its existing
        # token-budget logic.
        segments = [
            {
                "text": result.text,
                "start": 0.0,
                "duration": float(result.word_count) / 3.0,  # 3-wps per D-013
                "extra": {
                    "kind": "post" if self.source_type != "article" else "article_body",
                    "author": result.author or "",
                    "comment_id": candidate.source_id,
                    "comment_url": url,
                    "depth": 0,
                },
            }
        ]
        return ExtractedText(
            segments=segments,
            language=result.language or "en",
            text_source=f"paste_extract_{result.source}",
            word_count=result.word_count,
            extra={
                "extractor_source": result.source,
                "extracted_title": result.title or "",
                "extracted_author": result.author or "",
                "url": url,
            },
        )


class ArticleConnector(_PasteURLBaseConnector):
    """`source_type='article'` — generic blog posts, news articles, substacks."""

    source_type = "article"


class FBPostConnector(_PasteURLBaseConnector):
    """`source_type='fb_post'` — Facebook public posts.

    Public-post extraction works via the Playwright fallback (FB is
    a JS-rendered SPA). Private posts won't extract — trafilatura sees
    the login wall and returns None; the dispatcher records the
    document as text_status=unavailable.
    """

    source_type = "fb_post"


class IGPostConnector(_PasteURLBaseConnector):
    """`source_type='ig_post'` — Instagram public posts and reels.

    Same Playwright requirement as FB; Instagram is the canonical
    SPA-shell page. Image-only posts (no caption text) extract
    nothing; that's expected.
    """

    source_type = "ig_post"


class LIPostConnector(_PasteURLBaseConnector):
    """`source_type='li_post'` — LinkedIn public posts.

    Trafilatura's static-HTML path works for many public LinkedIn
    pulse posts; activity-stream posts often need the Playwright
    fallback for full text.
    """

    source_type = "li_post"


class TweetConnector(_PasteURLBaseConnector):
    """`source_type='tweet'` — single tweets / X posts via paste.

    Mode B (paste) only. Mode A (search via paid Twitter API) is
    [S-1.5.10](../../../docs/initiatives.md#s-1510--twitter-connector-paid-api),
    a separate connector that registers for the same source_type
    when its BYOK token is configured.
    """

    source_type = "tweet"


# Eager registration. All five connectors register at import time,
# so `connector_for("article")` / etc resolve out of the box once
# this module is imported by `app.sources.__init__`.
_INSTANCES = [
    ArticleConnector(),
    FBPostConnector(),
    IGPostConnector(),
    LIPostConnector(),
    TweetConnector(),
]
for _c in _INSTANCES:
    registry.register(_c)

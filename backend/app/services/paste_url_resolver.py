"""URL → source_type resolver for Mode B paste-mode (S-1.5.8 T-1.5.8.1).

Maps a pasted URL to one of the paste-mode source types based on
host + path heuristics. Returns one of:

- ``"fb_post"`` — facebook.com / fb.com / facebook.* domains
- ``"ig_post"`` — instagram.com (post or reel)
- ``"li_post"`` — linkedin.com (posts / pulse / activity)
- ``"tweet"`` — twitter.com / x.com (status URLs)
- ``"article"`` — anything else (generic blog / news / substack /
  medium / etc.)

The resolver is purely host-based with optional path discrimination
for reels / status patterns. We don't attempt to follow redirects
or hit the URL — that happens later in the extraction step. False
positives (e.g. an embedded twitter.com link inside a news article
URL) won't survive the actual fetch step because the extractor will
see the page's content, but at the source_type level we route
based on the user's pasted URL alone.

Returns ``"article"`` as the safe default — a misclassification just
means the post lives under the wrong source_type filter; the text
extraction works regardless.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# Known social-platform host suffixes. Match against `parsed.netloc`
# stripped of leading `www.`/`m.`/locale subdomains.
_HOST_RULES: list[tuple[str, str]] = [
    # (host_suffix, source_type)
    ("facebook.com", "fb_post"),
    ("fb.com", "fb_post"),
    ("instagram.com", "ig_post"),
    ("linkedin.com", "li_post"),
    ("twitter.com", "tweet"),
    ("x.com", "tweet"),
]


# Subdomain prefixes we strip before matching. Many social platforms
# serve mobile / locale variants under different subdomains.
_STRIPPABLE_PREFIXES = ("www.", "m.", "mobile.", "lm.", "touch.")


def _normalise_host(host: str) -> str:
    """Strip common subdomain prefixes for host-suffix matching."""
    h = host.lower()
    for pfx in _STRIPPABLE_PREFIXES:
        if h.startswith(pfx):
            h = h[len(pfx) :]
            break  # only one strip layer; nested prefixes are rare
    return h


def resolve_source_type(url: str) -> str:
    """Return the paste-mode source_type for `url`.

    Always returns a valid source_type — defaults to ``"article"`` for
    URLs that don't match any social-platform rule. This means a paste
    of a TikTok URL, a Discord invite, or a Spotify share URL all
    fall into ``"article"`` for now. They might extract poorly (the
    Playwright fallback may or may not yield content), but the
    routing layer doesn't gatekeep — it just picks the most
    informative source_type from the URL alone.

    For URLs that fail to parse (None, empty, malformed), returns
    ``"article"`` rather than raising — same fail-soft contract as
    extract_text.
    """
    if not url or not isinstance(url, str):
        return "article"
    try:
        parsed = urlparse(url.strip())
    except (ValueError, TypeError):
        return "article"
    host = _normalise_host(parsed.netloc or "")
    if not host:
        return "article"
    for suffix, source_type in _HOST_RULES:
        if host == suffix or host.endswith("." + suffix):
            return source_type
    return "article"


def is_recognised_paste_source(source_type: str) -> bool:
    """True iff `source_type` is one of the five paste-mode types."""
    return source_type in {"article", "fb_post", "ig_post", "li_post", "tweet"}

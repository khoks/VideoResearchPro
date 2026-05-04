"""Paste-URL connectors for Mode B (S-1.5.8) — 5 source types share one extractor.

Closes S-1.5.8 (Mode B paste-mode for FB / IG / LI / X-without-paid-API +
generic blogs / news articles). Each source type has a thin connector
that registers under its own discriminator (``article`` / ``fb_post`` /
``ig_post`` / ``li_post`` / ``tweet``); all delegate to the same shared
``app.services.article_extraction.extract_text`` for the actual
fetch + boilerplate-removal + Playwright fallback.

**Why separate source types instead of one ``article`` catch-all.**

The original [`source-types.md`](../../../docs/source-types.md) matrix
(established by [D-005](../../../docs/decisions.md#d-005--social-media-ingest-before-article-ingest-2026-04-25)
and friends) already commits to per-platform discriminators because:

1. Citation rendering differs per platform (a "fb_post" cite renders
   differently from a "tweet" cite — different glyphs, different host
   parsing, different per-platform URL formats).
2. Library filtering by source_type is meaningful — users want to
   browse "all my Facebook posts" without "all my random blogs".
3. Future per-platform metadata extractors (parse FB post author from
   meta tags, X handle from URL, etc.) can pivot on source_type
   without re-classifying existing rows.
4. The polymorphic-plumbing claim (validated 7 times pre-S-1.5.8)
   rests on per-source-type discrimination at every layer; collapsing
   FB / IG / LI / X / generic into a single source_type would weaken
   the structural guarantees the contract provides.

**Identity convention.**

For all five paste connectors, ``Candidate.source_id`` is namespaced
``f"{source_type}:{sha256_of_url}"``. Rationale: the URL is the
canonical identifier (we can't use platform-native IDs because we
don't have the APIs for them); SHA-256 ensures dedup at the
``(source_type, source_id)`` unique index even when the URL has
tracking parameters that vary across pastes.

**Discovery surface — none.**

All five connectors raise ``NotImplementedError`` from ``search()``
and ``list_creator_items()`` per [D-035](../../../docs/decisions.md#d-035--connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03)
— they're paste-only. Discovery for tweet/X is a separate,
opt-in BYOK path filed as [S-1.5.9 / S-1.5.10](../../../docs/initiatives.md#s-159--pluggable-twitter-bearer-token-byok).

**Routing.**

The ``POST /api/v1/library/paste-urls`` endpoint resolves each URL
to the right ``source_type`` via :func:`resolve_source_type` (host-
based; see :mod:`app.services.paste_url_resolver`), then dispatches
through the connector registry just like every other source type.
"""

"""Twitter / X connector — BYOK paid API on top of paste-mode primitives.

Closes the **S-1.5.9 + S-1.5.10** Twitter pair. Per
[D-009](../../../docs/decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25),
Twitter access is BYOK + opt-in because the platform's free tier is
too restrictive for ingest at the scale this project needs.
Pro tier @ $100/mo is the realistic floor for search-based ingest.

The connector subclasses :class:`app.sources.paste_url.connector.TweetConnector`
(the paste-only base) and adds `search()` (Twitter API v2 recent
search) + `list_creator_items()` (user timeline) + an enriched
`fetch_text` that pulls the full tweet thread + top-K replies via
the Twitter API rather than just the trafilatura-extracted body.

Same E-1.6 pattern as the article connector: when the BYOK token is
unset, `search()` returns ``[]`` gracefully (rather than raising)
so topic jobs that include `source_types=['tweet']` don't fail —
they just yield zero candidates from search until the operator opts
in. Paste-mode for individual tweet URLs continues to work either
way (via the inherited `_PasteURLBaseConnector.fetch_text`).

Capability flag: when `TWITTER_BEARER_TOKEN` is set, the
`/api/v1/health` endpoint reports `twitter_search_enabled: true`
so the frontend can surface the topic-search-with-Twitter path
without the user having to inspect env state directly.
"""

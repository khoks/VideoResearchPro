"""Article connector — search-engine + RSS-feed discovery on top of paste-URL primitives.

Closes the E-1.6 full UX: T-1.6.2 (search-engine integration via Brave
Search API), T-1.6.3 (RSS feed ingestion), T-1.6.5 (e2e pipeline
test). T-1.6.4 (approval card variant + citation rendering) was
already shipped as part of S-1.5.8 PR #144.

The connector for `source_type='article'` was originally registered in
:mod:`app.sources.paste_url` for the paste-mode-only path (S-1.5.8).
This module **re-registers** it with a search-having subclass that
overrides `search()` (Brave Search) and `list_creator_items()` (RSS
feed iteration) while reusing the same paste-mode `fetch_text` from
the base class. The registry's idempotent re-registration semantics
(per :mod:`app.sources.registry`) make this safe — the second
registration replaces the first.

Per [D-035](../../../docs/decisions.md#d-035--connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03),
when no Brave key is configured `search()` returns an empty list
(rather than raising NotImplementedError) — the connector "has" a
search surface, it's just gated on operator opt-in.
"""

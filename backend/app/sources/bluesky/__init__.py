"""Bluesky source-type connector — registers under ``source_type='bluesky_post'``.

The connector is a thin wrapper around the public AT-Protocol XRPC
HTTP API at ``https://public.api.bsky.app/xrpc/``. Bluesky's public
read endpoints don't require auth, which matches the no-auth model
we use for HN and Mastodon — a write-side or quota-bumped tier
would need an app password but we don't need one for ingest today.

- ``client.py`` — unauthenticated, rate-limited HTTP wrapper.
- ``flatten.py`` — pure helpers that turn a `getPostThread` payload
  (post + recursive ``replies`` tree) into chunkable
  `{text, start, duration, extra}` segments. Pseudo-timestamps are
  synthesised at 3 wps via :mod:`app.sources._text_utils` (D-013).
- ``connector.py`` — `BlueskyConnector(BaseConnector)`. Imported
  eagerly by `app.sources.__init__` so registration happens at
  process start.

Identity convention. Bluesky posts have two parallel identifiers:
the AT-URI (``at://did:plc:...repo/app.bsky.feed.post/<rkey>``) and
the readable web URL (``https://bsky.app/profile/<handle>/post/<rkey>``).
We use the AT-URI as the canonical ``source_id`` because:

1. It's stable across handle renames (DIDs are permanent; handles are not).
2. It's what every XRPC endpoint expects as input.
3. It namespaces cleanly: ``bluesky:at://did:.../app.bsky.feed.post/<rkey>``.

The web URL goes into ``Candidate.source_url`` for browser-friendly
citations. Both are reconstructible from each other, so callers can
choose which one they want.
"""

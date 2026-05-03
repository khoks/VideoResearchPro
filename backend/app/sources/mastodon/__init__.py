"""Mastodon source-type connector — registers under `source_type='mastodon_post'`.

The connector is a thin wrapper around Mastodon's public ActivityPub
HTTP API. Mastodon servers are federated; we drive everything through
a single configurable instance (default `mastodon.social`) because
the public hashtag-timeline endpoint federates posts from across the
network anyway, so a single well-connected instance gives broad reach
without per-instance auth.

- `client.py` — unauthenticated, rate-limited HTTP wrapper. Mastodon's
  public timeline / status / context endpoints require no OAuth on
  most instances; per-IP unauth limit is 300 req/5min ≈ 60 rpm.
- `flatten.py` — pure helpers that turn a status + context (replies)
  payload into chunkable `{text, start, duration, extra}` segments.
  Pseudo-timestamps are synthesised at 3 wps via
  `app.sources._text_utils._segment_for_text` (D-013).
- `connector.py` — `MastodonConnector(BaseConnector)`. Imported
  eagerly by `app.sources.__init__` so registration happens at
  process start.

Identity convention: `Candidate.source_id` is namespaced
`f"mastodon:{status_id}"` so it cannot collide with YouTube video
IDs, Reddit post IDs, or HN story IDs while the legacy `video_id` PK
column is shared across source types.

Topic→hashtag mapping is the connector's discovery hook: a topic
search query is normalised (lowercased, non-alphanumerics stripped)
and queried via `/api/v1/timelines/tag/<hashtag>`. This is the same
shape Mastodon's own client uses; results are public posts tagged
with that hashtag, ranked by recency.
"""

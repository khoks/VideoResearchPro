"""Hacker News source-type connector — registers under `source_type='hn_story'`.

The connector is a thin wrapper around the public Algolia HN API
(`https://hn.algolia.com/api/v1/`):

- `client.py` — unauthenticated, rate-limited HTTP wrapper. Algolia's
  HN search is free and keyless; no OAuth handshake to manage.
- `flatten.py` — pure helpers that turn an Algolia item tree (story +
  recursively-nested children) into chunkable `{text, start, duration,
  extra}` segments. Pseudo-timestamps are synthesised at 3 wps via
  `app.sources._text_utils._segment_for_text` (D-013).
- `connector.py` — `HNConnector(BaseConnector)`. Imported eagerly by
  `app.sources.__init__` so registration happens at process start.

Identity convention: `Candidate.source_id` is namespaced
`f"hn:{story_id}"` so it cannot collide with YouTube video IDs or
Reddit post IDs while the legacy `video_id` PK column is shared across
source types.
"""

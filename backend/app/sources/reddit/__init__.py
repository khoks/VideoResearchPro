"""Reddit source-type connector — registers under `source_type='reddit_post'`.

The connector is a thin wrapper around the read-only Reddit API:

- `client.py` — OAuth (script-app `client_credentials`) + rate-limited
  HTTP wrapper. Hits `https://oauth.reddit.com/...` with a Bearer token.
- `flatten.py` — pure helpers that turn a Reddit `[post, comments]`
  listing into chunkable `{text, start, duration, extra}` segments.
- `connector.py` — `RedditConnector(BaseConnector)`. Imported eagerly
  by `app.sources.__init__` so registration happens at process start.

Identity convention: `Candidate.source_id` is namespaced
`f"reddit:{post_id}"` so it cannot collide with YouTube video IDs while
the legacy `video_id` PK column is shared across source types.
"""

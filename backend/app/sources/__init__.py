"""Source-type connector framework (L1 multi-source ingest).

The connector contract lives in `docs/source-types.md`. Every source type
(`video`, `podcast`, `article`, `tweet`, `forum_post`, `pdf`, …) ships as
a connector module that conforms to `BaseConnector` and registers itself
in `registry`. The job orchestrator dispatches to `connector_for(source_type)`
instead of calling provider-specific service modules directly.

Importing this package eagerly registers every shipped connector. Today
that's `video` (YouTube), `reddit_post` (Reddit), `hn_story`
(Hacker News), `mastodon_post` (Mastodon), `bluesky_post`
(Bluesky / AT-Protocol), and `podcast_episode` (RSS-feed podcasts
with iTunes-Search discovery + OpenAI-Whisper fallback). Future PRs
add `article`, `pdf`, etc.
"""
from app.sources.base import BaseConnector
from app.sources.registry import all_connectors, connector_for, register
from app.sources.types import Candidate, CreatorMetadata, ExtractedText, SourceMetadata

# Eager registration — importing each connector module triggers its
# `register(...)` call. Add new source types here as they ship.
from app.sources.video import connector as _video_connector  # noqa: F401  (registers on import)
from app.sources.reddit import connector as _reddit_connector  # noqa: F401  (registers on import)
from app.sources.hn import connector as _hn_connector  # noqa: F401  (registers on import)
from app.sources.mastodon import connector as _mastodon_connector  # noqa: F401  (registers on import)
from app.sources.bluesky import connector as _bluesky_connector  # noqa: F401  (registers on import)
from app.sources.podcast import connector as _podcast_connector  # noqa: F401  (registers on import)

__all__ = [
    "BaseConnector",
    "Candidate",
    "CreatorMetadata",
    "ExtractedText",
    "SourceMetadata",
    "all_connectors",
    "connector_for",
    "register",
]

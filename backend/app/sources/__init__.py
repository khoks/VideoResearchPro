"""Source-type connector framework (L1 multi-source ingest).

The connector contract lives in `docs/source-types.md`. Every source type
(`video`, `podcast`, `article`, `tweet`, `forum_post`, `pdf`, …) ships as
a connector module that conforms to `BaseConnector` and registers itself
in `registry`. The job orchestrator dispatches to `connector_for(source_type)`
instead of calling provider-specific service modules directly.

Importing this package eagerly registers every shipped connector. Today
that's `video` (YouTube), `reddit_post` (Reddit), `hn_story`
(Hacker News), `mastodon_post` (Mastodon), `bluesky_post`
(Bluesky / AT-Protocol), `podcast_episode` (RSS-feed podcasts with
iTunes-Search discovery + OpenAI-Whisper fallback), `pdf` (uploaded
PDFs / e-books with PyMuPDF text + table extraction), and the five
paste-mode source types (`article` / `fb_post` / `ig_post` /
`li_post` / `tweet`) that share `app.services.article_extraction`
for fetch + boilerplate-removal + Playwright fallback. **Twelve
source types total.**
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
from app.sources.pdf import connector as _pdf_connector  # noqa: F401  (registers on import)
from app.sources.paste_url import connector as _paste_url_connector  # noqa: F401  (registers article + fb_post + ig_post + li_post + tweet on import)
# `article` re-registration with search-having subclass (E-1.6 full
# UX). Order matters: paste_url registers `article` first, then this
# import overwrites it with the search-enabled variant per the
# registry's last-write-wins semantics.
from app.sources.article import connector as _article_connector  # noqa: F401  (re-registers article)
# `tweet` re-registration with search-having subclass (S-1.5.10 BYOK
# Twitter). Same idempotent re-registration pattern. When
# `TWITTER_BEARER_TOKEN` is unset, search()/list_creator_items()
# return empty gracefully rather than raising; paste-mode for
# individual tweet URLs continues to work via the inherited
# `_PasteURLBaseConnector.fetch_text` either way.
from app.sources.twitter import connector as _twitter_connector  # noqa: F401  (re-registers tweet)

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

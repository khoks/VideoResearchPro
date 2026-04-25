"""Typed dataclasses shared by every source-type connector.

Connectors do not expose provider-specific shapes (YouTube `video_id` dicts,
Spotify episode dicts, RSS entries, etc.). They normalize into the four
dataclasses below so the job orchestrator can stay source-type-agnostic.

See `docs/source-types.md` §"connector contract" for the spec these
mirror.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Candidate:
    """A single source-item candidate produced by `search()` or
    `list_creator_items()`.

    A Candidate is the *result of discovery*: enough metadata for the
    user to decide whether to approve it, and enough identity to round-
    trip into `fetch_text()` later. The full text payload is fetched
    later via `fetch_text(candidate)`.
    """

    source_type: str
    source_id: str
    title: str
    source_url: str
    creator_external_id: str | None = None
    creator_name: str | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    description: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedText:
    """The text payload produced by `fetch_text(candidate)`.

    `segments` is the canonical chunking-friendly representation. For
    time-based sources (video/podcast) each segment is `{text, start,
    duration}`. For text-based sources (article/PDF) the chunker accepts
    the same shape — articles synthesise pseudo-timestamps if needed,
    PDFs use page numbers in `extra`.
    """

    segments: list[dict[str, Any]]
    language: str
    text_source: str
    word_count: int
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceMetadata:
    """Per-item enrichment returned by `fetch_metadata([source_ids])`.

    Used after a Candidate has been chosen but before fetching text — the
    orchestrator may need duration, channel name, etc. for filtering or
    display before committing to the full text fetch.
    """

    title: str | None = None
    creator_external_id: str | None = None
    creator_name: str | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreatorMetadata:
    """Per-creator metadata for the `creators` table (today: `channels`).

    Returned by `fetch_creator(creator_external_id)`. Connectors that
    don't have a creator concept (e.g. PDFs) leave this unimplemented —
    the default in `BaseConnector` returns None.
    """

    creator_external_id: str
    name: str
    url: str | None = None
    description: str | None = None
    subscriber_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

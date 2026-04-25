"""YouTube video connector — wraps `app.services.youtube_service` to expose
the `BaseConnector` contract.

This module is intentionally a thin pass-through. All YouTube quirks
(API quota handling, transcript-API retry/back-off, Whisper fallback,
yt-dlp audio download, subscriber-count enrichment) live in
`youtube_service` and stay there. The connector's job is purely shape
normalization: turning provider-specific dicts into `Candidate`,
`SourceMetadata`, `ExtractedText`, `CreatorMetadata`.

Behavior must remain identical to direct `youtube_service` calls so that
PR 2 lands without observable changes. Future PRs may extend the
connector (e.g. emit `text_source="whisper"` once `fetch_transcript`
reports which path it took).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterator

from app.config import settings
from app.services import youtube_service
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate, CreatorMetadata, ExtractedText, SourceMetadata

logger = logging.getLogger(__name__)

_YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a YouTube ISO 8601 timestamp to a naive UTC `datetime`.

    Returns None on missing/unparseable input. Mirrors the lenient style
    elsewhere in the codebase — we don't crash on a malformed date.
    """
    if not value:
        return None
    try:
        # YouTube returns trailing "Z"; fromisoformat in 3.11+ handles "Z"
        # natively but we'll be safe.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _candidate_from_search_dict(d: dict) -> Candidate:
    """Convert a `search_videos` result dict into a `Candidate`."""
    return Candidate(
        source_type="video",
        source_id=d["video_id"],
        title=d.get("title", ""),
        source_url=_YOUTUBE_WATCH_URL.format(video_id=d["video_id"]),
        creator_external_id=d.get("channel_id"),
        creator_name=d.get("channel_name"),
        published_at=_parse_iso(d.get("published_at")),
        thumbnail_url=d.get("thumbnail_url"),
    )


def _candidate_from_id(video_id: str) -> Candidate:
    """Build a shallow `Candidate` from a bare video ID.

    Used by `list_creator_items` — today's `youtube_service.get_channel_videos*`
    helpers only return IDs (the subsequent `get_video_details` call
    enriches them). Keeping the connector thin means we surface the same
    shape: callers that want full metadata invoke `fetch_metadata` next.
    """
    return Candidate(
        source_type="video",
        source_id=video_id,
        title="",
        source_url=_YOUTUBE_WATCH_URL.format(video_id=video_id),
    )


def _metadata_from_details_dict(d: dict) -> SourceMetadata:
    return SourceMetadata(
        title=d.get("title"),
        creator_external_id=d.get("channel_id") or None,
        creator_name=d.get("channel_name") or None,
        duration_seconds=d.get("duration_seconds"),
        published_at=_parse_iso(d.get("published_at")),
        thumbnail_url=d.get("thumbnail_url"),
        extra={
            k: d[k]
            for k in ("view_count", "like_count", "url")
            if k in d and d[k] is not None
        },
    )


class YouTubeConnector(BaseConnector):
    """`BaseConnector` for `source_type="video"` (YouTube)."""

    source_type = "video"

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        # `instructions` is not used by the YouTube Data API search call;
        # it's interpreted upstream by the search agent when planning
        # query reformulations. The connector just runs each ready query.
        results = youtube_service.search_videos(query, max_results=limit)
        return [_candidate_from_search_dict(r) for r in results]

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
    ) -> Iterator[Candidate]:
        # `since` is not yet honored — today's job pipeline filters at
        # the orchestrator layer using the channel's `last_synced_at`.
        # When PR 3+ migrates that filter into the connector, this is
        # where it lands.
        if limit is None:
            ids = youtube_service.get_channel_videos_all(creator_external_id)
        else:
            ids = youtube_service.get_channel_videos(
                creator_external_id, max_results=limit
            )
        for vid in ids:
            yield _candidate_from_id(vid)

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------
    def fetch_metadata(self, source_ids: list[str]) -> dict[str, SourceMetadata]:
        if not source_ids:
            return {}
        details = youtube_service.get_video_details(source_ids)
        return {vid: _metadata_from_details_dict(d) for vid, d in details.items()}

    def fetch_creator(self, creator_external_id: str) -> CreatorMetadata | None:
        meta = youtube_service.get_channel_metadata(creator_external_id)
        if not meta:
            return None
        return CreatorMetadata(
            creator_external_id=creator_external_id,
            name=meta.get("name", ""),
            url=meta.get("url"),
            description=meta.get("description"),
            subscriber_count=meta.get("subscriber_count"),
            extra={
                k: meta[k]
                for k in ("uploads_playlist_id",)
                if k in meta and meta[k] is not None
            },
        )

    # ------------------------------------------------------------------
    # Text payload
    # ------------------------------------------------------------------
    def fetch_text(
        self,
        candidate: Candidate,
        *,
        job_id: str = "",
    ) -> ExtractedText | None:
        result = youtube_service.fetch_transcript(
            candidate.source_id,
            language=settings.DEFAULT_TRANSCRIPT_LANGUAGE,
            job_id=job_id,
        )
        if not result:
            return None
        segments, language = result
        word_count = sum(len(seg.get("text", "").split()) for seg in segments)
        # Today `fetch_transcript` doesn't tell us whether it took the
        # YouTube-Transcript-API path or the Whisper fallback (see job_tasks
        # comment that hardcodes "youtube"). Preserving that behavior
        # here — improving it is a separate change.
        return ExtractedText(
            segments=segments,
            language=language,
            text_source="youtube",
            word_count=word_count,
        )


# Module-level instance + eager registration. Importing this module
# registers the connector for `source_type="video"`.
_INSTANCE = YouTubeConnector()
registry.register(_INSTANCE)

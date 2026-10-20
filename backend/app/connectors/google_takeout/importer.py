"""Google Takeout (S-3.7.5, T-3.7.5.2): Keep notes and YouTube history from
one archive.

- **Keep** (``Takeout/Keep/*.json``): each note becomes a share, exactly as
  the Keep importer reads it (``google_keep.importer``).
- **YouTube watch history** (``…/YouTube and YouTube Music/history/
  watch-history.json``): each watched video becomes a ``watched_video``
  event. The Data API cannot return watch history at all, so this export is
  the only source. Ads and removed videos are left out.
- **YouTube search history** (``…/history/search-history.json``): each search
  becomes a ``searched_youtube`` event whose text is the query, the user's
  own words.

The history files can be tens of megabytes; they are read item by item.
Entries are recognised by their URLs, not by their localised titles
("Watched …" in English), so an archive in any language reads the same.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

from app.config import settings
from app.connectors.archive import (
    ExportUnreadable,
    ImportPreview,
    ImportSource,
    find_members,
    iter_json_array,
    parse_datetime,
    stable_id,
)
from app.connectors.base import ActivityEvent, ImportedShare
from app.connectors.google_keep import importer as keep

NAME = "google_takeout"
LABEL = "Google Takeout (Keep notes, YouTube history)"

_WATCH = re.compile(r"(^|/)YouTube[^/]*/history/watch-history\.json$", re.I)
_SEARCH = re.compile(r"(^|/)YouTube[^/]*/history/search-history\.json$", re.I)
_WATCHED_PREFIX = re.compile(r"^Watched\s+", re.I)


def _video_id(url: str) -> str | None:
    parts = urlsplit(url or "")
    if "youtube.com" in parts.netloc and parts.path == "/watch":
        return (parse_qs(parts.query).get("v") or [None])[0]
    if parts.netloc.endswith("youtu.be"):
        return parts.path.lstrip("/") or None
    return None


def _search_query(url: str) -> str | None:
    parts = urlsplit(url or "")
    if "youtube.com" in parts.netloc and parts.path == "/results":
        return (parse_qs(parts.query).get("search_query") or [None])[0]
    return None


def _is_ad(item: dict) -> bool:
    return any("ads" in str(d.get("name", "")).lower() for d in item.get("details") or [])


def watch_events(source: ImportSource, member: str, stats: dict[str, int]) -> Iterator[ActivityEvent]:
    with source.open_text(member) as stream:
        for item in iter_json_array(stream):
            if not isinstance(item, dict) or _is_ad(item):
                stats["ads_skipped"] = stats.get("ads_skipped", 0) + 1
                continue
            vid = _video_id(item.get("titleUrl", ""))
            when = parse_datetime(item.get("time"))
            if not vid or when is None:
                stats["removed_videos_skipped"] = stats.get("removed_videos_skipped", 0) + 1
                continue
            channel = (item.get("subtitles") or [{}])[0]
            title = _WATCHED_PREFIX.sub("", (item.get("title") or "").strip()) or vid
            yield ActivityEvent(
                external_id=f"yt-watch:{vid}:{when.isoformat()}",
                event_type="watched_video",
                occurred_at=when,
                payload={
                    "title": title,
                    "video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "channel": channel.get("name"),
                    "channel_url": channel.get("url"),
                    "product": (item.get("products") or ["YouTube"])[0],
                },
            )


def search_events(source: ImportSource, member: str, stats: dict[str, int]) -> Iterator[ActivityEvent]:
    with source.open_text(member) as stream:
        for item in iter_json_array(stream):
            if not isinstance(item, dict) or _is_ad(item):
                continue
            query = _search_query(item.get("titleUrl", ""))
            when = parse_datetime(item.get("time"))
            if not query or when is None:
                stats["searches_skipped"] = stats.get("searches_skipped", 0) + 1
                continue
            yield ActivityEvent(
                external_id=f"yt-search:{when.isoformat()}:{stable_id(query)}",
                event_type="searched_youtube",
                occurred_at=when,
                payload={"title": query, "query": query},
                # What the user typed: their own words.
                text_content=query,
            )


def sniff(source: ImportSource) -> bool:
    try:
        return source.is_zip and bool(
            keep._members(source) or find_members(source, _WATCH) or find_members(source, _SEARCH)
        )
    except Exception:
        return False


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    summary: dict[str, Any] = {"notes": 0, "watched": 0, "searches": 0}
    warnings: list[str] = []
    first: datetime | None = None
    last: datetime | None = None
    if keep._members(source):
        kp = keep.preview(source, options)
        summary["notes"] = kp.summary.get("notes", 0)
        summary["notes_trashed"] = kp.summary.get("trashed", 0)
        summary["labels"] = kp.summary.get("labels", {})
    stats: dict[str, int] = {}
    channels: dict[str, int] = {}
    for member in find_members(source, _WATCH):
        for ev in watch_events(source, member, stats):
            summary["watched"] += 1
            name = ev.payload.get("channel")
            if name:
                channels[name] = channels.get(name, 0) + 1
            first = min(first, ev.occurred_at) if first else ev.occurred_at
            last = max(last, ev.occurred_at) if last else ev.occurred_at
    for member in find_members(source, _SEARCH):
        for ev in search_events(source, member, stats):
            summary["searches"] += 1
            first = min(first, ev.occurred_at) if first else ev.occurred_at
            last = max(last, ev.occurred_at) if last else ev.occurred_at
    if not any((summary["notes"], summary["watched"], summary["searches"], summary.get("notes_trashed"))):
        raise ExportUnreadable("No Keep notes or YouTube history were found in this Takeout archive.")
    summary["top_channels"] = dict(sorted(channels.items(), key=lambda kv: -kv[1])[:10])
    summary["ads_skipped"] = stats.get("ads_skipped", 0)
    summary["first_at"] = first.isoformat() if first else None
    summary["last_at"] = last.isoformat() if last else None
    if source.is_zip and any(n.lower().endswith("watch-history.html") for n in source.member_names()) and not summary["watched"]:
        warnings.append(
            "Your YouTube history is in HTML. Export it again from Google Takeout with the "
            "format set to JSON (Multiple formats, history: JSON)."
        )
    return ImportPreview(
        importer=NAME,
        label=LABEL,
        summary=summary,
        options={"include_keep": True, "include_youtube": True, "own_words": True, "include_trashed": False},
        warnings=warnings,
    )


def parse_source(source: ImportSource, options: dict[str, Any], stats: dict[str, int]):
    if options.get("include_keep", True) is not False and keep._members(source):
        yield from keep.parse_source(source, options, stats)
    if options.get("include_youtube", True) is not False:
        for member in find_members(source, _WATCH):
            yield from watch_events(source, member, stats)
        for member in find_members(source, _SEARCH):
            yield from search_events(source, member, stats)


class GoogleTakeoutImporter:
    name = NAME
    display_name = LABEL
    privacy_weight = "high"
    consent_disclosure = (
        "Reads a Google Takeout archive you downloaded. Keep notes become shares in "
        "your words; YouTube watch history becomes a record of what you watched, and "
        "your YouTube searches a record of what you looked for. Ads are left out. "
        "The archive itself is not kept."
    )

    def accepts(self, filename: str) -> bool:
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return base.startswith("takeout") and base.endswith(".zip")

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(self, stream, *, tenant_id: str, options: dict[str, Any] | None = None,
              filename: str = "takeout.zip", stats: dict[str, int] | None = None) -> Iterator[ActivityEvent | ImportedShare]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        yield from parse_source(source, dict(options or {}), stats if stats is not None else {})


IMPORTER = GoogleTakeoutImporter()

"""Spotify streaming history (S-3.7.5, T-3.7.5.3).

Two exports, both from Spotify's privacy page:

- **Extended streaming history** (``Streaming_History_Audio_*.json``, older
  ``endsong_*.json``): every play since the account began, with ``ts``,
  ``ms_played``, track / episode / audiobook names and URIs, ``skipped``,
  ``reason_end``. The complete source; the Web API's recently-played is a
  50-item window, and since 2026-02 the API is closed to small apps.
- **Account data** (``StreamingHistory_music_*.json``): the last year,
  ``endTime``, ``artistName``, ``trackName``, ``msPlayed``.

Each play is a ``played_track`` / ``played_episode`` / ``played_audiobook``
event. Plays in a private session (``incognito_mode``) are not imported: the
user chose not to be recorded. The IP address and country fields are never
stored.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

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
from app.connectors.base import ActivityEvent

NAME = "spotify_export"
LABEL = "Spotify listening history"

_EXTENDED = re.compile(r"(^|/)(Streaming_History_(Audio|Video)_[^/]*|endsong_\d+)\.json$", re.I)
_ACCOUNT = re.compile(r"(^|/)StreamingHistory[^/]*\.json$", re.I)


def _members(source: ImportSource) -> list[str]:
    if source.is_zip:
        return find_members(source, _EXTENDED) + find_members(source, _ACCOUNT)
    return [None]  # type: ignore[list-item]


def _event(item: dict, stats: dict[str, int]) -> ActivityEvent | None:
    if item.get("incognito_mode"):
        stats["private_session_skipped"] = stats.get("private_session_skipped", 0) + 1
        return None
    if "ts" in item:  # extended history
        when = parse_datetime(item.get("ts"))
        ms = int(item.get("ms_played") or 0)
        track = item.get("master_metadata_track_name")
        episode = item.get("episode_name")
        book = item.get("audiobook_title")
        if track:
            kind, title, by = "played_track", track, item.get("master_metadata_album_artist_name")
            uri = item.get("spotify_track_uri")
            extra = {"album": item.get("master_metadata_album_album_name")}
        elif episode:
            kind, title, by = "played_episode", episode, item.get("episode_show_name")
            uri = item.get("spotify_episode_uri")
            extra = {}
        elif book:
            kind, title, by = "played_audiobook", item.get("audiobook_chapter_title") or book, book
            uri = item.get("audiobook_uri")
            extra = {}
        else:
            stats["unknown_skipped"] = stats.get("unknown_skipped", 0) + 1
            return None
        extra.update({
            "skipped": bool(item.get("skipped")),
            "reason_end": item.get("reason_end"),
            "shuffle": bool(item.get("shuffle")),
        })
    elif "endTime" in item:  # account data, last year
        when = parse_datetime(item.get("endTime"), ("%Y-%m-%d %H:%M",))
        ms = int(item.get("msPlayed") or 0)
        title, by = item.get("trackName"), item.get("artistName")
        if not title:
            return None
        kind, uri, extra = "played_track", None, {}
    else:
        return None
    if when is None:
        stats["undated_skipped"] = stats.get("undated_skipped", 0) + 1
        return None
    return ActivityEvent(
        external_id=f"{when.isoformat()}|{uri or stable_id(title, by)}",
        event_type=kind,
        occurred_at=when,
        payload={
            "title": f"{title} — {by}" if by else title,
            "name": title,
            "by": by,
            "uri": uri,
            "ms_played": ms,
            **extra,
        },
    )


def events(source: ImportSource, stats: dict[str, int]) -> Iterator[ActivityEvent]:
    for member in _members(source):
        with source.open_text(member) as stream:
            for item in iter_json_array(stream):
                if isinstance(item, dict):
                    ev = _event(item, stats)
                    if ev is not None:
                        yield ev


def sniff(source: ImportSource) -> bool:
    try:
        if source.is_zip:
            return bool(_members(source))
        if not source.filename.lower().endswith(".json"):
            return False
        head = source.head(8192).decode("utf-8", "replace")
        return ("ms_played" in head and "ts" in head) or ("msPlayed" in head and "endTime" in head)
    except Exception:
        return False


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    stats: dict[str, int] = {}
    counts = {"plays": 0, "tracks": 0, "episodes": 0, "audiobooks": 0, "skipped_by_you": 0}
    artists: dict[str, int] = {}
    hours = 0.0
    first = last = None
    for ev in events(source, stats):
        counts["plays"] += 1
        counts[{"played_track": "tracks", "played_episode": "episodes", "played_audiobook": "audiobooks"}[ev.event_type]] += 1
        counts["skipped_by_you"] += bool(ev.payload.get("skipped"))
        hours += ev.payload.get("ms_played", 0) / 3_600_000
        by = ev.payload.get("by")
        if by and ev.event_type == "played_track":
            artists[by] = artists.get(by, 0) + 1
        first = min(first, ev.occurred_at) if first else ev.occurred_at
        last = max(last, ev.occurred_at) if last else ev.occurred_at
    if not counts["plays"] and not stats.get("private_session_skipped"):
        raise ExportUnreadable("No plays were found in this Spotify export.")
    return ImportPreview(
        importer=NAME,
        label=LABEL,
        summary={
            **counts,
            "hours": round(hours, 1),
            "private_session_skipped": stats.get("private_session_skipped", 0),
            "top_artists": dict(sorted(artists.items(), key=lambda kv: -kv[1])[:10]),
            "first_at": first.isoformat() if first else None,
            "last_at": last.isoformat() if last else None,
        },
        options={},
        warnings=[],
    )


class SpotifyExportImporter:
    name = NAME
    display_name = LABEL
    privacy_weight = "medium"
    consent_disclosure = (
        "Reads the listening history you downloaded from Spotify: what you played, "
        "when, for how long, and whether you skipped it. Plays from private sessions "
        "are left out, and the IP address and country in the file are never stored."
    )

    def accepts(self, filename: str) -> bool:
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return (
            base in ("my_spotify_data.zip", "my_spotify_data (1).zip")
            or bool(_EXTENDED.search(base))
            or bool(_ACCOUNT.search(base))
        )

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(self, stream, *, tenant_id: str, options: dict[str, Any] | None = None,
              filename: str = "Streaming_History_Audio.json", stats: dict[str, int] | None = None) -> Iterator[ActivityEvent]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        yield from events(source, stats if stats is not None else {})


IMPORTER = SpotifyExportImporter()

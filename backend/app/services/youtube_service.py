import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NamedTuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import TranscriptList, YouTubeTranscriptApi

from app.config import settings
from app.database import SessionLocal
from app.models.transcript_cache import TranscriptCache
from app.services import quota_service
from app.services.quota_service import QuotaExceededError
from app.utils.rate_limiter import RateLimiter
from app.utils.youtube_helpers import parse_iso8601_duration

logger = logging.getLogger(__name__)

transcript_limiter = RateLimiter(
    rate=settings.YOUTUBE_TRANSCRIPT_RATE_LIMIT,
    jitter=settings.YOUTUBE_TRANSCRIPT_RATE_JITTER,
)

# OpenAI Whisper API enforces a 25 MB upload limit per file.
WHISPER_MAX_FILE_BYTES = 25 * 1024 * 1024


class _TranscriptCircuitBreaker:
    """Shared breaker for YouTube transcript-API IP blocks (S-1.11.1 / D-051).

    After ``threshold`` consecutive block signals the breaker opens for a
    cooldown that doubles on every re-trip (base → max). Callers consult
    ``wait_if_open()`` before a fetch: when the remaining cooldown is at
    most ``max_wait`` it sleeps the block off and allows a probe attempt;
    longer remainders return False so the caller can fall to Whisper
    without stalling a single video for many minutes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consecutive_blocks = 0
        self._open_until = 0.0
        self._current_cooldown = 0.0

    def record_block(self) -> None:
        with self._lock:
            self._consecutive_blocks += 1
            if self._consecutive_blocks >= settings.TRANSCRIPT_BREAKER_THRESHOLD:
                if self._current_cooldown <= 0:
                    self._current_cooldown = settings.TRANSCRIPT_BREAKER_COOLDOWN_BASE
                else:
                    self._current_cooldown = min(
                        self._current_cooldown * 2,
                        settings.TRANSCRIPT_BREAKER_COOLDOWN_MAX,
                    )
                self._open_until = time.monotonic() + self._current_cooldown
                logger.warning(
                    "Transcript circuit breaker OPEN: %d consecutive IP-block "
                    "signals; cooling down %.0fs before the next transcript attempt",
                    self._consecutive_blocks,
                    self._current_cooldown,
                )

    def record_success(self) -> None:
        with self._lock:
            if self._consecutive_blocks:
                logger.info(
                    "Transcript circuit breaker reset after successful fetch"
                )
            self._consecutive_blocks = 0
            self._open_until = 0.0
            self._current_cooldown = 0.0

    def wait_if_open(self, tag: str = "") -> bool:
        """Return True when the caller may attempt a transcript fetch.

        Sleeps out short remaining cooldowns (≤ ``TRANSCRIPT_BREAKER_MAX_WAIT``);
        returns False when the wait would be longer, so the caller skips the
        transcript path for this video.
        """
        with self._lock:
            remaining = self._open_until - time.monotonic()
        if remaining <= 0:
            return True
        if remaining > settings.TRANSCRIPT_BREAKER_MAX_WAIT:
            logger.warning(
                f"{tag} Transcript breaker open for another {remaining:.0f}s "
                f"(> max wait {settings.TRANSCRIPT_BREAKER_MAX_WAIT:.0f}s); "
                "skipping transcript attempt for this video"
            )
            return False
        logger.info(
            f"{tag} Transcript breaker open; waiting {remaining:.0f}s "
            "before probing the transcript API again..."
        )
        time.sleep(remaining)
        return True


transcript_breaker = _TranscriptCircuitBreaker()

# Length (in seconds) of each synthesized pseudo-segment when Whisper
# returns only a text blob without per-segment timestamps.
WHISPER_PSEUDO_SEGMENT_SECONDS = 30.0

# Retry configuration for 5xx responses from the YouTube Data API.
_YT_RETRY_DELAYS = (1, 2, 4)


def get_youtube_client():
    return build("youtube", "v3", developerKey=settings.YOUTUBE_API_KEY)


def _is_quota_error(err: HttpError) -> bool:
    """Identify a 403 quota-exceeded response."""
    if err.resp.status != 403:
        return False
    body = (err.content or b"").decode("utf-8", errors="ignore").lower()
    return "quotaexceeded" in body or "dailylimitexceeded" in body or "quota" in body


def _execute_youtube_request(request, operation: str):
    """Execute a YouTube Data API request with retries, quota tracking, and error translation.

    - Retries 5xx responses with exponential backoff.
    - Translates 403 quota errors into ``QuotaExceededError``.
    - Records a quota-log row for every request that is actually issued.
    """
    last_error: HttpError | None = None
    for attempt, delay in enumerate((0, *_YT_RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            response = request.execute()
        except HttpError as err:
            last_error = err
            status = err.resp.status
            if _is_quota_error(err):
                logger.error("YouTube API quota exceeded on operation=%s: %s", operation, err)
                # Still record the attempt so the daily counter reflects reality.
                quota_service.record(operation)
                raise QuotaExceededError(
                    f"YouTube API daily quota exceeded during '{operation}' call."
                ) from err
            if 500 <= status < 600 and attempt < len(_YT_RETRY_DELAYS):
                logger.warning(
                    "YouTube API %s returned %s, retrying (attempt %s/%s)...",
                    operation, status, attempt + 1, len(_YT_RETRY_DELAYS),
                )
                continue
            logger.error("YouTube API %s failed with HttpError %s: %s", operation, status, err)
            raise
        else:
            quota_service.record(operation)
            return response

    # Exhausted retries on 5xx.
    assert last_error is not None
    raise last_error


def search_videos(
    query: str,
    max_results: int = 10,
    published_after: str | None = None,
    video_duration: str | None = None,
    channel_type: str | None = None,
) -> list[dict]:
    """
    Search YouTube for videos matching a query.

    Args:
        query: Search query string.
        max_results: Max results to return (costs 100 quota units per call).
        published_after: ISO 8601 datetime string.
        video_duration: "short" (<4min), "medium" (4-20min), "long" (>20min).
        channel_type: YouTube search `channelType` filter, e.g. "any" or "show".

    Returns:
        List of video dicts with basic metadata.
    """
    logger.info(
        f"search_videos: query={query!r}, max_results={max_results}, "
        f"published_after={published_after}, video_duration={video_duration}, "
        f"channel_type={channel_type}"
    )
    youtube = get_youtube_client()

    params = {
        "q": query,
        "part": "snippet",
        "type": "video",
        "maxResults": min(max_results, 50),
        "order": "relevance",
    }
    if published_after:
        params["publishedAfter"] = published_after
    if video_duration:
        params["videoDuration"] = video_duration
    if channel_type:
        params["channelType"] = channel_type

    # S-1.11.5: paginate up to YOUTUBE_SEARCH_MAX_PAGES (each page costs
    # 100 quota units) so targets above 50 aren't silently starved by the
    # single-page cap.
    max_pages = max(1, settings.YOUTUBE_SEARCH_MAX_PAGES)
    videos: list[dict] = []
    page_token: str | None = None
    for page in range(max_pages):
        if page_token:
            params["pageToken"] = page_token
        response = _execute_youtube_request(youtube.search().list(**params), "search")
        for item in response.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "video_id": item["id"]["videoId"],
                "title": snippet["title"],
                "channel_name": snippet["channelTitle"],
                "channel_id": snippet["channelId"],
                "published_at": snippet.get("publishedAt"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
            })
        page_token = response.get("nextPageToken")
        if len(videos) >= max_results or not page_token:
            break

    videos = videos[:max_results]
    logger.info(
        f"search_videos: returned {len(videos)} results for query={query!r} "
        f"({page + 1} page(s))"
    )
    return videos


def get_video_details(video_ids: list[str], job_id: str = "") -> dict[str, dict]:
    """
    Fetch detailed metadata for videos (duration, etc.).
    Costs 1 quota unit per call (up to 50 IDs per call).
    """
    tag = f"[job:{job_id}]" if job_id else ""
    total = len(video_ids)
    logger.info(f"{tag} get_video_details: fetching details for {total} video(s)")
    youtube = get_youtube_client()
    details = {}

    # Process in batches of 50
    for i in range(0, total, 50):
        batch = video_ids[i:i + 50]
        batch_num = i // 50 + 1
        total_batches = (total + 49) // 50
        logger.info(f"{tag} get_video_details: batch {batch_num}/{total_batches} ({len(batch)} IDs)")
        response = _execute_youtube_request(
            youtube.videos().list(
                part="contentDetails,snippet,statistics",
                id=",".join(batch),
            ),
            "videos",
        )

        for item in response.get("items", []):
            vid = item["id"]
            content = item.get("contentDetails", {})
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            details[vid] = {
                "video_id": vid,
                "title": snippet.get("title", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "duration_seconds": parse_iso8601_duration(content.get("duration", "PT0S")),
                "published_at": snippet.get("publishedAt"),
                # S-3.7.2: Echo shares of a YouTube link keep the description.
                "description": snippet.get("description", ""),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "view_count": _safe_int(stats.get("viewCount")),
                "like_count": _safe_int(stats.get("likeCount")),
            }

    logger.info(f"{tag} get_video_details: resolved {len(details)}/{total} video(s)")
    return details


def get_default_audio_languages(video_ids: list[str], job_id: str = "") -> dict[str, str | None]:
    """``snippet.defaultAudioLanguage`` per video — the language the uploader
    says the video is spoken in (S-1.11.11).

    1 quota unit per 50 ids (``videos.list``). Never ``captions.list``, which
    costs 50 units per video. ``snippet.defaultLanguage`` is deliberately not
    used: it is the language of the title and description, and on
    ``v6CuYULP3tM`` it reads ``en`` for a Hindi-spoken video. Ids the API does
    not return, and videos without the field, map to None.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    out: dict[str, str | None] = {vid: None for vid in video_ids}
    if not video_ids:
        return out
    youtube = get_youtube_client()
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        response = _execute_youtube_request(
            youtube.videos().list(
                part="snippet",
                id=",".join(batch),
                fields="items(id,snippet(defaultAudioLanguage))",
            ),
            "videos",
        )
        for item in response.get("items", []):
            out[item["id"]] = (item.get("snippet") or {}).get("defaultAudioLanguage") or None
    logger.info(
        f"{tag} get_default_audio_languages: {sum(1 for v in out.values() if v)}"
        f"/{len(video_ids)} video(s) declare an audio language"
    )
    return out


def _safe_int(value) -> int | None:
    """Parse a string/int statistic to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_channel_subscribers(channel_ids: list[str], job_id: str = "") -> dict[str, int | None]:
    """
    Fetch subscriber counts for a batch of channels.
    Costs 1 quota unit per channels.list call (up to 50 IDs per call).

    Returns a mapping of channel_id -> subscriber count (or None if hidden/unavailable).
    """
    tag = f"[job:{job_id}]" if job_id else ""
    unique_ids = [cid for cid in dict.fromkeys(channel_ids) if cid]
    if not unique_ids:
        return {}

    logger.info(f"{tag} get_channel_subscribers: fetching for {len(unique_ids)} channel(s)")
    youtube = get_youtube_client()
    subs: dict[str, int | None] = {}

    for i in range(0, len(unique_ids), 50):
        batch = unique_ids[i:i + 50]
        response = youtube.channels().list(
            part="statistics",
            id=",".join(batch),
        ).execute()
        for item in response.get("items", []):
            cid = item.get("id")
            stats = item.get("statistics", {})
            if stats.get("hiddenSubscriberCount"):
                subs[cid] = None
            else:
                subs[cid] = _safe_int(stats.get("subscriberCount"))

    for cid in unique_ids:
        subs.setdefault(cid, None)

    logger.info(f"{tag} get_channel_subscribers: resolved {len(subs)} channel(s)")
    return subs


def get_channel_videos(
    channel_id: str,
    max_results: int = 10,
    job_id: str = "",
) -> list[dict]:
    """
    Fetch videos from a channel's uploads playlist.
    Costs 1 quota unit per playlistItems.list call (vs 100 for search).
    """
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} get_channel_videos: channel_id={channel_id}, max_results={max_results}")
    youtube = get_youtube_client()

    # Get the uploads playlist ID from channel
    channel_response = _execute_youtube_request(
        youtube.channels().list(
            part="contentDetails",
            id=channel_id,
        ),
        "channels",
    )

    items = channel_response.get("items", [])
    if not items:
        logger.warning(f"{tag} get_channel_videos: channel {channel_id} not found or has no content")
        return []

    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    logger.info(f"{tag} get_channel_videos: uploads playlist={uploads_playlist_id}")

    # Fetch videos from uploads playlist
    video_ids = []
    next_page_token = None
    page = 0

    while len(video_ids) < max_results:
        page += 1
        playlist_response = _execute_youtube_request(
            youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=min(50, max_results - len(video_ids)),
                pageToken=next_page_token,
            ),
            "playlistItems",
        )

        page_items = playlist_response.get("items", [])
        for item in page_items:
            video_ids.append(item["contentDetails"]["videoId"])

        logger.info(
            f"{tag} get_channel_videos: page {page} fetched {len(page_items)} items "
            f"(total so far: {len(video_ids)})"
        )

        next_page_token = playlist_response.get("nextPageToken")
        if not next_page_token:
            break

    logger.info(f"{tag} get_channel_videos: done — {len(video_ids)} video IDs from channel {channel_id}")
    return video_ids


def get_channel_videos_all(
    channel_id: str,
    job_id: str = "",
    uploads_playlist_id: str | None = None,
) -> list[str]:
    """Walk every page of a channel's uploads playlist and return all video IDs.

    Unlike ``get_channel_videos`` this imposes no cap — it paginates via
    ``nextPageToken`` until exhausted. Costs 1 quota unit per 50 items
    (each ``playlistItems.list`` page).

    Args:
        channel_id: Canonical YouTube channel ID (``UC...``).
        job_id: Optional job tag for log correlation.
        uploads_playlist_id: Pre-resolved uploads playlist ID. Providing it
            skips an extra ``channels.list`` round trip (1 quota unit).

    Returns:
        List of YouTube video IDs in the channel's uploads playlist.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} get_channel_videos_all: channel_id={channel_id}")
    youtube = get_youtube_client()

    if not uploads_playlist_id:
        channel_response = _execute_youtube_request(
            youtube.channels().list(part="contentDetails", id=channel_id),
            "channels",
        )
        items = channel_response.get("items", [])
        if not items:
            logger.warning(
                f"{tag} get_channel_videos_all: channel {channel_id} not found or has no content"
            )
            return []
        uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    logger.info(f"{tag} get_channel_videos_all: uploads playlist={uploads_playlist_id}")

    video_ids: list[str] = []
    next_page_token: str | None = None
    page = 0

    while True:
        page += 1
        playlist_response = _execute_youtube_request(
            youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token,
            ),
            "playlistItems",
        )

        page_items = playlist_response.get("items", [])
        for item in page_items:
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)

        logger.info(
            f"{tag} get_channel_videos_all: page {page} fetched {len(page_items)} items "
            f"(total so far: {len(video_ids)})"
        )

        next_page_token = playlist_response.get("nextPageToken")
        if not next_page_token:
            break

    logger.info(
        f"{tag} get_channel_videos_all: done — {len(video_ids)} video IDs from channel {channel_id}"
    )
    return video_ids


def get_channel_metadata(channel_id: str, job_id: str = "") -> dict | None:
    """Fetch channel name, uploads playlist ID, and subscriber count.

    Costs 1 quota unit (``channels.list``). Returns ``None`` when the channel
    cannot be resolved.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} get_channel_metadata: channel_id={channel_id}")
    youtube = get_youtube_client()
    response = _execute_youtube_request(
        youtube.channels().list(
            part="snippet,contentDetails,statistics",
            id=channel_id,
        ),
        "channels",
    )
    items = response.get("items", [])
    if not items:
        return None
    item = items[0]
    snippet = item.get("snippet", {})
    content = item.get("contentDetails", {})
    stats = item.get("statistics", {})
    subs: int | None = None
    if not stats.get("hiddenSubscriberCount"):
        subs = _safe_int(stats.get("subscriberCount"))
    return {
        "channel_id": item.get("id", channel_id),
        "name": snippet.get("title", ""),
        "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads"),
        "subscriber_count": subs,
    }


def resolve_channel_id(channel_input: str, job_id: str = "") -> str | None:
    """
    Resolve a channel URL, handle, or name to a channel ID.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} resolve_channel_id: input={channel_input!r}")
    youtube = get_youtube_client()

    # Direct channel ID
    if channel_input.startswith("UC") and len(channel_input) == 24:
        logger.info(f"{tag} resolve_channel_id: direct channel ID detected → {channel_input}")
        return channel_input

    # Channel URL with /channel/UCxxxx
    if "/channel/" in channel_input:
        parts = channel_input.split("/channel/")
        if len(parts) > 1:
            cid = parts[1].split("/")[0].split("?")[0]
            if cid.startswith("UC"):
                logger.info(f"{tag} resolve_channel_id: extracted from URL → {cid}")
                return cid

    # Handle (@username) or URL with /@handle
    handle = None
    if "/@" in channel_input:
        handle = channel_input.split("/@")[1].split("/")[0].split("?")[0]
    elif channel_input.startswith("@"):
        handle = channel_input[1:]

    if handle:
        logger.info(f"{tag} resolve_channel_id: resolving handle @{handle} via API")
        response = _execute_youtube_request(
            youtube.channels().list(
                part="id",
                forHandle=handle,
            ),
            "channels",
        )
        items = response.get("items", [])
        if items:
            channel_id = items[0]["id"]
            logger.info(f"{tag} resolve_channel_id: @{handle} → {channel_id}")
            return channel_id
        logger.warning(f"{tag} resolve_channel_id: handle @{handle} not found via API")

    # Fall back to search (costs 100 units)
    logger.info(f"{tag} resolve_channel_id: falling back to search for {channel_input!r} (costs 100 quota units)")
    response = _execute_youtube_request(
        youtube.search().list(
            q=channel_input,
            part="snippet",
            type="channel",
            maxResults=1,
        ),
        "search",
    )
    items = response.get("items", [])
    if items:
        channel_id = items[0]["snippet"]["channelId"]
        logger.info(f"{tag} resolve_channel_id: search fallback → {channel_id}")
        return channel_id

    logger.warning(f"{tag} resolve_channel_id: could not resolve {channel_input!r}")
    return None


# ---------------------------------------------------------------------------
# Caption-track choice (S-1.11.11)
#
# Before this, `_fetch_transcript_once` asked for `en` / `en-auto` and then
# took the FIRST listed track. On videos YouTube has auto-dubbed, the list
# carries one ASR track per dubbed audio track, so a Hindi lecture arrived as
# its Bengali dub (`1v3_AQ26jZ0`, `5AuuOZ4vuxI`) or its English one
# (`v6CuYULP3tM`): fluent text no detector downstream can flag, and every
# quote from it words the speaker never said. Measured on 37 Hindi, Hinglish
# and Kannada library videos in docs/notes/2026-10-25-caption-track-choice.md.
# ---------------------------------------------------------------------------

# Sentinel: the caller did not look the default audio language up.
AUDIO_LANGUAGE_UNSET: Any = object()

# The player response names each audio track "<language>.<n>". On all 12
# multi-audio videos measured, exactly one track ended ".4" — always the
# default track — and every other one ".10" (the auto-dubs).
_ORIGINAL_AUDIO_TRACK_SUFFIX = "4"

# YouTube still serves a few retired ISO 639 codes (`iw` for Hebrew).
_LANGUAGE_ALIASES = {"iw": "he", "in": "id", "ji": "yi", "jw": "jv"}


def primary_language(code: str | None) -> str | None:
    """The primary subtag of a BCP-47 code, lower-cased: ``en-US`` -> ``en``."""
    if not code:
        return None
    primary = str(code).strip().replace("_", "-").split("-")[0].lower()
    return _LANGUAGE_ALIASES.get(primary, primary) or None


@dataclass(frozen=True)
class AudioTracks:
    """A multi-audio video's audio tracks, read from the player response."""

    original: str  # language code of the original audio, e.g. "hi"
    # Exact, lower-cased codes of the other (dubbed) audio tracks: "en-us".
    dubbed: frozenset[str] = field(default_factory=frozenset)


def audio_tracks_from_captions(captions_json: dict) -> AudioTracks | None:
    """The original and dubbed audio languages, or None for a video with a
    single audio track (nothing dubbed) or one whose original is unclear."""
    entries = [
        (i, (t or {}).get("audioTrackId"))
        for i, t in enumerate(captions_json.get("audioTracks") or [])
    ]
    ids = [(i, tid) for i, tid in entries if tid]
    if len(ids) < 2:
        return None
    originals = [tid for _, tid in ids if tid.rsplit(".", 1)[-1] == _ORIGINAL_AUDIO_TRACK_SUFFIX]
    original = originals[0] if len(originals) == 1 else None
    if original is None:
        default_index = captions_json.get("defaultAudioTrackIndex")
        original = next((tid for i, tid in ids if i == default_index), None)
    if original is None:
        return None
    original_lang = original.rsplit(".", 1)[0]
    # A dub's ASR caption track carries the dub's code EXACTLY (`en-US.10`
    # -> `en-US`, `bn.10` -> `bn`, all 20 dubs of `8Hdx8IGL1sc`), while the
    # original audio's ASR track carries the language the recogniser heard,
    # usually bare (`en-US.4` -> `en`). Matching on the primary subtag would
    # drop `IcVYyF3EEbk`'s only real track (`en`) because of its `en-US` dub.
    dubbed = frozenset(
        code
        for _, tid in ids
        if tid != original
        and (code := tid.rsplit(".", 1)[0].lower())
        and code != original_lang.lower()
    )
    return AudioTracks(original=original_lang, dubbed=dubbed)


def _is_dub_track(track, dubbed: frozenset[str]) -> bool:
    """An ASR caption track in exactly a dubbed audio track's language."""
    return bool(track.is_generated) and (track.language_code or "").lower() in dubbed


def _best_track(tracks: list, language: str | None):
    """Manual before ASR; then the exact code, the bare code, a regional one."""
    wanted = (language or "").lower()

    def rank(item):
        index, t = item
        code = (t.language_code or "").lower()
        closeness = 0 if code == wanted else 1 if "-" not in code else 2
        return (1 if t.is_generated else 0, closeness, index)

    return min(enumerate(tracks), key=rank)[1]


def choose_caption_track(
    tracks: list,
    *,
    spoken_language: str | None,
    dubbed: frozenset[str] = frozenset(),
    preferred_language: str = "en",
) -> tuple[Any, str, tuple[str, ...]]:
    """Pick the caption track to ingest. Pure: no network.

    1. Drop auto-dubbed tracks: an ASR track in a language the video was
       dubbed into is the dub's transcript, never the speaker's words.
    2. A track in the spoken language: manual first, then the ASR track.
    3. Only when the spoken language is unknown or has no track, the old
       English-first fallback (``preferred_language``, then ``en``), then the
       remaining ASR track (the original audio's), then whatever is left.

    Translated tracks (``tlang``) are never requested, so never chosen.

    Returns ``(track, match, skipped_dubbed)``; ``track`` is None with match
    ``only_dubbed`` when every track is a dub and ``none`` when there are no
    tracks at all.
    """
    usable, skipped = [], []
    for t in tracks:
        (skipped if _is_dub_track(t, dubbed) else usable).append(t)
    skipped_codes = tuple(t.language_code for t in skipped)
    if not usable:
        return None, ("only_dubbed" if skipped else "none"), skipped_codes

    spoken = primary_language(spoken_language)
    if spoken:
        pool = [t for t in usable if primary_language(t.language_code) == spoken]
        if pool:
            return _best_track(pool, spoken_language), "spoken", skipped_codes

    for lang in dict.fromkeys([preferred_language, "en"]):
        pool = [t for t in usable if primary_language(t.language_code) == primary_language(lang)]
        if pool:
            return _best_track(pool, lang), "fallback_english_first", skipped_codes
    asr = [t for t in usable if t.is_generated]
    if asr:
        return asr[0], "fallback_original_asr", skipped_codes
    return usable[0], "fallback_first_listed", skipped_codes


@dataclass
class TrackChoice:
    """The outcome of ``plan_caption_track``: the track and why."""

    track: Any  # youtube_transcript_api Transcript, or None
    match: str
    spoken_language: str | None
    spoken_language_source: str | None  # "data_api" | "player"
    skipped_dubbed: tuple[str, ...] = ()
    available: tuple[str, ...] = ()

    @property
    def language(self) -> str | None:
        return getattr(self.track, "language_code", None)

    @property
    def kind(self) -> str | None:
        if self.track is None:
            return None
        return "asr" if self.track.is_generated else "manual"

    def as_metadata(self) -> dict:
        meta = {
            "language": self.language,
            "kind": self.kind,
            "match": self.match,
            "spoken_language": self.spoken_language,
            "spoken_language_source": self.spoken_language_source,
        }
        if self.skipped_dubbed:
            meta["skipped_dubbed"] = list(self.skipped_dubbed)
        return meta


class _NoSpokenTrackError(RuntimeError):
    """Every caption track is an auto-dub: definitive, so not retried."""


def _list_caption_tracks(ytt_api, video_id: str) -> tuple[Any, AudioTracks | None]:
    """The transcript list plus the player's audio tracks.

    ``youtube-transcript-api`` parses the player response but keeps only the
    caption tracks; the audio tracks that tell an original from a dub are in
    the same JSON. Read it through the library's fetcher and build the list
    with its public ``TranscriptList.build`` — the same request ``list()``
    makes, so no extra traffic. If a future release moves those internals,
    fall back to ``list()`` without audio tracks (pinned by a test).
    """
    fetcher = getattr(ytt_api, "_fetcher", None)
    fetch_json = getattr(fetcher, "_fetch_captions_json", None)
    http_client = getattr(fetcher, "_http_client", None)
    if callable(fetch_json) and http_client is not None:
        captions_json = fetch_json(video_id)
        return (
            TranscriptList.build(http_client, video_id, captions_json),
            audio_tracks_from_captions(captions_json),
        )
    logger.warning(
        "youtube-transcript-api internals changed; caption-track choice runs "
        "without audio tracks, so auto-dubs cannot be told apart (S-1.11.11)"
    )
    return ytt_api.list(video_id), None


def _lookup_default_audio_language(video_id: str, tag: str) -> str | None:
    """Fail-soft single-video ``defaultAudioLanguage`` (1 quota unit)."""
    try:
        return get_default_audio_languages([video_id]).get(video_id)
    except Exception as exc:  # noqa: BLE001 — quota, key or network: fall back
        logger.warning(
            f"{tag} defaultAudioLanguage lookup failed for {video_id} "
            f"({type(exc).__name__}); choosing the caption track without it"
        )
        return None


def plan_caption_track(
    ytt_api,
    video_id: str,
    *,
    language: str = "en",
    audio_language: Any = AUDIO_LANGUAGE_UNSET,
    tag: str = "",
) -> TrackChoice:
    """List a video's caption tracks and choose the one to ingest.

    Dubs are recognised from the player's audio tracks (free; the only
    source that has them). The spoken language is, in order:

    1. ``defaultAudioLanguage`` — passed by a caller that looked it up in a
       batch, or looked up here (1 unit), but only when the non-dub tracks
       span more than one language: with one language the choice cannot
       change, so the unit would be wasted (35 of 37 measured videos);
    2. the player's original audio track, on a multi-audio video (present
       even when the uploader declared nothing — ``v6CuYULP3tM``).

    Network errors propagate (the caller classifies IP blocks).
    """
    transcript_list, audio = _list_caption_tracks(ytt_api, video_id)
    tracks = list(transcript_list)
    dubbed = audio.dubbed if audio is not None else frozenset()

    spoken, source = None, None
    if audio_language is not AUDIO_LANGUAGE_UNSET:
        spoken = audio_language or None
    else:
        offered = {
            primary_language(t.language_code) for t in tracks if not _is_dub_track(t, dubbed)
        }
        if len(offered) > 1:
            spoken = _lookup_default_audio_language(video_id, tag)
    if spoken:
        source = "data_api"
    elif audio is not None:
        spoken, source = audio.original, "player"

    track, match, skipped = choose_caption_track(
        tracks, spoken_language=spoken, dubbed=dubbed, preferred_language=language
    )
    return TrackChoice(
        track=track,
        match=match,
        spoken_language=spoken,
        spoken_language_source=source,
        skipped_dubbed=skipped,
        available=tuple(
            f"{t.language_code}({'auto' if t.is_generated else 'manual'})" for t in tracks
        ),
    )


class TranscriptResult(NamedTuple):
    """What ``fetch_transcript`` returns.

    The first three fields keep the historical ``(segments, language,
    source)`` order. ``track`` (S-1.11.11) describes the caption track that
    was chosen — ``TrackChoice.as_metadata()`` — and is None for cache hits
    and Whisper transcriptions, which carry no track.
    """

    segments: list[dict]
    language: str
    source: str
    track: dict | None = None


def fetch_transcript(
    video_id: str,
    language: str = "en",
    job_id: str = "",
    allow_whisper: bool = True,
    audio_language: Any = AUDIO_LANGUAGE_UNSET,
) -> TranscriptResult | None:
    """
    Fetch transcript with caching, retry, circuit breaker, and Whisper fallback.

    Lookup order:
    1. transcript_cache DB table — cache hit returns immediately.
    2. YouTube Transcript API up to 3 times with exponential backoff (2s, 4s, 8s),
       gated by the shared IP-block circuit breaker (S-1.11.1 / D-051). The
       caption track is the one in the video's SPOKEN language, never an
       auto-dub (S-1.11.11, ``plan_caption_track``).
    3. Download audio via yt-dlp and transcribe via OpenAI Whisper API
       (segmented when >25 MB — S-1.11.2), unless ``allow_whisper`` is False
       (per-job Whisper budget exhausted — S-1.11.7).

    Args:
        language: the fallback language (English-first) used only when the
            spoken language is unknown or has no caption track.
        audio_language: the video's ``defaultAudioLanguage`` when the caller
            already looked it up (batched, 1 unit per 50 ids); None means it
            looked and the video declares none. Omitted, it is looked up
            here, and only when the caption tracks span more than one
            language (1 unit).

    Returns:
        ``TranscriptResult(segments, actual_language, source, track)`` on
        success, or None. `segments` is a list of {text, start, duration}
        dicts. `actual_language` is the BCP-47 code, or "unknown" for
        Whisper. `source` is "youtube" or "whisper" (S-1.11.4 provenance).
        `track` is the chosen caption track's metadata (YouTube fetches only).
    """
    retry_delays = [2, 4, 8]
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} fetch_transcript: video_id={video_id}, language={language}")

    cached = _load_from_cache(video_id, tag)
    if cached is not None:
        return TranscriptResult(*cached)

    ip_blocked = False
    only_dubbed = False
    if transcript_breaker.wait_if_open(tag):
        for attempt, delay in enumerate(retry_delays, start=1):
            try:
                result = _fetch_transcript_once(
                    video_id, language, job_id=job_id, audio_language=audio_language
                )
            except _IpBlockedError as e:
                # YouTube is actively blocking us — no point retrying in 2-8s.
                logger.warning(
                    f"{tag} YouTube is blocking requests for {video_id} ({e})"
                )
                transcript_breaker.record_block()
                ip_blocked = True
                break
            except _NoSpokenTrackError as e:
                # Only auto-dubbed tracks: definitive, so no retry. Whisper
                # transcribes the original audio (yt-dlp prefers the track
                # marked original), so it is still worth trying.
                logger.warning(f"{tag} {e}")
                transcript_breaker.record_success()
                only_dubbed = True
                break
            if result:
                logger.info(
                    f"{tag} YouTube transcript succeeded for {video_id} "
                    f"on attempt {attempt}/{len(retry_delays)}"
                )
                transcript_breaker.record_success()
                segments, actual_lang, track = result
                _save_to_cache(video_id, segments, actual_lang, "youtube", tag)
                return TranscriptResult(segments, actual_lang, "youtube", track)
            if attempt < len(retry_delays):
                logger.info(
                    f"{tag} Transcript attempt {attempt}/{len(retry_delays)} failed for {video_id}, "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
    else:
        ip_blocked = True

    if not allow_whisper:
        logger.warning(
            f"{tag} Transcript unavailable for {video_id} and Whisper fallback "
            "is disabled (per-job budget exhausted); recording unavailable"
        )
        return None

    if only_dubbed:
        logger.warning(f"{tag} Starting Whisper API fallback for {video_id} (original audio)...")
    elif not ip_blocked:
        logger.warning(
            f"{tag} All {len(retry_delays)} YouTube transcript attempts failed for {video_id}. "
            "Starting Whisper API fallback..."
        )
    whisper_result = _transcribe_with_whisper(video_id, job_id=job_id)
    if whisper_result is not None:
        _save_to_cache(video_id, whisper_result[0], whisper_result[1], "whisper", tag)
        return TranscriptResult(whisper_result[0], whisper_result[1], "whisper")
    return None


def _load_from_cache(video_id: str, tag: str) -> tuple[list[dict], str, str] | None:
    """Return cached (segments, language, source) for video_id, or None on miss.

    Rows written before the S-1.11.4 provenance migration have NULL source;
    those default to "youtube" (the pre-fix writer's dominant path).
    """
    db = SessionLocal()
    try:
        row = db.query(TranscriptCache).filter(TranscriptCache.video_id == video_id).first()
        if row is None:
            return None
        try:
            segments = json.loads(row.segments_json)
        except (ValueError, TypeError):
            logger.exception(f"{tag} Corrupt transcript cache row for {video_id}; ignoring")
            return None
        source = getattr(row, "source", None) or "youtube"
        logger.info(
            f"{tag} Transcript cache hit for {video_id}: "
            f"{len(segments)} segments, language={row.language}, source={source}"
        )
        return segments, row.language, source
    finally:
        db.close()


def _save_to_cache(
    video_id: str, segments: list[dict], language: str, source: str, tag: str
) -> None:
    """Upsert a transcript into the cache. Failures are logged but non-fatal."""
    if not segments:
        return
    db = SessionLocal()
    try:
        payload = json.dumps(segments)
        existing = db.query(TranscriptCache).filter(TranscriptCache.video_id == video_id).first()
        if existing is None:
            db.add(
                TranscriptCache(
                    video_id=video_id,
                    segments_json=payload,
                    language=language,
                    source=source,
                )
            )
        else:
            existing.segments_json = payload
            existing.language = language
            existing.source = source
            existing.fetched_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"{tag} Transcript cached for {video_id}: "
            f"{len(segments)} segments, language={language}"
        )
    except Exception:
        db.rollback()
        logger.exception(f"{tag} Failed to write transcript cache for {video_id}")
    finally:
        db.close()


def _build_transcript_api() -> YouTubeTranscriptApi:
    """Build the transcript client, routing through the configured proxy
    when ``YOUTUBE_PROXY_URL`` is set (S-1.11.10 / D-051 hook — the
    escape hatch for cloud-IP / rate-based blocks)."""
    proxy_url = (settings.YOUTUBE_PROXY_URL or "").strip()
    if not proxy_url:
        return YouTubeTranscriptApi()
    from youtube_transcript_api.proxies import GenericProxyConfig

    return YouTubeTranscriptApi(
        proxy_config=GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
    )


def _fetch_transcript_once(
    video_id: str,
    language: str = "en",
    job_id: str = "",
    audio_language: Any = AUDIO_LANGUAGE_UNSET,
) -> tuple[list[dict], str, dict] | None:
    """Single attempt to fetch transcript via YouTube Transcript API.

    Lists the caption tracks once, chooses the spoken-language track
    (``plan_caption_track``, S-1.11.11) and fetches only that one.

    Returns a (segments, actual_language, track_metadata) tuple, or None on
    failure. Raises ``_IpBlockedError`` when YouTube is blocking us and
    ``_NoSpokenTrackError`` when every track is an auto-dub.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    transcript_limiter.wait()
    ytt_api = _build_transcript_api()
    logger.info(f"{tag} _fetch_transcript_once: video_id={video_id}, fallback language={language}")

    try:
        choice = plan_caption_track(
            ytt_api, video_id, language=language, audio_language=audio_language, tag=tag
        )
        if choice.track is None:
            if choice.match == "only_dubbed":
                raise _NoSpokenTrackError(
                    f"Every caption track of {video_id} is an auto-dub "
                    f"(skipped {list(choice.skipped_dubbed)}); refusing to ingest a dub"
                )
            logger.warning(f"{tag} No caption tracks listed for {video_id}")
            return None
        logger.info(
            f"{tag} Caption track for {video_id}: {choice.language} ({choice.kind}, "
            f"{choice.match}; spoken={choice.spoken_language} via "
            f"{choice.spoken_language_source}; available={list(choice.available)}"
            + (f"; skipped dubs={list(choice.skipped_dubbed)}" if choice.skipped_dubbed else "")
            + ")"
        )
        transcript = choice.track.fetch()
        result = _transcript_to_list(transcript)
        actual_lang = getattr(transcript, "language_code", None) or choice.language or language
        logger.info(
            f"{tag} YouTube transcript fetched for {video_id}: "
            f"{len(result)} segments (language={actual_lang})"
        )
        return result, actual_lang, choice.as_metadata()
    except _NoSpokenTrackError:
        raise
    except Exception as e:
        logger.warning(f"{tag} Transcript unavailable for {video_id}: {e}")
        # Propagate a sentinel so callers can distinguish IP-blocking (where
        # retrying a few seconds later is pointless) from normal "no transcript"
        # failures. The youtube-transcript-api library raises a handful of
        # exception types for this; we don't want to import them all, so we
        # match on their string representation.
        if _is_ip_block_signal(e):
            raise _IpBlockedError(str(e)) from e

    return None


class _IpBlockedError(RuntimeError):
    """Marker raised by `_fetch_transcript_once` when YouTube is rate-limiting us.

    Consumed by `fetch_transcript` to skip the retry loop and go straight to
    Whisper fallback (or bail), since retrying within seconds won't unblock us.
    """


def _is_ip_block_signal(exc: BaseException) -> bool:
    """True when the exception message indicates YouTube is blocking our IP.

    youtube-transcript-api raises `IpBlocked` / `RequestBlocked` for explicit
    blocks and bubbles up `urllib3.exceptions.RemoteDisconnected` when the
    server closes the connection without responding — a common symptom of
    rate-limiting. Classifying by name avoids brittle imports across library
    versions.
    """
    names: list[str] = []
    cls = type(exc)
    if cls is not None:
        names.append(cls.__name__)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        names.append(type(cause).__name__)
    # Also walk args in case the real exception is nested inside a tuple.
    for a in getattr(exc, "args", ()) or ():
        if isinstance(a, BaseException):
            names.append(type(a).__name__)
    msg = str(exc).lower()
    signals = ("ipblocked", "requestblocked", "remotedisconnected", "youtube is blocking")
    return any(s.lower() in n.lower() for s in signals for n in names) or any(
        s in msg for s in signals
    )


# Per-request timeout for a single Whisper API call. OpenAI's SDK default is
# 600s total, which was letting failed requests hang for 5+ minutes each. A
# tighter cap lets us surface transient connection errors quickly and retry.
# 180s is long enough for a ~25 MB upload over a 1 Mbit/s link with margin
# for transcription, short enough that three retries total out under 10 min.
_WHISPER_REQUEST_TIMEOUT = 180.0
_WHISPER_MAX_ATTEMPTS = 3
_WHISPER_RETRY_BACKOFF = (5, 15)  # seconds between attempts 1→2 and 2→3


def _whisper_transcribe_with_retry(
    client, audio_path: str, video_id: str, tag: str, audio_size_mb: float
):
    """Call OpenAI Whisper with bounded retries for transient errors.

    Retryable: ``APIConnectionError``, ``APITimeoutError``, 5xx ``InternalServerError``.
    These typically indicate network drops or upstream overload — the same
    file often succeeds on a second attempt.

    Non-retryable: ``BadRequestError`` (e.g. 400 "file too large" — won't get
    smaller on retry), ``AuthenticationError`` / ``PermissionDeniedError``
    (credentials won't fix themselves). These bubble up so the caller records
    the video as unavailable without wasting 3× the upload time.
    """
    # Deferred import so the module loads cleanly in test environments where
    # ``openai`` may be unavailable at import time.
    from openai import (
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        PermissionDeniedError,
    )

    last_exc: BaseException | None = None
    for attempt in range(1, _WHISPER_MAX_ATTEMPTS + 1):
        try:
            logger.info(
                f"{tag} Sending {video_id} to OpenAI Whisper API "
                f"({audio_size_mb:.1f} MB, attempt {attempt}/{_WHISPER_MAX_ATTEMPTS})..."
            )
            with open(audio_path, "rb") as audio_file:
                return client.with_options(
                    timeout=_WHISPER_REQUEST_TIMEOUT
                ).audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                )
        except (BadRequestError, AuthenticationError, PermissionDeniedError) as e:
            # Non-retryable: re-raise so the caller records unavailable.
            logger.error(
                f"{tag} Whisper non-retryable error for {video_id} "
                f"(attempt {attempt}): {type(e).__name__}: {e}"
            )
            raise
        except (APIConnectionError, APITimeoutError, InternalServerError) as e:
            last_exc = e
            if attempt < _WHISPER_MAX_ATTEMPTS:
                backoff = _WHISPER_RETRY_BACKOFF[attempt - 1]
                logger.warning(
                    f"{tag} Whisper retryable error for {video_id} "
                    f"(attempt {attempt}/{_WHISPER_MAX_ATTEMPTS}): "
                    f"{type(e).__name__}: {e}. Retrying in {backoff}s..."
                )
                time.sleep(backoff)
            else:
                logger.error(
                    f"{tag} Whisper exhausted {_WHISPER_MAX_ATTEMPTS} attempts for "
                    f"{video_id}: {type(e).__name__}: {e}"
                )
    if last_exc is not None:
        raise last_exc
    return None


# yt-dlp innertube player-client ladder (S-1.11.3 / D-051). YouTube's 403s on
# audio downloads are usually client-specific (signature throttling applied to
# the default web client); retrying via the android or ios innertube clients
# recovers most of them. Sleep between rungs so a transient block can clear.
_YTDLP_CLIENT_LADDER: tuple[tuple[str | None, float], ...] = (
    (None, 0),          # yt-dlp default client selection
    ("android", 5),
    ("ios", 15),
)

# S-1.11.10: pace yt-dlp attempts the same way transcript fetches are paced —
# back-to-back download bursts escalate YouTube's bot-wall.
download_limiter = RateLimiter(
    rate=settings.YTDLP_DOWNLOAD_RATE_LIMIT,
    jitter=settings.YOUTUBE_TRANSCRIPT_RATE_JITTER,
)


def _build_ydl_opts(
    attempt_dir: str, client: str | None, prefer_smallest: bool
) -> dict:
    """Assemble yt-dlp options for one download attempt.

    Folds in the S-1.11.10 unblock knobs when configured:
    - ``YOUTUBE_PROXY_URL`` routes the download through a proxy.
    - ``YTDLP_COOKIES_FROM_BROWSER`` / ``YTDLP_COOKIES_FILE`` attach the
      operator's own YouTube session to pass the "confirm you're not a
      bot" wall (browser source wins; both are explicit opt-in).
    """
    fmt = (
        "worstaudio[ext=m4a]/worstaudio[ext=webm]/worstaudio"
        if prefer_smallest
        else "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"
    )
    opts: dict = {
        "format": fmt,
        "outtmpl": os.path.join(attempt_dir, "audio.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    proxy_url = (settings.YOUTUBE_PROXY_URL or "").strip()
    if proxy_url:
        opts["proxy"] = proxy_url
    from_browser = (settings.YTDLP_COOKIES_FROM_BROWSER or "").strip()
    cookies_file = (settings.YTDLP_COOKIES_FILE or "").strip()
    if from_browser:
        # yt-dlp expects a tuple (browser, profile, keyring, container);
        # support the "browser" and "browser:Profile" spellings.
        browser, _, profile = from_browser.partition(":")
        opts["cookiesfrombrowser"] = (browser, profile or None, None, None)
    elif cookies_file:
        opts["cookiefile"] = cookies_file
    return opts


def _download_audio_with_ladder(
    video_id: str, tmpdir: str, tag: str, prefer_smallest: bool = False
) -> str | None:
    """Download a video's audio via yt-dlp, escalating through player clients
    on failure. Returns the audio file path, or None when every rung failed.

    ``prefer_smallest`` selects the lowest-bitrate audio format — used for the
    oversize retry path where fidelity matters less than fitting the Whisper
    upload cap (speech transcription is robust to low-bitrate audio).
    """
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"

    for client, delay in _YTDLP_CLIENT_LADDER:
        if delay:
            time.sleep(delay)
        download_limiter.wait()
        # Fresh subdir per attempt so a partial download from a failed rung
        # can't be mistaken for the real artifact.
        attempt_dir = tempfile.mkdtemp(dir=tmpdir)
        ydl_opts = _build_ydl_opts(attempt_dir, client, prefer_smallest)
        client_label = client or "default"
        try:
            logger.info(
                f"{tag} Downloading audio for {video_id} via yt-dlp "
                f"(client={client_label}, format={'smallest' if prefer_smallest else 'best'})..."
            )
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            logger.warning(
                f"{tag} yt-dlp download failed for {video_id} "
                f"(client={client_label}): {e}"
            )
            continue
        files = [os.path.join(attempt_dir, f) for f in os.listdir(attempt_dir)]
        if files:
            return files[0]
        logger.warning(
            f"{tag} yt-dlp produced no file for {video_id} (client={client_label})"
        )
    logger.error(
        f"{tag} yt-dlp download failed for {video_id} on all "
        f"{len(_YTDLP_CLIENT_LADDER)} player clients"
    )
    return None


def _probe_audio_duration(audio_path: str, tag: str) -> float:
    """Return the audio duration in seconds via ffprobe, or 0.0 on failure."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return float(out.stdout.strip())
    except Exception as e:
        logger.warning(f"{tag} ffprobe duration probe failed: {e}")
        return 0.0


def _split_audio_for_whisper(
    audio_path: str, tmpdir: str, tag: str
) -> list[tuple[str, float]] | None:
    """Split oversize audio into overlapping chunks via ffmpeg stream-copy.

    S-1.11.2 / D-051 (user-specified design): chunks target
    ``WHISPER_SEGMENT_TARGET_MB`` each and share
    ``WHISPER_SEGMENT_OVERLAP_SECONDS`` of audio with their successor so
    words cut at a boundary are fully captured in the next chunk.

    Returns ``[(chunk_path, chunk_start_seconds), ...]`` or None when
    splitting isn't possible (no ffmpeg / unknown duration / ffmpeg error).
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning(
            f"{tag} ffmpeg not found on PATH — cannot split oversize audio. "
            "Install ffmpeg to enable segmented Whisper transcription."
        )
        return None

    duration = _probe_audio_duration(audio_path, tag)
    if duration <= 0:
        logger.warning(f"{tag} Unknown audio duration; cannot split for Whisper")
        return None

    size_bytes = os.path.getsize(audio_path)
    target_bytes = settings.WHISPER_SEGMENT_TARGET_MB * 1024 * 1024
    n_chunks = max(2, math.ceil(size_bytes / target_bytes))
    chunk_len = duration / n_chunks
    overlap = settings.WHISPER_SEGMENT_OVERLAP_SECONDS
    ext = os.path.splitext(audio_path)[1] or ".m4a"

    logger.info(
        f"{tag} Splitting {size_bytes / (1024 * 1024):.1f} MB / {duration:.0f}s audio "
        f"into {n_chunks} chunks of ~{chunk_len:.0f}s (+{overlap:.0f}s overlap)"
    )

    chunks: list[tuple[str, float]] = []
    for i in range(n_chunks):
        start = i * chunk_len
        # Every chunk except the last extends into its successor by `overlap`.
        length = chunk_len + (overlap if i < n_chunks - 1 else 0)
        out_path = os.path.join(tmpdir, f"whisper_chunk_{i:03d}{ext}")
        cmd = [
            ffmpeg, "-v", "error", "-y",
            "-ss", f"{start:.2f}",
            "-t", f"{length:.2f}",
            "-i", audio_path,
            "-c", "copy",
            out_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        except Exception as e:
            logger.error(f"{tag} ffmpeg chunk {i}/{n_chunks} failed: {e}")
            return None
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.error(f"{tag} ffmpeg produced empty chunk {i}/{n_chunks}")
            return None
        chunks.append((out_path, start))
    return chunks


def _merge_chunk_transcripts(
    per_chunk: list[tuple[float, float, list[dict]]],
    overlap: float,
    tag: str,
) -> list[dict]:
    """Merge per-chunk Whisper segments into one timeline (S-1.11.2).

    ``per_chunk`` is ``[(chunk_start, chunk_len, segments), ...]`` where each
    segment's ``start`` is chunk-relative. Timestamps are shifted by the
    chunk's position; segments inside an overlap zone are deduplicated by the
    midpoint-ownership rule: the boundary between chunk *i* and *i+1* falls at
    ``overlap / 2`` into the shared audio, and each chunk keeps only segments
    whose (adjusted) start lies inside its owned span.
    """
    merged: list[dict] = []
    n = len(per_chunk)
    for i, (chunk_start, chunk_len, segments) in enumerate(per_chunk):
        own_lo = chunk_start + (overlap / 2 if i > 0 else 0.0)
        own_hi = (
            chunk_start + chunk_len + (overlap / 2)
            if i < n - 1
            else float("inf")
        )
        kept = 0
        for seg in segments:
            adjusted_start = float(seg.get("start", 0.0)) + chunk_start
            if own_lo <= adjusted_start < own_hi:
                merged.append(
                    {
                        "text": seg["text"],
                        "start": adjusted_start,
                        "duration": float(seg.get("duration", 0.0)),
                    }
                )
                kept += 1
        logger.info(
            f"{tag} Chunk {i + 1}/{n}: kept {kept}/{len(segments)} segments "
            f"(owned span {own_lo:.0f}s–{'end' if own_hi == float('inf') else f'{own_hi:.0f}s'})"
        )
    merged.sort(key=lambda s: s["start"])
    return merged


def _whisper_response_to_segments(response, tag: str, video_id: str) -> tuple[list[dict], str, float]:
    """Normalize a verbose_json Whisper response to our segment dicts.

    Returns (segments, language, duration). Falls back to pseudo-segments
    when the response carries only a text blob.
    """
    response_language = getattr(response, "language", None) or "unknown"
    response_duration = float(getattr(response, "duration", 0.0) or 0.0)

    raw_segments = getattr(response, "segments", None) or []
    if raw_segments:
        transcript = [
            {
                "text": getattr(seg, "text", "").strip(),
                "start": getattr(seg, "start", 0.0),
                "duration": getattr(seg, "end", getattr(seg, "start", 0.0))
                - getattr(seg, "start", 0.0),
            }
            for seg in raw_segments
            if getattr(seg, "text", "").strip()
        ]
        return transcript, response_language, response_duration

    text = getattr(response, "text", "").strip()
    if text:
        pseudo = _synthesize_pseudo_segments(text, response_duration)
        logger.info(
            f"{tag} Whisper returned full text (no segments) for {video_id}: "
            f"{len(text.split())} words → {len(pseudo)} pseudo-segments"
        )
        return pseudo, response_language, response_duration
    return [], response_language, response_duration


def _transcribe_with_whisper(
    video_id: str, job_id: str = ""
) -> tuple[list[dict], str] | None:
    """
    Download audio with yt-dlp and transcribe via OpenAI Whisper API.

    Oversize handling (S-1.11.2 / D-051): audio beyond the 25 MB Whisper cap
    is first re-downloaded at the smallest available bitrate; if still
    oversize it is split into overlapping ffmpeg stream-copy chunks that are
    transcribed independently and merged with offset-adjusted timestamps.

    Returns (segments, language) tuple on success, or None on failure.

    Multilingual note: we do **not** pass a ``language`` hint so Whisper
    auto-detects the spoken language(s). OpenAI's hosted
    ``audio.transcriptions.create`` already preserves the speaker's original
    language (its sibling ``audio.translations.create`` is the one that
    forces English), so no explicit ``task`` kwarg is needed — the hosted
    API does not accept one. Proper nouns and code-mixed speech are
    preserved in their native script.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} Whisper fallback starting for video_id={video_id}")

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        logger.error(f"{tag} yt-dlp is not installed. Run: pip install yt-dlp")
        return None

    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = _download_audio_with_ladder(video_id, tmpdir, tag)
        if audio_path is None:
            return None

        audio_size_bytes = os.path.getsize(audio_path)
        audio_size_mb = audio_size_bytes / (1024 * 1024)
        logger.info(
            f"{tag} Audio downloaded for {video_id}: "
            f"{audio_size_mb:.1f} MB ({os.path.basename(audio_path)})"
        )

        # Oversize step 1: retry at the smallest available bitrate — cheap,
        # no ffmpeg needed, and often enough on its own.
        if audio_size_bytes > WHISPER_MAX_FILE_BYTES:
            logger.info(
                f"{tag} Audio for {video_id} is {audio_size_mb:.1f} MB (> 25 MB); "
                "retrying with smallest audio format..."
            )
            smaller = _download_audio_with_ladder(
                video_id, tmpdir, tag, prefer_smallest=True
            )
            if smaller is not None and os.path.getsize(smaller) < audio_size_bytes:
                audio_path = smaller
                audio_size_bytes = os.path.getsize(audio_path)
                audio_size_mb = audio_size_bytes / (1024 * 1024)
                logger.info(
                    f"{tag} Smallest-format audio for {video_id}: {audio_size_mb:.1f} MB"
                )

        # Oversize step 2: segmented transcription.
        if audio_size_bytes > WHISPER_MAX_FILE_BYTES:
            chunks = _split_audio_for_whisper(audio_path, tmpdir, tag)
            if not chunks:
                logger.warning(
                    f"{tag} Audio for {video_id} is {audio_size_mb:.1f} MB, exceeds Whisper "
                    f"{WHISPER_MAX_FILE_BYTES // (1024 * 1024)} MB limit and could not be "
                    "split; skipping Whisper fallback"
                )
                return None
            overlap = settings.WHISPER_SEGMENT_OVERLAP_SECONDS
            per_chunk: list[tuple[float, float, list[dict]]] = []
            language = "unknown"
            n = len(chunks)
            chunk_len_estimate = 0.0
            for idx, (chunk_path, chunk_start) in enumerate(chunks):
                chunk_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                try:
                    response = _whisper_transcribe_with_retry(
                        client, chunk_path, f"{video_id}#chunk{idx + 1}/{n}", tag, chunk_mb
                    )
                except Exception as e:
                    logger.error(
                        f"{tag} Whisper failed on chunk {idx + 1}/{n} of {video_id}: {e}"
                    )
                    return None
                if response is None:
                    return None
                segs, lang, dur = _whisper_response_to_segments(response, tag, video_id)
                if lang != "unknown":
                    language = lang
                # Chunk length (sans tail overlap) — from the response duration.
                chunk_len = max(0.0, dur - (overlap if idx < n - 1 else 0.0))
                chunk_len_estimate = chunk_len or chunk_len_estimate
                per_chunk.append((chunk_start, chunk_len or chunk_len_estimate, segs))
            merged = _merge_chunk_transcripts(per_chunk, overlap, tag)
            logger.info(
                f"{tag} Segmented Whisper transcription succeeded for {video_id}: "
                f"{len(merged)} segments across {n} chunks (language={language})"
            )
            if not merged:
                return None
            return merged, language

        # Standard single-file path.
        try:
            response = _whisper_transcribe_with_retry(
                client, audio_path, video_id, tag, audio_size_mb
            )
        except Exception as e:
            logger.error(f"{tag} OpenAI Whisper API transcription failed for {video_id}: {e}")
            return None
        if response is None:
            return None

        transcript, response_language, _ = _whisper_response_to_segments(
            response, tag, video_id
        )
        logger.info(
            f"{tag} Whisper transcription succeeded for {video_id}: "
            f"{len(transcript)} segments (language={response_language})"
        )
        if not transcript:
            return None
        return transcript, response_language


def _synthesize_pseudo_segments(text: str, duration_seconds: float) -> list[dict]:
    """
    Split a single-blob Whisper transcript into evenly spaced pseudo-segments.

    Uses word count to proportion the text, and the reported audio duration to
    space start times. Falls back to a single segment when duration is unknown
    or the text is too short to split meaningfully.
    """
    words = text.split()
    if not words:
        return []

    if duration_seconds <= 0:
        # Without a duration we have no basis for timestamps; keep one segment.
        return [{"text": text, "start": 0.0, "duration": 0.0}]

    segment_len = WHISPER_PSEUDO_SEGMENT_SECONDS
    num_segments = max(1, int(round(duration_seconds / segment_len)))
    if num_segments == 1:
        return [{"text": text, "start": 0.0, "duration": duration_seconds}]

    words_per_segment = max(1, len(words) // num_segments)
    segments: list[dict] = []
    for i in range(num_segments):
        start_word = i * words_per_segment
        # Absorb any remainder words into the final segment so no text is lost.
        end_word = (i + 1) * words_per_segment if i < num_segments - 1 else len(words)
        chunk = " ".join(words[start_word:end_word]).strip()
        if not chunk:
            continue
        start = round(i * segment_len, 3)
        # Clamp the last segment's duration to the actual audio length.
        end = min(duration_seconds, (i + 1) * segment_len)
        segments.append(
            {
                "text": chunk,
                "start": start,
                "duration": round(max(0.0, end - start), 3),
            }
        )
    return segments


def _transcript_to_list(transcript) -> list[dict]:
    return [
        {
            "text": entry.text,
            "start": entry.start,
            "duration": entry.duration,
        }
        for entry in transcript
    ]

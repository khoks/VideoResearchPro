import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi

from app.config import settings
from app.database import SessionLocal
from app.models.transcript_cache import TranscriptCache
from app.services import quota_service
from app.services.quota_service import QuotaExceededError
from app.utils.rate_limiter import RateLimiter
from app.utils.youtube_helpers import parse_iso8601_duration

logger = logging.getLogger(__name__)

transcript_limiter = RateLimiter(rate=settings.YOUTUBE_TRANSCRIPT_RATE_LIMIT)

# OpenAI Whisper API enforces a 25 MB upload limit per file.
WHISPER_MAX_FILE_BYTES = 25 * 1024 * 1024

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

    response = _execute_youtube_request(youtube.search().list(**params), "search")

    videos = []
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

    logger.info(f"search_videos: returned {len(videos)} results for query={query!r}")
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
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "view_count": _safe_int(stats.get("viewCount")),
                "like_count": _safe_int(stats.get("likeCount")),
            }

    logger.info(f"{tag} get_video_details: resolved {len(details)}/{total} video(s)")
    return details


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


def fetch_transcript(
    video_id: str, language: str = "en", job_id: str = ""
) -> tuple[list[dict], str] | None:
    """
    Fetch transcript with caching, retry, and OpenAI Whisper API fallback.

    Lookup order:
    1. transcript_cache DB table — cache hit returns immediately.
    2. YouTube Transcript API up to 3 times with exponential backoff (2s, 4s, 8s).
    3. Download audio via yt-dlp and transcribe via OpenAI Whisper API.

    Returns:
        Tuple of (segments, actual_language) on success, or None if unavailable.
        `segments` is a list of {text, start, duration} dicts.
        `actual_language` is the BCP-47 code of the transcript that was fetched,
        or "unknown" when the source cannot report one (e.g. Whisper fallback).
    """
    retry_delays = [2, 4, 8]
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} fetch_transcript: video_id={video_id}, language={language}")

    cached = _load_from_cache(video_id, tag)
    if cached is not None:
        return cached

    for attempt, delay in enumerate(retry_delays, start=1):
        result = _fetch_transcript_once(video_id, language, job_id=job_id)
        if result:
            logger.info(
                f"{tag} YouTube transcript succeeded for {video_id} "
                f"on attempt {attempt}/{len(retry_delays)}"
            )
            _save_to_cache(video_id, result[0], result[1], tag)
            return result
        if attempt < len(retry_delays):
            logger.info(
                f"{tag} Transcript attempt {attempt}/{len(retry_delays)} failed for {video_id}, "
                f"retrying in {delay}s..."
            )
            time.sleep(delay)

    logger.warning(
        f"{tag} All {len(retry_delays)} YouTube transcript attempts failed for {video_id}. "
        "Starting Whisper API fallback..."
    )
    whisper_result = _transcribe_with_whisper(video_id, job_id=job_id)
    if whisper_result is not None:
        _save_to_cache(video_id, whisper_result[0], whisper_result[1], tag)
    return whisper_result


def _load_from_cache(video_id: str, tag: str) -> tuple[list[dict], str] | None:
    """Return cached (segments, language) tuple for video_id, or None on miss."""
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
        logger.info(
            f"{tag} Transcript cache hit for {video_id}: "
            f"{len(segments)} segments, language={row.language}"
        )
        return segments, row.language
    finally:
        db.close()


def _save_to_cache(video_id: str, segments: list[dict], language: str, tag: str) -> None:
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
                )
            )
        else:
            existing.segments_json = payload
            existing.language = language
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


def _fetch_transcript_once(
    video_id: str, language: str = "en", job_id: str = ""
) -> tuple[list[dict], str] | None:
    """Single attempt to fetch transcript via YouTube Transcript API.

    Returns a (segments, actual_language) tuple, or None on failure.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    transcript_limiter.wait()
    ytt_api = YouTubeTranscriptApi()

    # Preferred language order
    preferred = [language, f"{language}-auto", "en", "en-auto"]
    logger.info(f"{tag} _fetch_transcript_once: video_id={video_id}, trying languages={preferred}")

    try:
        transcript = ytt_api.fetch(video_id, languages=preferred)
        result = _transcript_to_list(transcript)
        actual_lang = getattr(transcript, "language_code", None) or language
        logger.info(
            f"{tag} YouTube transcript fetched for {video_id}: "
            f"{len(result)} segments (language={actual_lang})"
        )
        return result, actual_lang
    except Exception:
        pass

    # Fallback: try any available transcript
    try:
        transcript_list = ytt_api.list(video_id)
        available = [t.language_code for t in transcript_list]
        if available:
            fallback_lang = available[0]
            logger.info(
                f"{tag} Preferred languages unavailable for {video_id}, "
                f"falling back to '{fallback_lang}' (available: {available})"
            )
            transcript = ytt_api.fetch(video_id, languages=[fallback_lang])
            result = _transcript_to_list(transcript)
            actual_lang = getattr(transcript, "language_code", None) or fallback_lang
            logger.info(
                f"{tag} Fallback transcript fetched for {video_id} in '{actual_lang}': "
                f"{len(result)} segments"
            )
            return result, actual_lang
    except Exception as e:
        logger.warning(f"{tag} Transcript unavailable for {video_id}: {e}")

    return None


def _transcribe_with_whisper(
    video_id: str, job_id: str = ""
) -> tuple[list[dict], str] | None:
    """
    Download audio with yt-dlp and transcribe via OpenAI Whisper API.

    Does not require ffmpeg — downloads audio in native format (m4a/webm).
    Returns (segments, language) tuple on success, or None on failure.
    """
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} Whisper fallback starting for video_id={video_id}")

    try:
        import yt_dlp
    except ImportError:
        logger.error(f"{tag} yt-dlp is not installed. Run: pip install yt-dlp")
        return None

    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_template = os.path.join(tmpdir, "audio.%(ext)s")

        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "outtmpl": audio_template,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            logger.info(f"{tag} Downloading audio for {video_id} via yt-dlp...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            logger.error(f"{tag} yt-dlp download failed for {video_id}: {e}")
            return None

        candidates = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
        if not candidates:
            logger.error(f"{tag} No audio file found after yt-dlp download for {video_id}")
            return None
        audio_path = candidates[0]
        audio_size_bytes = os.path.getsize(audio_path)
        audio_size_mb = audio_size_bytes / (1024 * 1024)
        logger.info(
            f"{tag} Audio downloaded for {video_id}: "
            f"{audio_size_mb:.1f} MB ({os.path.basename(audio_path)})"
        )

        # Whisper rejects uploads larger than 25 MB. Splitting is out of scope;
        # bail cleanly so callers can record the transcript as unavailable.
        if audio_size_bytes > WHISPER_MAX_FILE_BYTES:
            logger.warning(
                f"{tag} Audio for {video_id} is {audio_size_mb:.1f} MB, exceeds Whisper "
                f"{WHISPER_MAX_FILE_BYTES // (1024 * 1024)} MB limit; skipping Whisper fallback"
            )
            return None

        try:
            logger.info(
                f"{tag} Sending {video_id} to OpenAI Whisper API ({audio_size_mb:.1f} MB)..."
            )
            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                )
        except Exception as e:
            logger.error(f"{tag} OpenAI Whisper API transcription failed for {video_id}: {e}")
            return None

        response_language = getattr(response, "language", None) or "unknown"
        response_duration = float(getattr(response, "duration", 0.0) or 0.0)

        segments = getattr(response, "segments", None) or []
        if not segments:
            text = getattr(response, "text", "").strip()
            if text:
                pseudo = _synthesize_pseudo_segments(text, response_duration)
                logger.info(
                    f"{tag} Whisper returned full text (no segments) for {video_id}: "
                    f"{len(text.split())} words → {len(pseudo)} pseudo-segments "
                    f"(duration={response_duration:.1f}s, language={response_language})"
                )
                return pseudo, response_language
            logger.warning(f"{tag} Whisper returned no transcript content for {video_id}")
            return None

        transcript = [
            {
                "text": getattr(seg, "text", "").strip(),
                "start": getattr(seg, "start", 0.0),
                "duration": getattr(seg, "end", getattr(seg, "start", 0.0))
                - getattr(seg, "start", 0.0),
            }
            for seg in segments
            if getattr(seg, "text", "").strip()
        ]

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

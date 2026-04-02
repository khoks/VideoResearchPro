import logging
import os
import tempfile
import time
from datetime import datetime, timezone

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

from app.config import settings
from app.utils.rate_limiter import RateLimiter
from app.utils.youtube_helpers import parse_iso8601_duration

logger = logging.getLogger(__name__)

transcript_limiter = RateLimiter(rate=settings.YOUTUBE_TRANSCRIPT_RATE_LIMIT)


def get_youtube_client():
    return build("youtube", "v3", developerKey=settings.YOUTUBE_API_KEY)


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
        channel_type: Filter by channel type.

    Returns:
        List of video dicts with basic metadata.
    """
    logger.info(
        f"search_videos: query={query!r}, max_results={max_results}, "
        f"published_after={published_after}, video_duration={video_duration}"
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

    response = youtube.search().list(**params).execute()

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
        response = youtube.videos().list(
            part="contentDetails,snippet,statistics",
            id=",".join(batch),
        ).execute()

        for item in response.get("items", []):
            vid = item["id"]
            content = item.get("contentDetails", {})
            snippet = item.get("snippet", {})
            details[vid] = {
                "video_id": vid,
                "title": snippet.get("title", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "duration_seconds": parse_iso8601_duration(content.get("duration", "PT0S")),
                "published_at": snippet.get("publishedAt"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                "url": f"https://www.youtube.com/watch?v={vid}",
            }

    logger.info(f"{tag} get_video_details: resolved {len(details)}/{total} video(s)")
    return details


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
    channel_response = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()

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
        playlist_response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=min(50, max_results - len(video_ids)),
            pageToken=next_page_token,
        ).execute()

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
        response = youtube.channels().list(
            part="id",
            forHandle=handle,
        ).execute()
        items = response.get("items", [])
        if items:
            channel_id = items[0]["id"]
            logger.info(f"{tag} resolve_channel_id: @{handle} → {channel_id}")
            return channel_id
        logger.warning(f"{tag} resolve_channel_id: handle @{handle} not found via API")

    # Fall back to search (costs 100 units)
    logger.info(f"{tag} resolve_channel_id: falling back to search for {channel_input!r} (costs 100 quota units)")
    response = youtube.search().list(
        q=channel_input,
        part="snippet",
        type="channel",
        maxResults=1,
    ).execute()
    items = response.get("items", [])
    if items:
        channel_id = items[0]["snippet"]["channelId"]
        logger.info(f"{tag} resolve_channel_id: search fallback → {channel_id}")
        return channel_id

    logger.warning(f"{tag} resolve_channel_id: could not resolve {channel_input!r}")
    return None


def fetch_transcript(video_id: str, language: str = "en", job_id: str = "") -> list[dict] | None:
    """
    Fetch transcript with retry + OpenAI Whisper API fallback.

    1. Try YouTube Transcript API up to 3 times with exponential backoff (2s, 4s, 8s).
    2. If all retries fail, download audio via yt-dlp and transcribe via OpenAI Whisper API.
    3. If that also fails, return None.

    Returns:
        List of {text, start, duration} segments, or None if unavailable.
    """
    retry_delays = [2, 4, 8]
    tag = f"[job:{job_id}]" if job_id else ""
    logger.info(f"{tag} fetch_transcript: video_id={video_id}, language={language}")

    for attempt, delay in enumerate(retry_delays, start=1):
        result = _fetch_transcript_once(video_id, language, job_id=job_id)
        if result:
            logger.info(f"{tag} YouTube transcript succeeded for {video_id} on attempt {attempt}/{len(retry_delays)}")
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
    return _transcribe_with_whisper(video_id, job_id=job_id)


def _fetch_transcript_once(video_id: str, language: str = "en", job_id: str = "") -> list[dict] | None:
    """Single attempt to fetch transcript via YouTube Transcript API."""
    tag = f"[job:{job_id}]" if job_id else ""
    transcript_limiter.wait()
    ytt_api = YouTubeTranscriptApi()

    # Preferred language order
    preferred = [language, f"{language}-auto", "en", "en-auto"]
    logger.info(f"{tag} _fetch_transcript_once: video_id={video_id}, trying languages={preferred}")

    try:
        transcript = ytt_api.fetch(video_id, languages=preferred)
        result = _transcript_to_list(transcript)
        logger.info(f"{tag} YouTube transcript fetched for {video_id}: {len(result)} segments")
        return result
    except Exception:
        pass

    # Fallback: try any available transcript
    try:
        transcript_list = ytt_api.list(video_id)
        available = [t.language_code for t in transcript_list]
        if available:
            logger.info(f"{tag} Preferred languages unavailable for {video_id}, "
                        f"falling back to '{available[0]}' (available: {available})")
            transcript = ytt_api.fetch(video_id, languages=[available[0]])
            result = _transcript_to_list(transcript)
            logger.info(f"{tag} Fallback transcript fetched for {video_id} in '{available[0]}': "
                        f"{len(result)} segments")
            return result
    except Exception as e:
        logger.warning(f"{tag} Transcript unavailable for {video_id}: {e}")

    return None


def _transcribe_with_whisper(video_id: str, job_id: str = "") -> list[dict] | None:
    """
    Download audio with yt-dlp and transcribe via OpenAI Whisper API.

    Does not require ffmpeg — downloads audio in native format (m4a/webm).
    Returns transcript segments in [{text, start, duration}] format, or None on failure.
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
        audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        logger.info(f"{tag} Audio downloaded for {video_id}: {audio_size_mb:.1f} MB ({os.path.basename(audio_path)})")

        try:
            logger.info(f"{tag} Sending {video_id} to OpenAI Whisper API ({audio_size_mb:.1f} MB)...")
            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                )
        except Exception as e:
            logger.error(f"{tag} OpenAI Whisper API transcription failed for {video_id}: {e}")
            return None

        segments = getattr(response, "segments", None) or []
        if not segments:
            text = getattr(response, "text", "").strip()
            if text:
                logger.info(f"{tag} Whisper returned full text (no segments) for {video_id}: "
                            f"{len(text.split())} words")
                return [{"text": text, "start": 0.0, "duration": 0.0}]
            logger.warning(f"{tag} Whisper returned no transcript content for {video_id}")
            return None

        transcript = [
            {
                "text": getattr(seg, "text", "").strip(),
                "start": getattr(seg, "start", 0.0),
                "duration": getattr(seg, "end", getattr(seg, "start", 0.0)) - getattr(seg, "start", 0.0),
            }
            for seg in segments
            if getattr(seg, "text", "").strip()
        ]

        logger.info(f"{tag} Whisper transcription succeeded for {video_id}: {len(transcript)} segments")
        return transcript or None


def _transcript_to_list(transcript) -> list[dict]:
    return [
        {
            "text": entry.text,
            "start": entry.start,
            "duration": entry.duration,
        }
        for entry in transcript
    ]

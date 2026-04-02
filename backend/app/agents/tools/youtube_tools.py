import json
import logging

from langchain_core.tools import tool

from app.services import youtube_service
from app.utils.youtube_helpers import format_duration

logger = logging.getLogger(__name__)


@tool
def youtube_search(query: str, max_results: int = 25, video_duration: str | None = None) -> str:
    """Search YouTube for videos matching a query.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default 25, max 50).
        video_duration: Filter by duration - "short" (<4min), "medium" (4-20min), "long" (>20min).

    Returns:
        JSON string of video results with titles, channels, and IDs.
    """
    videos = youtube_service.search_videos(
        query=query,
        max_results=min(max_results, 50),
        video_duration=video_duration,
    )
    return json.dumps(videos, indent=2)


@tool
def youtube_video_details(video_ids: list[str]) -> str:
    """Fetch detailed metadata for YouTube videos including duration.

    Args:
        video_ids: List of YouTube video IDs.

    Returns:
        JSON string of video details with durations.
    """
    details = youtube_service.get_video_details(video_ids)
    # Format durations for readability
    for vid, info in details.items():
        info["duration_display"] = format_duration(info.get("duration_seconds", 0))
    return json.dumps(details, indent=2)

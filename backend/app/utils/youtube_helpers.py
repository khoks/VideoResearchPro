import re


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    # Maybe it's just a video ID
    if re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        return url
    return None


def extract_channel_id(url: str) -> str | None:
    """Extract channel ID from YouTube channel URL."""
    # /channel/UCxxxxxx format
    match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{22})", url)
    if match:
        return match.group(1)
    return None


def extract_channel_handle(url: str) -> str | None:
    """Extract @handle from YouTube channel URL."""
    match = re.search(r"/@([a-zA-Z0-9_.-]+)", url)
    if match:
        return match.group(1)
    # Bare handle
    if url.startswith("@"):
        return url[1:]
    return None


def build_youtube_url(video_id: str, timestamp_seconds: float | None = None) -> str:
    """Build a YouTube URL, optionally with timestamp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    if timestamp_seconds is not None and timestamp_seconds > 0:
        url += f"&t={int(timestamp_seconds)}"
    return url


def format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_timestamp(seconds: float) -> str:
    """Format seconds into timestamp display (MM:SS or HH:MM:SS)."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_iso8601_duration(duration: str) -> int:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds

import json
import logging

from langchain_core.tools import tool

from app.services import chroma_service
from app.utils.youtube_helpers import build_youtube_url, format_timestamp

logger = logging.getLogger(__name__)


@tool
def search_knowledge_base(job_id: str, query: str, n_results: int = 15) -> str:
    """Search the video transcript knowledge base for relevant information.

    Args:
        job_id: The job ID whose knowledge base to search.
        query: The search query.
        n_results: Number of results to return.

    Returns:
        JSON string of relevant transcript chunks with metadata.
    """
    results = chroma_service.query_collection(job_id, query, n_results=n_results)

    # Enrich with formatted timestamps and links
    for r in results:
        meta = r.get("metadata", {})
        ts = meta.get("timestamp_start", 0)
        vid = meta.get("video_id", "")
        r["timestamp_display"] = format_timestamp(ts)
        r["youtube_link"] = build_youtube_url(vid, ts)

    return json.dumps(results, indent=2)

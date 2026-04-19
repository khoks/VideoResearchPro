import json
import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.search_prompts import INTERPRET_QUERY_PROMPT, RANK_AND_CURATE_PROMPT
from app.agents.state import SearchAgentState
from app.services import youtube_service
from app.services.llm_service import get_llm
from app.utils.youtube_helpers import format_duration

logger = logging.getLogger(__name__)


def generate_search_queries(state: SearchAgentState) -> dict:
    """Use LLM to generate YouTube search queries from topic + instructions."""
    llm = get_llm(temperature=0.3)
    prompt = INTERPRET_QUERY_PROMPT.format(
        topic=state["topic"],
        search_instructions=state.get("search_instructions", ""),
        channel_type_filters=", ".join(state.get("channel_type_filters", [])) or "none",
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        queries = json.loads(response.content)
        if not isinstance(queries, list):
            queries = [state["topic"]]
    except (json.JSONDecodeError, TypeError):
        queries = [state["topic"]]

    return {
        "search_queries_used": queries,
        "messages": [HumanMessage(content=f"Generated {len(queries)} search queries")],
    }


def execute_searches(state: SearchAgentState) -> dict:
    """Execute YouTube searches, pull detailed metadata, and filter by duration."""
    queries = state.get("search_queries_used", [state["topic"]])
    target = state["num_videos"]
    min_dur = state.get("min_duration")
    max_dur = state.get("max_duration")
    # NOTE: `channel_type_filters` (e.g. "educational", "academic") is a semantic
    # preference consumed by the LLM ranking step, NOT a YouTube API parameter.
    # YouTube's `channelType` only accepts ['channelTypeUnspecified', 'any', 'show'].
    # Don't forward user-facing semantic filters to the API — let the rank prompt use them.

    # Fetch a generous candidate pool so ranking has real choices. We rely on
    # post-fetch duration filtering (finer than YouTube's short/medium/long buckets).
    per_query_max = max(target * 3, 50)

    all_videos: dict[str, dict] = {}
    for query in queries:
        results = youtube_service.search_videos(
            query=query,
            max_results=per_query_max,
        )
        for v in results:
            vid = v["video_id"]
            if vid not in all_videos:
                all_videos[vid] = v

        if len(all_videos) >= target * 5:
            break

    # Fetch detailed metadata (duration, stats, channel_id, etc.).
    video_ids = list(all_videos.keys())
    if video_ids:
        details = youtube_service.get_video_details(video_ids)
        for vid, detail in details.items():
            if vid in all_videos:
                all_videos[vid].update(detail)

    # Fetch channel subscriber counts so ranking can use channel authority.
    channel_ids = sorted({v.get("channel_id") for v in all_videos.values() if v.get("channel_id")})
    if channel_ids:
        try:
            subs = youtube_service.get_channel_subscribers(channel_ids)
        except Exception:
            logger.exception("Failed to fetch channel subscribers; continuing without them")
            subs = {}
        for v in all_videos.values():
            v["channel_subscribers"] = subs.get(v.get("channel_id"))

    # Fine-grained duration filtering using minute bounds.
    filtered = []
    for v in all_videos.values():
        dur_min = v.get("duration_seconds", 0) / 60
        if min_dur is not None and dur_min < min_dur:
            continue
        if max_dur is not None and dur_min > max_dur:
            continue
        filtered.append(v)

    return {
        "discovered_videos": filtered,
        "messages": [HumanMessage(content=f"Found {len(filtered)} videos after filtering")],
    }


def _format_video_line(v: dict) -> str:
    """Render a single video entry for the ranking prompt."""
    subs = v.get("channel_subscribers")
    subs_str = f"{subs:,}" if isinstance(subs, int) else "unknown"
    views = v.get("view_count")
    views_str = f"{views:,}" if isinstance(views, int) else "unknown"
    likes = v.get("like_count")
    likes_str = f"{likes:,}" if isinstance(likes, int) else "unknown"
    return (
        f"- ID: {v['video_id']} | Title: {v.get('title', 'N/A')} | "
        f"Channel: {v.get('channel_name', 'N/A')} | "
        f"Duration: {format_duration(v.get('duration_seconds', 0))} | "
        f"Views: {views_str} | Likes: {likes_str} | "
        f"Published: {v.get('published_at', 'unknown')} | "
        f"Subscribers: {subs_str}"
    )


def rank_and_curate(state: SearchAgentState) -> dict:
    """Use LLM to rank and select the best videos."""
    videos = state.get("discovered_videos", [])
    target = state["num_videos"]

    if len(videos) <= target:
        return {"curated_videos": videos}

    llm = get_llm(temperature=0.0)
    video_list = "\n".join(_format_video_line(v) for v in videos)

    prompt = RANK_AND_CURATE_PROMPT.format(
        topic=state["topic"],
        search_instructions=state.get("search_instructions", ""),
        num_videos=target,
        video_list=video_list,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        selected_ids = json.loads(response.content)
        if isinstance(selected_ids, list):
            id_set = set(selected_ids[:target])
            curated = [v for v in videos if v["video_id"] in id_set]
            # Fill remaining slots if LLM didn't select enough
            if len(curated) < target:
                for v in videos:
                    if v["video_id"] not in id_set:
                        curated.append(v)
                        if len(curated) >= target:
                            break
            return {"curated_videos": curated}
    except (json.JSONDecodeError, TypeError):
        logger.exception("Failed to parse rank_and_curate LLM response; falling back to head-of-list")

    return {"curated_videos": videos[:target]}


def build_search_graph() -> StateGraph:
    """Build the search agent LangGraph."""
    graph = StateGraph(SearchAgentState)
    graph.add_node("generate_search_queries", generate_search_queries)
    graph.add_node("execute_searches", execute_searches)
    graph.add_node("rank_and_curate", rank_and_curate)

    graph.set_entry_point("generate_search_queries")
    graph.add_edge("generate_search_queries", "execute_searches")
    graph.add_edge("execute_searches", "rank_and_curate")
    graph.add_edge("rank_and_curate", END)

    return graph.compile()


def run_search_agent(
    topic: str,
    num_videos: int = 10,
    search_instructions: str = "",
    min_duration: int | None = None,
    max_duration: int | None = None,
    channel_type_filters: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Run the search agent and return (curated videos, queries used)."""
    graph = build_search_graph()
    result = graph.invoke({
        "messages": [],
        "topic": topic,
        "search_instructions": search_instructions,
        "num_videos": num_videos,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "channel_type_filters": channel_type_filters or [],
        "discovered_videos": [],
        "curated_videos": [],
        "search_queries_used": [],
    })
    return result.get("curated_videos", []), result.get("search_queries_used", [])

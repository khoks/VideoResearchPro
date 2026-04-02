import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
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
    """Execute YouTube searches and collect videos."""
    queries = state.get("search_queries_used", [state["topic"]])
    target = state["num_videos"]
    min_dur = state.get("min_duration")
    max_dur = state.get("max_duration")

    # Determine duration filter
    duration_filter = None
    if min_dur and min_dur >= 20:
        duration_filter = "long"
    elif max_dur and max_dur <= 4:
        duration_filter = "short"
    elif min_dur or max_dur:
        duration_filter = "medium"

    all_videos = {}
    for query in queries:
        results = youtube_service.search_videos(
            query=query,
            max_results=min(target, 25),
            video_duration=duration_filter,
        )
        for v in results:
            vid = v["video_id"]
            if vid not in all_videos:
                all_videos[vid] = v

        if len(all_videos) >= target * 2:
            break

    # Fetch detailed metadata (duration, etc.)
    video_ids = list(all_videos.keys())
    if video_ids:
        details = youtube_service.get_video_details(video_ids)
        for vid, detail in details.items():
            if vid in all_videos:
                all_videos[vid].update(detail)

    # Apply duration filters
    filtered = []
    for v in all_videos.values():
        dur_sec = v.get("duration_seconds", 0)
        dur_min = dur_sec / 60
        if min_dur and dur_min < min_dur:
            continue
        if max_dur and dur_min > max_dur:
            continue
        filtered.append(v)

    return {
        "discovered_videos": filtered,
        "messages": [HumanMessage(content=f"Found {len(filtered)} videos after filtering")],
    }


def rank_and_curate(state: SearchAgentState) -> dict:
    """Use LLM to rank and select the best videos."""
    videos = state.get("discovered_videos", [])
    target = state["num_videos"]

    if len(videos) <= target:
        return {"curated_videos": videos}

    llm = get_llm(temperature=0.0)
    video_list = "\n".join([
        f"- ID: {v['video_id']} | Title: {v.get('title', 'N/A')} | "
        f"Channel: {v.get('channel_name', 'N/A')} | "
        f"Duration: {format_duration(v.get('duration_seconds', 0))}"
        for v in videos
    ])

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
        pass

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
) -> list[dict]:
    """Run the search agent and return curated video list."""
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
    return result.get("curated_videos", [])

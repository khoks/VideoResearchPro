import json
import logging
import math

import tiktoken
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.report_prompts import COMPOSE_REPORT_PROMPT, MAP_CHUNK_PROMPT, REDUCE_PROMPT
from app.agents.state import ReportAgentState
from app.services.llm_service import get_llm
from app.config import settings
from app.utils.youtube_helpers import format_timestamp

logger = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text.split())


def compute_statistics(state: ReportAgentState) -> dict:
    """Compute statistics from transcript chunks."""
    chunks = state.get("transcript_chunks", [])

    total_words = 0
    total_duration = 0.0
    channels: dict[str, dict] = {}
    video_ids = set()

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        vid = meta.get("video_id", "")
        channel = meta.get("channel_name", "Unknown")
        words = meta.get("word_count", len(chunk.get("text", "").split()))
        ts_start = meta.get("timestamp_start", 0)
        ts_end = meta.get("timestamp_end", 0)

        total_words += words

        if vid not in video_ids:
            video_ids.add(vid)
            duration = ts_end  # approximate from last chunk's end
            if channel not in channels:
                channels[channel] = {"channel_name": channel, "video_count": 0, "word_count": 0, "minutes": 0}
            channels[channel]["video_count"] += 1

        if channel in channels:
            channels[channel]["word_count"] += words

    # Calculate total duration from unique videos
    for ch_data in channels.values():
        total_duration += ch_data.get("minutes", 0)

    # Rough total minutes from chunks
    if chunks:
        last_ends = {}
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            vid = meta.get("video_id", "")
            ts_end = meta.get("timestamp_end", 0)
            if vid not in last_ends or ts_end > last_ends[vid]:
                last_ends[vid] = ts_end
        total_minutes = round(sum(last_ends.values()) / 60)
        for ch_name, ch_data in channels.items():
            ch_vids = [c for c in chunks if c.get("metadata", {}).get("channel_name") == ch_name]
            ch_last_ends = {}
            for c in ch_vids:
                v = c["metadata"].get("video_id", "")
                te = c["metadata"].get("timestamp_end", 0)
                if v not in ch_last_ends or te > ch_last_ends[v]:
                    ch_last_ends[v] = te
            ch_data["minutes"] = round(sum(ch_last_ends.values()) / 60)
    else:
        total_minutes = 0

    statistics = {
        "video_count": len(video_ids),
        "transcript_count": len(video_ids),
        "total_words": total_words,
        "total_minutes": total_minutes,
        "channel_breakdown": list(channels.values()),
    }

    return {"statistics": statistics}


def map_chunks(state: ReportAgentState) -> dict:
    """Map: process transcript chunks in batches, extract structured data."""
    if state["job_type"] == "channel":
        return {"chunk_summaries": []}

    chunks = state.get("transcript_chunks", [])
    if not chunks:
        return {"chunk_summaries": []}

    llm = get_llm(temperature=0.0)
    max_context = settings.LLM_MAX_CONTEXT_TOKENS
    budget_per_batch = int(max_context * 0.6)

    # Group chunks into batches
    batches = []
    current_batch = []
    current_tokens = 0

    for chunk in chunks:
        text = chunk.get("text", "")
        meta = chunk.get("metadata", {})
        formatted = (
            f"[{meta.get('video_title', 'Unknown')} | {meta.get('channel_name', 'Unknown')} | "
            f"{format_timestamp(meta.get('timestamp_start', 0))}]\n{text}"
        )
        tokens = _count_tokens(formatted)

        if current_tokens + tokens > budget_per_batch and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(formatted)
        current_tokens += tokens

    if current_batch:
        batches.append(current_batch)

    # Process each batch
    summaries = []
    for i, batch in enumerate(batches):
        batch_text = "\n\n".join(batch)
        prompt = MAP_CHUNK_PROMPT.format(
            topic=state.get("topic", ""),
            chunks=batch_text,
        )

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            try:
                parsed = json.loads(response.content)
                summaries.append(parsed)
            except json.JSONDecodeError:
                summaries.append({"raw": response.content})
        except Exception as e:
            logger.warning(f"Map batch {i} failed: {e}")
            continue

    return {"chunk_summaries": summaries}


def reduce_summaries(state: ReportAgentState) -> dict:
    """Reduce: consolidate batch summaries into a single dataset."""
    summaries = state.get("chunk_summaries", [])
    if not summaries or state["job_type"] == "channel":
        return {"chunk_summaries": summaries}

    if len(summaries) == 1:
        return {}  # No reduction needed

    llm = get_llm(temperature=0.0)
    batch_text = json.dumps(summaries, indent=2, default=str)

    # If too large, reduce in pairs
    if _count_tokens(batch_text) > settings.LLM_MAX_CONTEXT_TOKENS * 0.6:
        reduced = []
        for i in range(0, len(summaries), 2):
            pair = summaries[i:i + 2]
            pair_text = json.dumps(pair, indent=2, default=str)
            prompt = REDUCE_PROMPT.format(
                topic=state.get("topic", ""),
                batch_summaries=pair_text,
            )
            try:
                response = llm.invoke([HumanMessage(content=prompt)])
                parsed = json.loads(response.content)
                reduced.append(parsed)
            except Exception:
                reduced.extend(pair)
        return {"chunk_summaries": reduced}

    prompt = REDUCE_PROMPT.format(
        topic=state.get("topic", ""),
        batch_summaries=batch_text,
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        parsed = json.loads(response.content)
        return {"chunk_summaries": [parsed]}
    except Exception:
        return {}


def compose_report(state: ReportAgentState) -> dict:
    """Compose the final HTML report body using LLM."""
    if state["job_type"] == "channel":
        return {"final_html": ""}

    summaries = state.get("chunk_summaries", [])
    statistics = state.get("statistics", {})

    if not summaries:
        return {"final_html": "<p>No transcript data available for analysis.</p>"}

    llm = get_llm(temperature=0.2, max_tokens=8000)
    consolidated = json.dumps(summaries[0] if len(summaries) == 1 else summaries, indent=2, default=str)

    prompt = COMPOSE_REPORT_PROMPT.format(
        topic=state.get("topic", ""),
        statistics=json.dumps(statistics, indent=2),
        consolidated_data=consolidated,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"final_html": response.content}
    except Exception as e:
        logger.error(f"Report composition failed: {e}")
        return {"final_html": f"<p>Report generation failed: {e}</p>"}


def should_skip_analysis(state: ReportAgentState) -> str:
    """Route: skip map/reduce/compose for channel jobs."""
    if state["job_type"] == "channel":
        return "format_html"
    return "map_chunks"


def build_report_graph() -> StateGraph:
    """Build the report agent LangGraph."""
    graph = StateGraph(ReportAgentState)
    graph.add_node("compute_statistics", compute_statistics)
    graph.add_node("map_chunks", map_chunks)
    graph.add_node("reduce_summaries", reduce_summaries)
    graph.add_node("compose_report", compose_report)

    graph.set_entry_point("compute_statistics")
    graph.add_conditional_edges("compute_statistics", should_skip_analysis,
                                {"map_chunks": "map_chunks", "format_html": END})
    graph.add_edge("map_chunks", "reduce_summaries")
    graph.add_edge("reduce_summaries", "compose_report")
    graph.add_edge("compose_report", END)

    return graph.compile()


def run_report_agent(
    job_type: str,
    topic: str,
    transcript_chunks: list[dict],
) -> tuple[dict, str]:
    """
    Run the report agent.

    Returns:
        (statistics_dict, report_html_body_or_empty_for_channel_jobs)
    """
    graph = build_report_graph()
    result = graph.invoke({
        "messages": [],
        "job_type": job_type,
        "topic": topic,
        "transcript_chunks": transcript_chunks,
        "chunk_summaries": [],
        "report_sections": {},
        "statistics": {},
        "final_html": "",
    })
    return result.get("statistics", {}), result.get("final_html", "")

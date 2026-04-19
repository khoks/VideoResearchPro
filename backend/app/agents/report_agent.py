import json
import logging

import tiktoken
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.report_prompts import (
    CHANNEL_COMPOSE_PROMPT,
    CHANNEL_MAP_PROMPT,
    COMPOSE_REPORT_PROMPT,
    MAP_CHUNK_PROMPT,
    REDUCE_PROMPT,
)
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
        logger.exception("Token counting via tiktoken failed; falling back to whitespace split")
        return len(text.split())


def compute_statistics(state: ReportAgentState) -> dict:
    """Compute statistics from transcript chunks in a single pass per metric."""
    chunks = state.get("transcript_chunks", [])

    if not chunks:
        statistics = {
            "video_count": 0,
            "transcript_count": 0,
            "total_words": 0,
            "total_minutes": 0,
            "channel_breakdown": [],
        }
        return {"statistics": statistics}

    total_words = 0
    channel_agg: dict[str, dict] = {}
    unique_videos: set[str] = set()
    last_ends: dict[str, float] = {}

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        vid = meta.get("video_id", "")
        channel = meta.get("channel_name", "Unknown")
        words = meta.get("word_count", len(chunk.get("text", "").split()))
        ts_end = meta.get("timestamp_end", 0) or 0

        total_words += words

        agg = channel_agg.get(channel)
        if agg is None:
            agg = {"videos": set(), "words": 0, "last_ends": {}}
            channel_agg[channel] = agg

        agg["words"] += words
        if vid:
            agg["videos"].add(vid)
            unique_videos.add(vid)
            if ts_end > agg["last_ends"].get(vid, 0):
                agg["last_ends"][vid] = ts_end
            if ts_end > last_ends.get(vid, 0):
                last_ends[vid] = ts_end

    total_minutes = round(sum(last_ends.values()) / 60) if last_ends else 0

    channel_breakdown = [
        {
            "channel_name": name,
            "video_count": len(agg["videos"]),
            "word_count": agg["words"],
            "minutes": round(sum(agg["last_ends"].values()) / 60) if agg["last_ends"] else 0,
        }
        for name, agg in channel_agg.items()
    ]

    statistics = {
        "video_count": len(unique_videos),
        "transcript_count": len(unique_videos),
        "total_words": total_words,
        "total_minutes": total_minutes,
        "channel_breakdown": channel_breakdown,
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
                logger.exception("Reduce pair failed; keeping raw pair")
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
        logger.exception("Reduce pass failed; leaving chunk_summaries unchanged")
        return {}


def compose_report(state: ReportAgentState) -> dict:
    """Compose the final HTML report body using LLM."""
    if state["job_type"] == "channel":
        return {"final_html": ""}

    summaries = state.get("chunk_summaries", [])
    statistics = state.get("statistics", {})

    if not summaries:
        return {"final_html": "<p>No transcript data available for analysis.</p>"}

    llm = get_llm(temperature=0.2, max_tokens=16000)
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


def _group_chunks_by_channel(chunks: list[dict]) -> dict[str, list[dict]]:
    """Group transcript chunks by channel_name."""
    by_channel: dict[str, list[dict]] = {}
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        channel = meta.get("channel_name", "Unknown")
        by_channel.setdefault(channel, []).append(chunk)
    return by_channel


def compose_channel_report(state: ReportAgentState) -> dict:
    """Lightweight map-then-compose narrative for channel jobs.

    1) For each channel, summarize dominant themes from a bounded sample of its chunks.
    2) Compose an HTML narrative across channels using the per-channel summaries.
    """
    chunks = state.get("transcript_chunks", [])
    statistics = state.get("statistics", {})

    if not chunks:
        return {"final_html": "<p>No transcript data available for this channel collection.</p>"}

    llm = get_llm(temperature=0.1)
    by_channel = _group_chunks_by_channel(chunks)
    budget_per_channel = int(settings.LLM_MAX_CONTEXT_TOKENS * 0.3)

    channel_summaries: list[dict] = []
    for channel_name, ch_chunks in by_channel.items():
        video_ids = {c.get("metadata", {}).get("video_id", "") for c in ch_chunks}
        video_ids.discard("")

        excerpt_parts: list[str] = []
        used_tokens = 0
        for c in ch_chunks:
            meta = c.get("metadata", {})
            piece = (
                f"[{meta.get('video_title', 'Unknown')} | "
                f"{format_timestamp(meta.get('timestamp_start', 0))}]\n{c.get('text', '')}"
            )
            piece_tokens = _count_tokens(piece)
            if used_tokens + piece_tokens > budget_per_channel and excerpt_parts:
                break
            excerpt_parts.append(piece)
            used_tokens += piece_tokens

        prompt = CHANNEL_MAP_PROMPT.format(
            channel_name=channel_name,
            video_count=len(video_ids),
            chunks="\n\n".join(excerpt_parts),
        )
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            try:
                parsed = json.loads(response.content)
            except json.JSONDecodeError:
                logger.warning("Channel map for %r returned non-JSON output", channel_name)
                parsed = {
                    "channel_name": channel_name,
                    "themes": [],
                    "highlights": [response.content.strip()[:500]],
                }
            parsed.setdefault("channel_name", channel_name)
            channel_summaries.append(parsed)
        except Exception:
            logger.exception("Channel map failed for channel %r", channel_name)
            channel_summaries.append({
                "channel_name": channel_name,
                "themes": [],
                "highlights": [],
            })

    compose_llm = get_llm(temperature=0.2, max_tokens=4000)
    compose_prompt = CHANNEL_COMPOSE_PROMPT.format(
        statistics=json.dumps(statistics, indent=2),
        channel_summaries=json.dumps(channel_summaries, indent=2, default=str),
    )
    try:
        response = compose_llm.invoke([HumanMessage(content=compose_prompt)])
        return {"final_html": response.content}
    except Exception as e:
        logger.exception("Channel report composition failed")
        return {"final_html": f"<p>Channel narrative generation failed: {e}</p>"}


def route_after_statistics(state: ReportAgentState) -> str:
    """Route: channel jobs go through the lightweight channel compose path."""
    if state["job_type"] == "channel":
        return "compose_channel_report"
    return "map_chunks"


def build_report_graph() -> StateGraph:
    """Build the report agent LangGraph."""
    graph = StateGraph(ReportAgentState)
    graph.add_node("compute_statistics", compute_statistics)
    graph.add_node("map_chunks", map_chunks)
    graph.add_node("reduce_summaries", reduce_summaries)
    graph.add_node("compose_report", compose_report)
    graph.add_node("compose_channel_report", compose_channel_report)

    graph.set_entry_point("compute_statistics")
    graph.add_conditional_edges(
        "compute_statistics",
        route_after_statistics,
        {
            "map_chunks": "map_chunks",
            "compose_channel_report": "compose_channel_report",
        },
    )
    graph.add_edge("map_chunks", "reduce_summaries")
    graph.add_edge("reduce_summaries", "compose_report")
    graph.add_edge("compose_report", END)
    graph.add_edge("compose_channel_report", END)

    return graph.compile()


def run_report_agent(
    job_type: str,
    topic: str,
    transcript_chunks: list[dict],
) -> tuple[dict, str]:
    """
    Run the report agent.

    Returns:
        (statistics_dict, report_html_body). For channel jobs the body is a
        lightweight per-channel narrative; for topic jobs it is the full
        research report composed from map-reduce summaries.
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

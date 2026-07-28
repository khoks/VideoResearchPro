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
from app.services.llm_service import get_llm_for
from app.services.llm_routing import context_window_for, resolve_config
from app.utils.youtube_helpers import format_timestamp

logger = logging.getLogger(__name__)

# S-1.12.5 (context-rot guard): even when the resolved model's window would
# hold more, batches above ~120K tokens degrade extraction recall over the
# middle of the context. Quality cap applies before the window-derived cap.
_QUALITY_BATCH_CAP = 120_000

# Fraction of the resolved model's measured input window usable for batch
# content — the rest is margin for prompt scaffolding, tokenizer drift
# (we count with cl100k, gpt-5.x bills o200k), and output headroom.
_WINDOW_SAFETY_FRACTION = 0.5

# Recursion bound for the reduce loop — 2^6 = 64× compression is beyond any
# realistic corpus; this is a runaway guard, not a sizing decision.
_MAX_REDUCE_ROUNDS = 6


def _count_tokens(text: str) -> int:
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        logger.exception("Token counting via tiktoken failed; falling back to whitespace split")
        return len(text.split())


def _batch_budget(use_case: str, fraction: float = _WINDOW_SAFETY_FRACTION) -> int:
    """Token budget for prompt content, derived from the RESOLVED model's
    measured context window (S-1.12.2 / D-052) — replaces the legacy
    model-blind ``LLM_MAX_CONTEXT_TOKENS`` global."""
    cfg = resolve_config(use_case)
    window = context_window_for(cfg.model)
    return min(int(window * fraction), _QUALITY_BATCH_CAP)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Hard-truncate ``text`` to ``max_tokens`` (cl100k count)."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    except Exception:
        return text[: max_tokens * 4]


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

    llm = get_llm_for("report_map_chunks", temperature=0.0, max_tokens=3000)
    budget_per_batch = _batch_budget("report_map_chunks")
    logger.info(
        "map_chunks: %d chunks, batch budget %d tokens (model %s)",
        len(chunks), budget_per_batch,
        resolve_config("report_map_chunks").model,
    )

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

    def _invoke_batch(batch_items: list[str]) -> dict | None:
        """One map call. Returns the parsed (or raw-wrapped) summary, or
        None on invocation failure."""
        prompt = MAP_CHUNK_PROMPT.format(
            topic=state.get("topic", ""),
            chunks="\n\n".join(batch_items),
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {"raw": response.content}

    # Process each batch with one level of bisect-retry (S-1.12.6): a
    # failed batch (context overflow, transient 4xx/5xx) is split in half
    # and each half retried before any content is declared lost.
    summaries = []
    failed_batches = 0
    dropped_chunk_groups = 0
    for i, batch in enumerate(batches):
        try:
            summaries.append(_invoke_batch(batch))
            continue
        except Exception as e:
            logger.warning(
                f"Map batch {i + 1}/{len(batches)} failed ({e}); "
                f"bisecting {len(batch)} chunks and retrying halves"
            )
        if len(batch) < 2:
            failed_batches += 1
            dropped_chunk_groups += len(batch)
            logger.error(f"Map batch {i + 1} unrecoverable (single chunk); content dropped")
            continue
        mid = len(batch) // 2
        for half_idx, half in enumerate((batch[:mid], batch[mid:])):
            try:
                summaries.append(_invoke_batch(half))
            except Exception as e2:
                failed_batches += 1
                dropped_chunk_groups += len(half)
                logger.error(
                    f"Map batch {i + 1} half {half_idx + 1} failed after bisect ({e2}); "
                    f"{len(half)} chunks dropped from the report"
                )

    notes = dict(state.get("processing_notes") or {})
    notes.update(
        {
            "map_batches": len(batches),
            "map_batches_failed": failed_batches,
            "map_chunks_dropped": dropped_chunk_groups,
            "map_chunks_total": len(chunks),
        }
    )
    if failed_batches:
        logger.error(
            "map_chunks: %d batch(es) failed permanently; ~%d of %d chunks "
            "excluded from the report",
            failed_batches, dropped_chunk_groups, len(chunks),
        )
    return {"chunk_summaries": summaries, "processing_notes": notes}


def reduce_summaries(state: ReportAgentState) -> dict:
    """Reduce: recursively consolidate batch summaries into ONE dataset.

    S-1.12.3: pairwise rounds repeat until the working set fits the final
    merge budget, then a single merge call produces exactly one summary.
    No path passes unbounded raw content downstream — failed pairs are
    token-truncated instead of kept whole, so compose input is always
    bounded by the smaller of the reduce/compose budgets.
    """
    summaries = state.get("chunk_summaries", [])
    if not summaries or state["job_type"] == "channel":
        return {"chunk_summaries": summaries}

    if len(summaries) == 1:
        return {}  # No reduction needed

    llm = get_llm_for("report_reduce_summaries", temperature=0.0, max_tokens=6000)
    # The merged output must fit COMPOSE's prompt too, so target the
    # tighter of the two budgets.
    target_budget = min(
        _batch_budget("report_reduce_summaries", fraction=0.6),
        _batch_budget("report_compose", fraction=0.6),
    )

    def _merge_call(items: list) -> dict:
        prompt = REDUCE_PROMPT.format(
            topic=state.get("topic", ""),
            batch_summaries=json.dumps(items, indent=2, default=str),
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        return json.loads(response.content)

    current = list(summaries)
    rounds = 0
    while rounds < _MAX_REDUCE_ROUNDS:
        total_tokens = _count_tokens(json.dumps(current, indent=2, default=str))
        if total_tokens <= target_budget:
            break
        rounds += 1
        logger.info(
            "reduce_summaries: round %d — %d summaries / %d tokens over "
            "budget %d; pairwise merging",
            rounds, len(current), total_tokens, target_budget,
        )
        merged_round: list = []
        per_item_cap = max(2_000, target_budget // max(4, len(current)))
        for i in range(0, len(current), 2):
            pair = current[i:i + 2]
            if len(pair) == 1:
                merged_round.append(pair[0])
                continue
            try:
                merged_round.append(_merge_call(pair))
            except Exception:
                # Never pass unbounded raw content on — truncate each
                # member to its share of the budget and keep going.
                logger.exception(
                    "Reduce pair failed; keeping token-truncated members"
                )
                for member in pair:
                    truncated = _truncate_to_tokens(
                        json.dumps(member, default=str), per_item_cap
                    )
                    merged_round.append({"truncated_summary": truncated})
        current = merged_round

    if len(current) == 1:
        return {"chunk_summaries": current}

    # Final merge into exactly one summary.
    try:
        return {"chunk_summaries": [_merge_call(current)]}
    except Exception:
        logger.exception(
            "Final reduce merge failed; passing %d bounded summaries to compose",
            len(current),
        )
        # Bounded by construction (the loop above), so this is safe.
        return {"chunk_summaries": current}


def compose_report(state: ReportAgentState) -> dict:
    """Compose the final HTML report body using LLM."""
    if state["job_type"] == "channel":
        return {"final_html": ""}

    summaries = state.get("chunk_summaries", [])
    statistics = state.get("statistics", {})

    notes = state.get("processing_notes") or {}

    if not summaries:
        detail = ""
        if notes.get("map_batches_failed"):
            detail = (
                f" All {notes['map_batches']} analysis batches failed — "
                "see worker logs (likely a model/context configuration issue)."
            )
        return {"final_html": f"<p>No transcript data available for analysis.{detail}</p>"}

    llm = get_llm_for("report_compose", temperature=0.2, max_tokens=16000)
    consolidated = json.dumps(summaries[0] if len(summaries) == 1 else summaries, indent=2, default=str)

    # Last-line guard (S-1.12.2): never send compose an over-budget prompt.
    compose_budget = _batch_budget("report_compose", fraction=0.6)
    consolidated_tokens = _count_tokens(consolidated)
    if consolidated_tokens > compose_budget:
        logger.warning(
            "compose_report: consolidated data %d tokens exceeds budget %d; truncating",
            consolidated_tokens, compose_budget,
        )
        consolidated = _truncate_to_tokens(consolidated, compose_budget)

    prompt = COMPOSE_REPORT_PROMPT.format(
        topic=state.get("topic", ""),
        statistics=json.dumps(statistics, indent=2),
        consolidated_data=consolidated,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        html = response.content
    except Exception as e:
        logger.error(f"Report composition failed: {e}")
        return {"final_html": f"<p>Report generation failed: {e}</p>"}

    # S-1.12.4: loud accounting — any content dropped upstream is disclosed
    # in the report itself, not just in worker logs.
    if notes.get("map_chunks_dropped"):
        html += (
            "\n<p style=\"color:#8a6d3b;border:1px solid #c9ba9b;padding:8px 12px;"
            "border-radius:4px;margin-top:24px\"><strong>Processing note:</strong> "
            f"{notes['map_chunks_dropped']} of {notes.get('map_chunks_total', '?')} "
            "transcript segments could not be analyzed "
            f"({notes.get('map_batches_failed', 0)} failed batch(es) after retry) "
            "and are not reflected in this report.</p>"
        )
    return {"final_html": html}


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

    llm = get_llm_for("report_channel", temperature=0.1, max_tokens=6000)
    by_channel = _group_chunks_by_channel(chunks)
    budget_per_channel = _batch_budget("report_channel", fraction=0.3)

    channel_summaries: list[dict] = []
    for channel_name, ch_chunks in by_channel.items():
        video_ids = {c.get("metadata", {}).get("video_id", "") for c in ch_chunks}
        video_ids.discard("")

        excerpt_parts: list[str] = []
        used_tokens = 0
        skipped_chunks = 0
        for c in ch_chunks:
            meta = c.get("metadata", {})
            piece = (
                f"[{meta.get('video_title', 'Unknown')} | "
                f"{format_timestamp(meta.get('timestamp_start', 0))}]\n{c.get('text', '')}"
            )
            piece_tokens = _count_tokens(piece)
            if used_tokens + piece_tokens > budget_per_channel and excerpt_parts:
                skipped_chunks = len(ch_chunks) - len(excerpt_parts)
                break
            excerpt_parts.append(piece)
            used_tokens += piece_tokens
        if skipped_chunks:
            # S-1.12.4: never truncate silently.
            logger.warning(
                "compose_channel_report: channel %r excerpt capped at %d tokens — "
                "%d of %d chunks excluded from its summary",
                channel_name, budget_per_channel, skipped_chunks, len(ch_chunks),
            )

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

    compose_llm = get_llm_for("report_compose_channel_section", temperature=0.2, max_tokens=4000)
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
        "processing_notes": {},
    })
    return result.get("statistics", {}), result.get("final_html", "")

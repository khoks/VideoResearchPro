"""Per-video knowledge extraction LangGraph agent (Unit 4).

Flow:
  split_transcript  — token-budget batches of the full transcript
  extract_per_batch — LLM → structured JSON per batch
  merge_extractions — dedupe union across batches
  synthesize_report — LLM → Markdown report over merged + transcript

Used by the knowledge router to produce and persist on-demand per-video
knowledge artifacts on the `videos` row.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import tiktoken
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.knowledge_prompts import (
    EXTRACT_BATCH_PROMPT,
    SYNTHESIZE_REPORT_PROMPT,
)
from app.agents.state import KnowledgeAgentState
from app.config import settings
from app.services.llm_service import get_llm_for

logger = logging.getLogger(__name__)


_KNOWLEDGE_KEYS = ("topics", "concepts", "events", "facts")


def _count_tokens(text: str) -> int:
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        logger.exception("Token counting via tiktoken failed; falling back to whitespace split")
        return len(text.split())


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate `text` to roughly `max_tokens` using cl100k_base encoding."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    except Exception:
        logger.exception("Token truncation failed; falling back to char slice")
        # Rough: 4 chars per token.
        return text[: max_tokens * 4]


def split_transcript(state: KnowledgeAgentState) -> dict:
    """Split the full transcript into batches under `KNOWLEDGE_EXTRACT_BATCH_TOKENS`.

    Splits on paragraph breaks first (preserves semantic boundaries), then
    falls back to whitespace words if a single paragraph exceeds the budget.
    The total transcript is capped at `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` so
    pathologically long videos don't blow up the LLM budget.
    """
    text = state.get("full_transcript_text", "") or ""
    if not text.strip():
        return {"transcript_batches": []}

    text = _truncate_to_tokens(text, settings.KNOWLEDGE_MAX_TRANSCRIPT_TOKENS)

    budget = max(int(settings.KNOWLEDGE_EXTRACT_BATCH_TOKENS), 500)

    # Prefer paragraph boundaries; fall back to single-line / word-level split
    # only for paragraphs larger than the budget.
    units: list[str] = []
    for para in text.split("\n\n"):
        p = para.strip()
        if not p:
            continue
        if _count_tokens(p) <= budget:
            units.append(p)
            continue
        # Paragraph itself is too big — split on whitespace into word chunks.
        words = p.split()
        current: list[str] = []
        current_tokens = 0
        for w in words:
            wt = _count_tokens(w + " ")
            if current_tokens + wt > budget and current:
                units.append(" ".join(current))
                current = []
                current_tokens = 0
            current.append(w)
            current_tokens += wt
        if current:
            units.append(" ".join(current))

    # Pack units into batches up to the budget.
    batches: list[str] = []
    current_batch: list[str] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = _count_tokens(unit)
        if current_tokens + unit_tokens > budget and current_batch:
            batches.append("\n\n".join(current_batch))
            current_batch = []
            current_tokens = 0
        current_batch.append(unit)
        current_tokens += unit_tokens

    if current_batch:
        batches.append("\n\n".join(current_batch))

    logger.info(
        "Knowledge agent split transcript (video_id=%s) into %d batch(es)",
        state.get("video_id", ""), len(batches),
    )
    return {"transcript_batches": batches}


def _parse_extraction(raw: str) -> dict:
    """Parse a JSON extraction from LLM output; tolerate code fences."""
    content = (raw or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        end = -1 if lines and lines[-1].startswith("```") else len(lines)
        content = "\n".join(lines[1:end])

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Knowledge extraction batch returned non-JSON: %r", content[:200])
        return {k: [] for k in _KNOWLEDGE_KEYS}

    if not isinstance(data, dict):
        return {k: [] for k in _KNOWLEDGE_KEYS}

    out: dict[str, list[str]] = {}
    for key in _KNOWLEDGE_KEYS:
        val = data.get(key, [])
        if not isinstance(val, list):
            out[key] = []
            continue
        items: list[str] = []
        for item in val:
            if not isinstance(item, (str, int, float)):
                continue
            s = str(item).strip()
            if s:
                items.append(s)
        out[key] = items
    return out


def extract_per_batch(state: KnowledgeAgentState) -> dict:
    """Map: ask the LLM to extract structured knowledge from each batch."""
    batches = state.get("transcript_batches", []) or []
    if not batches:
        return {"per_batch_extractions": []}

    llm = get_llm_for("knowledge_extract_batch", temperature=0.0)
    video_title = state.get("video_title", "") or "Unknown"
    channel_name = state.get("channel_name", "") or "Unknown"

    extractions: list[dict] = []
    for i, batch_text in enumerate(batches):
        prompt = EXTRACT_BATCH_PROMPT.format(
            video_title=video_title,
            channel_name=channel_name,
            batch_text=batch_text,
        )
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            parsed = _parse_extraction(response.content)
        except Exception:
            logger.exception("Knowledge extract batch %d failed; continuing", i)
            parsed = {k: [] for k in _KNOWLEDGE_KEYS}
        extractions.append(parsed)

    return {"per_batch_extractions": extractions}


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        s = raw.strip()
        if not s:
            continue
        # Case-insensitive dedupe key; keep first-seen casing.
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def merge_extractions(state: KnowledgeAgentState) -> dict:
    """Reduce: union across batches, deduping each list case-insensitively."""
    extractions = state.get("per_batch_extractions", []) or []
    merged: dict[str, list[str]] = {k: [] for k in _KNOWLEDGE_KEYS}
    for extraction in extractions:
        if not isinstance(extraction, dict):
            continue
        for key in _KNOWLEDGE_KEYS:
            vals = extraction.get(key, [])
            if isinstance(vals, list):
                merged[key].extend(str(v) for v in vals if v)

    deduped = {k: _dedupe_preserve_order(merged[k]) for k in _KNOWLEDGE_KEYS}
    return {"merged_extraction": deduped}


def synthesize_report(state: KnowledgeAgentState) -> dict:
    """Compose the final Markdown knowledge document from merged + transcript."""
    merged = state.get("merged_extraction") or {k: [] for k in _KNOWLEDGE_KEYS}
    full_transcript = state.get("full_transcript_text", "") or ""
    # Give the synthesis LLM a bounded transcript view (same cap as splitter).
    transcript_for_prompt = _truncate_to_tokens(
        full_transcript, settings.KNOWLEDGE_MAX_TRANSCRIPT_TOKENS
    )

    if not any(merged.get(k) for k in _KNOWLEDGE_KEYS) and not transcript_for_prompt.strip():
        return {"knowledge_report_md": ""}

    llm = get_llm_for(
        "knowledge_synthesize_report",
        temperature=0.2,
        max_tokens=8000,
    )
    prompt = SYNTHESIZE_REPORT_PROMPT.format(
        video_title=state.get("video_title", "") or "Unknown",
        channel_name=state.get("channel_name", "") or "Unknown",
        merged_extraction_json=json.dumps(merged, ensure_ascii=False, indent=2),
        full_transcript_text=transcript_for_prompt,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        md = (response.content or "").strip()
        # Strip a surrounding code fence the model might add despite instructions.
        if md.startswith("```"):
            lines = md.splitlines()
            end = -1 if lines and lines[-1].startswith("```") else len(lines)
            md = "\n".join(lines[1:end]).strip()
        return {"knowledge_report_md": md}
    except Exception:
        logger.exception("Knowledge synthesis failed")
        return {"knowledge_report_md": ""}


def build_knowledge_graph():
    """Build and compile the knowledge extraction LangGraph."""
    graph = StateGraph(KnowledgeAgentState)
    graph.add_node("split_transcript", split_transcript)
    graph.add_node("extract_per_batch", extract_per_batch)
    graph.add_node("merge_extractions", merge_extractions)
    graph.add_node("synthesize_report", synthesize_report)

    graph.set_entry_point("split_transcript")
    graph.add_edge("split_transcript", "extract_per_batch")
    graph.add_edge("extract_per_batch", "merge_extractions")
    graph.add_edge("merge_extractions", "synthesize_report")
    graph.add_edge("synthesize_report", END)

    return graph.compile()


def run_knowledge_extract_agent(video: Any, full_transcript_text: str) -> dict:
    """Run the knowledge agent for one video.

    Args:
        video: the `Video` ORM row (used for title + channel_name).
        full_transcript_text: the full transcript as a single string.

    Returns:
        {
          "topics": list[str],
          "concepts": list[str],
          "events": list[str],
          "facts": list[str],
          "knowledge_report_md": str,
        }
    """
    video_id = getattr(video, "video_id", "") or ""
    video_title = getattr(video, "title", "") or ""
    # `video.channel_name` is a property that joins through `channel` and may
    # raise if the relationship isn't loaded; fall back to "" on any error.
    try:
        channel_name = getattr(video, "channel_name", "") or ""
    except Exception:
        channel_name = ""

    graph = build_knowledge_graph()
    result = graph.invoke({
        "messages": [],
        "video_id": video_id,
        "video_title": video_title,
        "channel_name": channel_name,
        "full_transcript_text": full_transcript_text or "",
        "transcript_batches": [],
        "per_batch_extractions": [],
        "merged_extraction": {},
        "knowledge_report_md": "",
    })

    merged = result.get("merged_extraction") or {k: [] for k in _KNOWLEDGE_KEYS}
    return {
        "topics": list(merged.get("topics", [])),
        "concepts": list(merged.get("concepts", [])),
        "events": list(merged.get("events", [])),
        "facts": list(merged.get("facts", [])),
        "knowledge_report_md": result.get("knowledge_report_md", "") or "",
    }

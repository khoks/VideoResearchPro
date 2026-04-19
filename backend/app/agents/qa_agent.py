import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.qa_prompts import (
    QA_ANSWER_PROMPT,
    QA_SYSTEM_PROMPT,
    REFINE_CONTEXT_PROMPT,
    SUB_QUERY_EXPANSION_PROMPT,
    USED_SOURCES_PROMPT,
)
from app.agents.state import QAAgentState
from app.config import settings
from app.services import chroma_service
from app.services.llm_service import get_llm
from app.utils.youtube_helpers import build_youtube_url, format_timestamp

logger = logging.getLogger(__name__)

REPORT_CONTEXT_CHAR_CAP = 50000


def _generate_sub_queries(question: str) -> list[str]:
    """Ask the LLM for 2 semantically-focused sub-queries to broaden retrieval."""
    llm = get_llm(temperature=0.0)
    prompt = SUB_QUERY_EXPANSION_PROMPT.format(question=question)
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = (response.content or "").strip()
    except Exception:
        logger.exception("Sub-query expansion LLM call failed; falling back to original question only")
        return []

    lines = [line.strip(" -*\t") for line in raw.splitlines() if line.strip()]
    # Drop any line that is just echoing the original question
    sub_queries = [line for line in lines if line.lower() != question.lower()]
    return sub_queries[:2]


def retrieve_context(state: QAAgentState) -> dict:
    """Retrieve relevant chunks from ChromaDB using multi-query expansion, plus extract report text."""
    job_id = state.get("job_id", "")
    question = state["question"]

    # Multi-query expansion: original question + up to 2 LLM-generated sub-queries.
    sub_queries = _generate_sub_queries(question)
    all_queries = [question] + sub_queries
    logger.info(f"[job:{job_id}] Q&A retrieval using {len(all_queries)} queries")

    # Retrieve per query and dedupe by chunk id (video_id + timestamp + chunk_index).
    merged: dict[str, dict] = {}
    for q in all_queries:
        results = chroma_service.query_collection(job_id, q, n_results=settings.RAG_TOP_K)
        for r in results:
            meta = r.get("metadata", {})
            key = (
                f"{meta.get('video_id', '')}"
                f"_{meta.get('chunk_index', '')}"
                f"_{meta.get('timestamp_start', '')}"
            )
            existing = merged.get(key)
            if existing is None or r.get("distance", 1.0) < existing.get("distance", 1.0):
                merged[key] = r

    rag_results = sorted(merged.values(), key=lambda x: x.get("distance", 1.0))

    # Enrich with formatted data
    for r in rag_results:
        meta = r.get("metadata", {})
        ts = float(meta.get("timestamp_start", 0))
        vid = meta.get("video_id", "")
        r["timestamp_display"] = format_timestamp(ts)
        r["youtube_link"] = build_youtube_url(vid, ts)

    # Extract clean text from HTML report
    report_context = None
    if state.get("job_type") == "topic" and state.get("report_html"):
        report_html = state["report_html"]
        clean = re.sub(r'<style[^>]*>.*?</style>', '', report_html, flags=re.DOTALL)
        clean = re.sub(r'<script[^>]*>.*?</script>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if len(clean) > REPORT_CONTEXT_CHAR_CAP:
            clean = clean[:REPORT_CONTEXT_CHAR_CAP] + "..."
        report_context = clean

    return {
        "sub_queries": sub_queries,
        "rag_results": rag_results,
        "report_context": report_context,
    }


def refine_context(state: QAAgentState) -> dict:
    """Use LLM to extract only the relevant passages from RAG + report context."""
    llm = get_llm(temperature=0.0)
    question = state["question"]
    rag_results = state.get("rag_results", [])
    report_context = state.get("report_context")

    # Format raw RAG chunks with source attribution
    raw_parts = []
    for i, r in enumerate(rag_results):
        meta = r.get("metadata", {})
        raw_parts.append(
            f"[Chunk {i+1} | Video: \"{meta.get('video_title', 'Unknown')}\" "
            f"by {meta.get('channel_name', 'Unknown')} at {r.get('timestamp_display', '0:00')}]\n"
            f"{r.get('text', '')}"
        )
    raw_rag = "\n\n".join(raw_parts) if raw_parts else ""

    raw_report = ""
    if report_context:
        raw_report = f"\n\n=== RESEARCH REPORT ===\n{report_context}"

    prompt = REFINE_CONTEXT_PROMPT.format(
        question=question,
        raw_context=raw_rag + raw_report,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    refined = response.content.strip()

    logger.info(f"Refined context: {len(refined)} chars from {len(raw_rag) + len(raw_report)} chars raw")

    return {"refined_context": refined}


def formulate_answer(state: QAAgentState) -> dict:
    """Generate answer using LLM with refined context."""
    llm = get_llm(temperature=0.1)

    prompt = QA_ANSWER_PROMPT.format(
        question=state["question"],
        refined_context=state.get("refined_context", "No context available."),
    )

    response = llm.invoke([
        SystemMessage(content=QA_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])

    return {"answer": response.content}


def _chunk_to_reference(chunk: dict) -> tuple[str, dict]:
    """Build a (dedupe_key, reference_dict) pair from a RAG chunk."""
    meta = chunk.get("metadata", {})
    vid = meta.get("video_id", "")
    ts = float(meta.get("timestamp_start", 0))
    key = f"{vid}_{int(ts)}"
    ref = {
        "video_url": meta.get("video_url", build_youtube_url(vid)),
        "video_title": meta.get("video_title", "Unknown") or "Unknown",
        "channel_name": meta.get("channel_name", "Unknown"),
        "timestamp_seconds": ts,
        "timestamp_display": format_timestamp(ts),
        "youtube_link": build_youtube_url(vid, ts),
    }
    return key, ref


def _title_variants(title: str) -> list[str]:
    """Yield normalized title forms the LLM might paraphrase to.

    LLMs often drop leading numbers ("8 Pragmatic Tips" -> "Pragmatic Tips") or
    parenthetical suffixes ("Tips (From Real Projects)" -> "Tips"). Generate a
    small handful of variants and let the matcher try each.
    """
    variants: list[str] = []
    base = title.strip()
    if base:
        variants.append(base)
    # Strip leading number / numeral prefix: "8 Foo", "10. Foo"
    stripped = re.sub(r'^\s*\d+[.\):\s-]*', '', base).strip()
    if stripped and stripped != base:
        variants.append(stripped)
    # Drop parenthetical/bracketed suffix: "Foo (From Real Projects)"
    no_paren = re.sub(r'\s*[\(\[].*?[\)\]]\s*$', '', stripped or base).strip()
    if no_paren and no_paren not in variants:
        variants.append(no_paren)
    # Drop trailing tagline after " - " or " | ": "Foo - A Deep Dive"
    no_tagline = re.split(r'\s+[-|–—]\s+', no_paren or stripped or base)[0].strip()
    if no_tagline and no_tagline not in variants:
        variants.append(no_tagline)
    return variants


def _channel_in_answer(channel: str, answer_lower: str) -> bool:
    """Match a channel name in the answer, ignoring trailing diacritics on the last token.

    Whisper / YouTube responses sometimes mojibake non-ASCII channel names
    (e.g. "Jovanović" -> garbled bytes). Match by ASCII-only substring fallback.
    """
    if not channel or len(channel) < 4:
        return False
    if channel.lower() in answer_lower:
        return True
    ascii_channel = re.sub(r'[^\x00-\x7f]+', '', channel).strip()
    if len(ascii_channel) >= 4 and ascii_channel.lower() in answer_lower:
        return True
    return False


def _references_from_citations(rag_results: list[dict], answer: str) -> list[dict]:
    """Deterministic: match video_ids / titles / channel names appearing in the answer.

    The LLM's `[Source: "<title>" by <channel> at <ts>]` citations are not always
    verbatim — it may strip leading numbers, parentheticals, or rephrase. So we
    accept any title variant or a channel-name + title-keyword co-occurrence.
    """
    answer_lower = answer.lower()
    references: list[dict] = []
    seen: set[str] = set()
    for r in rag_results:
        meta = r.get("metadata", {})
        vid = meta.get("video_id", "") or ""
        title = meta.get("video_title", "") or ""
        channel = meta.get("channel_name", "") or ""

        vid_match = bool(vid) and vid.lower() in answer_lower
        title_match = any(
            len(v) >= 10 and v.lower() in answer_lower
            for v in _title_variants(title)
        )
        # Fallback: channel name appears AND at least one significant (>=5 char)
        # title word also appears — strong signal the citation refers to this video.
        channel_match = False
        if not (vid_match or title_match) and _channel_in_answer(channel, answer_lower):
            keywords = [w.lower() for w in re.findall(r'\b[A-Za-z]{5,}\b', title)]
            if any(k in answer_lower for k in keywords):
                channel_match = True

        if not (vid_match or title_match or channel_match):
            continue
        key, ref = _chunk_to_reference(r)
        if key in seen:
            continue
        seen.add(key)
        references.append(ref)
    return references


def _references_via_llm(rag_results: list[dict], answer: str) -> list[dict]:
    """Ask the LLM which candidate chunks were actually used in the answer."""
    candidates = rag_results[:20]
    if not candidates:
        return []

    lines = [
        f"{i} | {r.get('metadata', {}).get('video_id', '')} | "
        f"{r.get('metadata', {}).get('video_title', 'Unknown')}"
        for i, r in enumerate(candidates)
    ]
    prompt = USED_SOURCES_PROMPT.format(answer=answer, chunks="\n".join(lines))

    llm = get_llm(temperature=0.0)
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = (response.content or "").strip()
    except Exception:
        logger.exception("Used-sources LLM call failed; returning no LLM-picked refs")
        return []

    # Strip any code fences the model might add despite instructions.
    if content.startswith("```"):
        content_lines = content.splitlines()
        content = "\n".join(
            content_lines[1:-1] if content_lines[-1].startswith("```") else content_lines[1:]
        )

    try:
        indices = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"Used-sources LLM returned non-JSON content: {content[:200]!r}")
        return []

    if not isinstance(indices, list):
        return []

    references: list[dict] = []
    seen: set[str] = set()
    for idx in indices:
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
            continue
        key, ref = _chunk_to_reference(candidates[idx])
        if key in seen:
            continue
        seen.add(key)
        references.append(ref)
    return references


def extract_references(state: QAAgentState) -> dict:
    """Extract structured references from RAG results actually used in the answer.

    Prefers an exact-match pass over `[Source: ...]` style citations / video_id
    substrings; falls back to an LLM auditor if nothing is matched
    deterministically.
    """
    rag_results = state.get("rag_results", [])
    answer = state.get("answer", "") or ""

    if not rag_results or not answer:
        return {"references": []}

    references = _references_from_citations(rag_results, answer)
    if not references:
        references = _references_via_llm(rag_results, answer)

    return {"references": references[:10]}


def build_qa_graph() -> StateGraph:
    """Build the Q&A agent LangGraph."""
    graph = StateGraph(QAAgentState)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("refine_context", refine_context)
    graph.add_node("formulate_answer", formulate_answer)
    graph.add_node("extract_references", extract_references)

    graph.set_entry_point("retrieve_context")
    graph.add_edge("retrieve_context", "refine_context")
    graph.add_edge("refine_context", "formulate_answer")
    graph.add_edge("formulate_answer", "extract_references")
    graph.add_edge("extract_references", END)

    return graph.compile()


def run_qa_agent(
    job_id: str,
    job_type: str,
    question: str,
    report_html: str | None = None,
) -> tuple[str, list[dict]]:
    """
    Run the Q&A agent.

    Returns:
        (answer_text, references_list)
    """
    graph = build_qa_graph()
    result = graph.invoke({
        "messages": [],
        "job_id": job_id,
        "job_type": job_type,
        "question": question,
        "report_html": report_html or "",
        "sub_queries": [],
        "rag_results": [],
        "report_context": None,
        "refined_context": "",
        "answer": "",
        "references": [],
    })
    return result.get("answer", ""), result.get("references", [])

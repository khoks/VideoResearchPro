import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.qa_prompts import (
    QA_ANSWER_PROMPT,
    QA_SYSTEM_PROMPT,
    REFINE_CONTEXT_PROMPT,
)
from app.agents.state import QAAgentState
from app.services import chroma_service
from app.services.llm_service import get_llm
from app.utils.youtube_helpers import build_youtube_url, format_timestamp

logger = logging.getLogger(__name__)


def retrieve_context(state: QAAgentState) -> dict:
    """Retrieve relevant chunks from ChromaDB and extract report text."""
    job_id = state.get("job_id", "")
    question = state["question"]

    rag_results = chroma_service.query_collection(job_id, question, n_results=15)

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
        if len(clean) > 15000:
            clean = clean[:15000] + "..."
        report_context = clean

    return {
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


def extract_references(state: QAAgentState) -> dict:
    """Extract structured references from RAG results used in the answer."""
    rag_results = state.get("rag_results", [])
    answer = state.get("answer", "")

    references = []
    seen = set()
    for r in rag_results[:10]:
        meta = r.get("metadata", {})
        vid = meta.get("video_id", "")
        ts = float(meta.get("timestamp_start", 0))
        key = f"{vid}_{int(ts)}"
        if key in seen:
            continue
        seen.add(key)

        # Only include references for videos mentioned in the answer
        video_title = meta.get("video_title", "Unknown")
        if video_title.lower()[:20] in answer.lower() or len(references) < 5:
            references.append({
                "video_url": meta.get("video_url", build_youtube_url(vid)),
                "video_title": video_title,
                "channel_name": meta.get("channel_name", "Unknown"),
                "timestamp_seconds": ts,
                "timestamp_display": format_timestamp(ts),
                "youtube_link": build_youtube_url(vid, ts),
            })

    return {"references": references}


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
        "rag_results": [],
        "report_context": None,
        "refined_context": "",
        "answer": "",
        "references": [],
    })
    return result.get("answer", ""), result.get("references", [])

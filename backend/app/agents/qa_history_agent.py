"""Q&A History chat agent (Unit 2 — Personal Wiki).

``run_qa_history_chat_agent(question, answer_language="en")`` answers
meta-questions across every Q&A the user has ever had. The RAG source is
the central ``qa_library_global`` ChromaDB collection (populated by Unit 1),
where each document is a single Q&A pair with metadata identifying whether
it came from a job, the library-wide Q&A page, or a prior history chat.

Structure mirrors ``run_library_qa_agent`` in ``app.agents.qa_agent``:
retrieve → refine → formulate → return. The flow is intentionally linear
(no LangGraph here) because the chain is short and the per-node state would
add more noise than clarity.
"""

from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts.qa_history_prompts import (
    QA_HISTORY_ANSWER_PROMPT,
    QA_HISTORY_REFINE_CONTEXT_PROMPT,
    QA_HISTORY_SYSTEM_PROMPT,
)
from app.config import settings
from app.services import chroma_service
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)

# Max characters from each past Q&A that we feed into the refine step.
# Keeps the raw context manageable when a past answer was several thousand
# characters long (multi-section reports).
_MAX_ANSWER_CHARS = 1500

_QUESTION_PREVIEW_CHARS = 80

_DEFAULT_TOP_K = 8


def _truncate(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "..."


def _question_preview(question: str) -> str:
    return _truncate(question, _QUESTION_PREVIEW_CHARS)


def _retrieve_past_exchanges(question: str, n_results: int) -> list[dict]:
    """Query the central Q&A collection for exchanges relevant to ``question``.

    Returns the raw chunks from chroma. If Unit 1 hasn't landed yet, or the
    collection is empty, returns ``[]``.
    """
    try:
        return chroma_service.query_qa_collection(
            question,
            top_k=n_results,
        )
    except AttributeError:
        logger.warning(
            "chroma_service.query_qa_collection not available yet "
            "(Unit 1 pending); returning no results."
        )
        return []
    except Exception:
        logger.exception("query_qa_collection failed; returning no results")
        return []


def _dedupe_by_exchange_id(chunks: list[dict]) -> list[dict]:
    """Keep the closest-distance chunk per exchange_id."""
    merged: dict[str, dict] = {}
    for r in chunks:
        meta = r.get("metadata", {}) or {}
        key = str(meta.get("exchange_id") or r.get("id") or "")
        if not key:
            continue
        existing = merged.get(key)
        if existing is None or r.get("distance", 1.0) < existing.get("distance", 1.0):
            merged[key] = r
    return sorted(merged.values(), key=lambda x: x.get("distance", 1.0))


def _extract_question_and_answer(document: str) -> tuple[str, str]:
    """Split a stored Q&A document back into (question, answer).

    Unit 1 writes each document as ``"Q: {question}\n\nA: {answer}"``. If the
    format ever drifts, we fall back to returning the whole document as the
    answer so nothing is lost.
    """
    if not document:
        return "", ""
    # Match "Q:" optionally preceded by whitespace, up to the "A:" marker.
    match = re.match(
        r"^\s*Q:\s*(?P<q>.*?)\n\s*A:\s*(?P<a>.*)$",
        document,
        flags=re.DOTALL,
    )
    if match:
        return match.group("q").strip(), match.group("a").strip()
    return "", document.strip()


def _build_reference(chunk: dict, stored_question: str) -> dict:
    """Build the reference dict shape consumed by the router/frontend."""
    meta = chunk.get("metadata", {}) or {}
    job_id = meta.get("job_id")
    if job_id is not None:
        job_id = str(job_id) or None
    return {
        "source_type": str(meta.get("source") or "history"),
        "exchange_id": str(meta.get("exchange_id") or ""),
        "question_preview": _question_preview(stored_question),
        "job_id": job_id or None,
        "original_created_at": str(
            meta.get("created_at_iso") or meta.get("created_at") or ""
        ),
    }


def _build_allowed_sources(refs: list[dict]) -> str:
    """Render the allow-list of exchanges the LLM may cite."""
    seen: set[str] = set()
    lines: list[str] = []
    for r in refs:
        eid = r["exchange_id"]
        if not eid or eid in seen:
            continue
        seen.add(eid)
        preview = r.get("question_preview") or ""
        stype = r.get("source_type") or "history"
        lines.append(f'- {eid} | {stype} | "{preview}"')
    return "\n".join(lines) if lines else "(no past exchanges available)"


def _build_raw_context(parsed: list[tuple[dict, str, str]], refs: list[dict]) -> str:
    """Format raw past exchanges as the refine-step input.

    Each past exchange gets a labeled block with its exchange id and source
    type so the refine LLM can carry those through into the refined context.
    """
    parts: list[str] = []
    for i, ((_chunk, stored_question, stored_answer), ref) in enumerate(
        zip(parsed, refs)
    ):
        parts.append(
            f"[Exchange {i+1} | id={ref['exchange_id']} | "
            f"source={ref['source_type']} | created={ref['original_created_at']}]\n"
            f"Q: {stored_question}\n"
            f"A: {_truncate(stored_answer, _MAX_ANSWER_CHARS)}"
        )
    return "\n\n".join(parts)


def _refine_context(question: str, raw_context: str) -> str:
    if not raw_context:
        return ""
    llm = get_llm(temperature=0.0)
    prompt = QA_HISTORY_REFINE_CONTEXT_PROMPT.format(
        question=question,
        raw_context=raw_context,
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
    except Exception:
        logger.exception(
            "Q&A history refine LLM call failed; falling back to raw context"
        )
        return raw_context
    refined = (response.content or "").strip()
    logger.info(
        "Q&A history refined context: %d chars from %d chars raw",
        len(refined), len(raw_context),
    )
    return refined or raw_context


def _formulate_answer(
    question: str,
    answer_language: str,
    allowed_sources: str,
    refined_context: str,
) -> str:
    llm = get_llm(temperature=0.0)
    system_prompt = QA_HISTORY_SYSTEM_PROMPT.format(answer_language=answer_language)
    user_prompt = QA_HISTORY_ANSWER_PROMPT.format(
        question=question,
        answer_language=answer_language,
        allowed_sources=allowed_sources,
        refined_context=refined_context or "(no relevant past exchanges)",
    )
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    return response.content or ""


def _filter_cited_references(answer: str, refs: list[dict]) -> list[dict]:
    """Keep only references whose exchange_id appears in the answer.

    Unlike video Q&A (where an answer is expected to cite every source it
    uses), history-chat answers may summarize without quoting exchange IDs.
    If nothing matches, fall back to the full reference list so the user can
    still see what was retrieved.
    """
    if not answer or not refs:
        return refs
    lower = answer.lower()
    cited = [r for r in refs if r["exchange_id"] and r["exchange_id"].lower() in lower]
    return cited or refs


async def run_qa_history_chat_agent(
    question: str,
    answer_language: str = "en",
) -> dict:
    """Answer a meta-question across the user's entire Q&A history.

    Flow:
        1. Retrieve top-K past Q&A docs from ``qa_library_global``.
        2. Build structured references (one per exchange).
        3. LLM compacts the raw past exchanges into focused context.
        4. LLM synthesizes the final answer with citation rules.
        5. Filter references to those the LLM actually cited; fall back to
           the full retrieval if it cited none.

    Returns:
        ``{"answer": str, "references": list[dict]}`` where each reference
        has shape ``{source_type, exchange_id, question_preview,
        job_id, original_created_at}``.
    """
    n_results = getattr(settings, "RAG_TOP_K", _DEFAULT_TOP_K) or _DEFAULT_TOP_K

    raw_chunks = _retrieve_past_exchanges(question, n_results=n_results)
    chunks = _dedupe_by_exchange_id(raw_chunks)
    # Parse each stored document exactly once.
    parsed = [
        (c, *_extract_question_and_answer(c.get("text") or ""))
        for c in chunks
    ]
    references = [_build_reference(c, q) for (c, q, _a) in parsed]

    if not chunks:
        logger.info("Q&A history agent: no past exchanges retrieved")
        answer = _formulate_answer(
            question=question,
            answer_language=answer_language,
            allowed_sources=_build_allowed_sources([]),
            refined_context="",
        )
        return {"answer": answer, "references": []}

    raw_context = _build_raw_context(parsed, references)
    refined_context = _refine_context(question, raw_context)
    allowed_sources = _build_allowed_sources(references)
    answer = _formulate_answer(
        question=question,
        answer_language=answer_language,
        allowed_sources=allowed_sources,
        refined_context=refined_context,
    )
    cited = _filter_cited_references(answer, references)
    return {"answer": answer, "references": cited[:10]}

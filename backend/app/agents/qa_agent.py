import json
import logging
import re
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.qa_prompts import (
    LIBRARY_QA_ANSWER_PROMPT,
    LIBRARY_QA_SYSTEM_PROMPT,
    LIBRARY_REFINE_CONTEXT_PROMPT,
    QA_ANSWER_PROMPT,
    QA_SYSTEM_PROMPT,
    REFINE_CONTEXT_PROMPT,
    SUB_QUERY_EXPANSION_PROMPT,
    USED_SOURCES_PROMPT,
)
from app.agents.state import QAAgentState
from app.config import settings
from app.services import chroma_service
from app.services.llm_service import get_llm_for, response_text
from app.services.llm_routing import max_output_for, resolve_config
from app.services import output_length as output_length_policy
from app.services import temporal_service
from app.utils.youtube_helpers import build_youtube_url, extract_video_id, format_timestamp

logger = logging.getLogger(__name__)

REPORT_CONTEXT_CHAR_CAP = 50000


def _usage_from_response(response) -> tuple[int | None, int | None]:
    """Extract (input_tokens, output_tokens) from a LangChain AIMessage.

    Prefers ``usage_metadata`` (normalized LangChain field), falls back to
    ``response_metadata["token_usage"]`` (provider-raw OpenAI shape). Returns
    (None, None) when the response carries no usage at all (local models).
    """
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if isinstance(input_tokens, int) or isinstance(output_tokens, int):
            return (
                input_tokens if isinstance(input_tokens, int) else 0,
                output_tokens if isinstance(output_tokens, int) else 0,
            )
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage")
        if isinstance(token_usage, dict):
            prompt = token_usage.get("prompt_tokens")
            completion = token_usage.get("completion_tokens")
            if isinstance(prompt, int) or isinstance(completion, int):
                return (
                    prompt if isinstance(prompt, int) else 0,
                    completion if isinstance(completion, int) else 0,
                )
    return None, None


class _TokenTally:
    """Sums token usage across every LLM call in one agent run.

    Totals stay None (not 0) when no call reported usage, so the DB row
    remains honestly NULL for providers that don't emit usage metadata.
    """

    def __init__(self) -> None:
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None

    def add(self, response) -> None:
        prompt, completion = _usage_from_response(response)
        if prompt is None and completion is None:
            return
        self.prompt_tokens = (self.prompt_tokens or 0) + (prompt or 0)
        self.completion_tokens = (self.completion_tokens or 0) + (completion or 0)


def _generate_sub_queries(question: str, tally: _TokenTally | None = None) -> list[str]:
    """Ask the LLM for 2 semantically-focused sub-queries to broaden retrieval."""
    llm = get_llm_for("qa_sub_query_expansion", temperature=0.0, max_tokens=300)
    prompt = SUB_QUERY_EXPANSION_PROMPT.format(question=question)
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        if tally is not None:
            tally.add(response)
        raw = response_text(response).strip()
    except Exception:
        logger.exception("Sub-query expansion LLM call failed; falling back to original question only")
        return []

    lines = [line.strip(" -*\t") for line in raw.splitlines() if line.strip()]
    # Drop any line that is just echoing the original question
    sub_queries = [line for line in lines if line.lower() != question.lower()]
    return sub_queries[:2]


def _vintage_parts(meta: dict) -> list[str]:
    """`published <date>` and `discusses <era>` fragments for a chunk's source.

    R3 / T-1.17.1.5: the date rides along wherever the source is named — in
    the raw-context headers the refiner reads and in the allowed-sources
    list the answer model cites from — so a time-sensitive answer can tell a
    2024 claim from a 2026 one. Empty for chunks that carry neither.
    """
    parts: list[str] = []
    pub = temporal_service.published_display((meta or {}).get("published_at"))
    if pub:
        parts.append(f"published {pub}")
    era = temporal_service.era_for_prompt(temporal_service.era_from_chunk_metadata(meta))
    if era:
        parts.append(era)
    return parts


def _chunk_header(index: int, chunk: dict) -> str:
    """`[Chunk N | Video: "T" by C at 12:34 | published 2025-03-12 | discusses 2019–2021]`."""
    meta = chunk.get("metadata", {}) or {}
    head = (
        f"[Chunk {index} | Video: \"{meta.get('video_title', 'Unknown')}\" "
        f"by {meta.get('channel_name', 'Unknown')} at {chunk.get('timestamp_display', '0:00')}"
    )
    for part in _vintage_parts(meta):
        head += f" | {part}"
    return head + "]"


def _answer_policy(
    statistics: dict | None,
    length_pref: str | None,
    use_case: str,
    base_tokens: int = 4_500,
) -> tuple[int, str, str]:
    """(max_tokens, corpus_note, length_guidance) for an answer call.

    S-1.15.2 (the Q&A half of R4): Q&A was corpus-blind — a fixed 4,500-token
    budget and no idea whether it was answering from 3 videos or 200. Same
    policy as the report (D-064): scale a derived budget and change the
    brief, never impose a cap. The statistics come from the router
    (`corpus_stats_service`), because a handful of retrieval hits says
    nothing about the corpus they came from. Until 2026-10-18 no router
    passed them, so every answer was classified `small` (D-066 amendment).

    R3 / T-1.17.1.4: the corpus note carries the publication span and, when
    known, the span of discussed eras, and tells the model what to do with
    them.
    """
    statistics = statistics or {}
    scale = output_length_policy.resolve_scale(statistics, length_pref)
    guidance = output_length_policy.guidance(statistics, length_pref)
    max_tokens = min(int(base_tokens * scale), max_output_for(resolve_config(use_case).model))

    corpus_note = ""
    if statistics.get("video_count"):
        span = ""
        if statistics.get("earliest_published"):
            span = (
                f" published between {statistics['earliest_published']} and "
                f"{statistics['latest_published']}"
            )
        eras = temporal_service.describe_corpus_eras(statistics)
        corpus_note = (
            f"CORPUS: this answer draws on {statistics['video_count']} source(s){span}"
            + (f"; {eras}" if eras else "")
            + ". Weight recency where the question is time-sensitive and the "
            "discussed era where it is about a period; when sources disagree "
            "along a time axis, say so and name the dates."
        )
    logger.info(
        "%s: length policy %s", use_case,
        output_length_policy.describe(statistics, length_pref),
    )
    return max_tokens, corpus_note, guidance


# ---------------------------------------------------------------------------
# D-068 / S-7.1.1 — trust-weighted re-rank
# ---------------------------------------------------------------------------
# Pre-registered in D-068 before any measurement, so it is not tuned here:
# retrieve 3 x top_k, drop anything failing RAG_DISTANCE_THRESHOLD on the RAW
# distance, sort by distance / weight, keep top_k. Weights come from the
# asking tenant's subscriptions keyed on the chunk's `channel_id`; a chunk with
# no channel (Reddit, HN, PDF, pasted page) weighs 1.0. Weighting after the
# threshold is the point: a trusted source reorders what is relevant and can
# never pull an off-topic passage into the answer.
TRUST_POOL_MULTIPLIER = 3
MIN_TRUST_WEIGHT = 0.05
MAX_TRUST_WEIGHT = 2.0


def _trust_weight(meta: dict, channel_weights: dict[str, float] | None) -> float:
    """The weight this tenant gives the chunk's channel, clamped to
    [MIN_TRUST_WEIGHT, MAX_TRUST_WEIGHT]; 1.0 when it has no channel or no
    weight. 0 becomes the floor so the source sinks but is never excluded."""
    if not channel_weights:
        return 1.0
    channel_id = (meta or {}).get("channel_id") or ""
    if not channel_id or channel_id not in channel_weights:
        return 1.0
    try:
        weight = float(channel_weights[channel_id])
    except (TypeError, ValueError):
        return 1.0
    if weight != weight:  # NaN
        return 1.0
    return min(MAX_TRUST_WEIGHT, max(MIN_TRUST_WEIGHT, weight))


def _weighted_distance(chunk: dict, channel_weights: dict[str, float] | None) -> float:
    return float(chunk.get("distance", 1.0)) / _trust_weight(
        chunk.get("metadata", {}) or {}, channel_weights
    )


def _weights_active(channel_weights: dict[str, float] | None) -> bool:
    """True when at least one weight differs from neutral. With none, the
    re-rank is the identity and retrieval runs exactly as before D-068."""
    if not channel_weights:
        return False
    for w in channel_weights.values():
        try:
            if abs(float(w) - 1.0) > 1e-9:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _rerank_by_trust(
    results: list[dict], channel_weights: dict[str, float] | None, top_k: int
) -> list[dict]:
    """D-068 steps 2-3 over a retrieved pool: the raw-distance threshold
    first, then ``distance / weight`` ascending, then ``top_k``.

    ``query_collection`` already drops chunks over the threshold; it is
    re-applied here so the guarantee does not depend on a caller passing it.
    """
    threshold = settings.RAG_DISTANCE_THRESHOLD
    relevant = [r for r in results if float(r.get("distance", 1.0)) <= threshold]
    relevant.sort(key=lambda r: _weighted_distance(r, channel_weights))
    return relevant[:top_k]


def _scoped_query(
    query_text: str,
    document_ids: list[str] | None,
    channel_weights: dict[str, float] | None = None,
) -> list[dict]:
    """One retrieval call, shared by job and library Q&A.

    Unweighted (the default for every tenant until they set a weight): one
    query for ``top_k``, identical to the pre-D-068 behaviour. Weighted: one
    query for ``3 x top_k``, then the re-rank. Still one Chroma call either way.
    """
    top_k = settings.RAG_TOP_K
    weighted = _weights_active(channel_weights)
    results = chroma_service.query_collection(
        query_text,
        n_results=top_k * TRUST_POOL_MULTIPLIER if weighted else top_k,
        document_ids=document_ids,
        distance_threshold=settings.RAG_DISTANCE_THRESHOLD,
    )
    if not weighted:
        return results
    return _rerank_by_trust(results, channel_weights, top_k)


def retrieve_context(state: QAAgentState, tally: _TokenTally | None = None) -> dict:
    """Retrieve relevant chunks from ChromaDB using multi-query expansion, plus extract report text."""
    job_id = state.get("job_id", "")
    question = state["question"]

    # Multi-query expansion: original question + up to 2 LLM-generated sub-queries.
    sub_queries = _generate_sub_queries(question, tally=tally)
    all_queries = [question] + sub_queries
    logger.info(f"[job:{job_id}] Q&A retrieval using {len(all_queries)} queries")

    # Retrieve per query and dedupe by chunk id (document + chunk_index + timestamp).
    merged: dict[str, dict] = {}
    document_ids = state.get("document_ids") or []
    if not document_ids:
        # A topic/channel job with zero approved documents has nothing to
        # retrieve from; never fall back to a global search here (S-1.12.1).
        logger.warning(f"[job:{job_id}] Q&A retrieval called with no approved document_ids")
    channel_weights = state.get("channel_weights") or {}
    if _weights_active(channel_weights):
        logger.info(
            f"[job:{job_id}] Q&A retrieval trust-weighted over {len(channel_weights)} channel(s)"
        )
    for q in all_queries:
        results = _scoped_query(q, document_ids, channel_weights) if document_ids else []
        for r in results:
            meta = r.get("metadata", {})
            key = (
                f"{_chunk_document_key(meta)}"
                f"_{meta.get('chunk_index', '')}"
                f"_{meta.get('timestamp_start', '')}"
            )
            existing = merged.get(key)
            if existing is None or r.get("distance", 1.0) < existing.get("distance", 1.0):
                merged[key] = r

    # D-068: the merged order follows the same weighted score that chose the
    # chunks; with no weights it is plain distance, as before.
    rag_results = sorted(
        merged.values(), key=lambda x: _weighted_distance(x, channel_weights)
    )

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


def refine_context(state: QAAgentState, tally: _TokenTally | None = None) -> dict:
    """Use LLM to extract only the relevant passages from RAG + report context."""
    llm = get_llm_for("qa_refine_context", temperature=0.0, max_tokens=3000)
    question = state["question"]
    rag_results = state.get("rag_results", [])
    report_context = state.get("report_context")

    # Format raw RAG chunks with source attribution
    raw_parts = []
    for i, r in enumerate(rag_results):
        raw_parts.append(f"{_chunk_header(i + 1, r)}\n{r.get('text', '')}")
    raw_rag = "\n\n".join(raw_parts) if raw_parts else ""

    raw_report = ""
    if report_context:
        raw_report = f"\n\n=== RESEARCH REPORT ===\n{report_context}"

    prompt = REFINE_CONTEXT_PROMPT.format(
        question=question,
        raw_context=raw_rag + raw_report,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    if tally is not None:
        tally.add(response)
    refined = response_text(response).strip()

    logger.info(f"Refined context: {len(refined)} chars from {len(raw_rag) + len(raw_report)} chars raw")

    return {"refined_context": refined}


def _build_allowed_sources(rag_results: list[dict], include_report: bool) -> str:
    """Render the allow-list of sources the LLM is permitted to cite.

    Listing them explicitly in the prompt is the strongest single anti-hallucination
    signal: the model has a closed universe of citable items.
    """
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for r in rag_results:
        meta = r.get("metadata", {})
        title = (meta.get("video_title") or "Unknown").strip()
        channel = (meta.get("channel_name") or "Unknown").strip()
        key = (title.lower(), channel.lower())
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f'- "{title}" by {channel}' + "".join(f" | {p}" for p in _vintage_parts(meta))
        )
    if include_report:
        lines.append("- Research Report (the synthesized report for this job)")
    return "\n".join(lines) if lines else "(no sources available)"


def formulate_answer(state: QAAgentState, tally: _TokenTally | None = None) -> dict:
    """Generate answer using LLM with refined context, constrained to allowed sources."""
    rag_results = state.get("rag_results", [])
    include_report = bool(state.get("report_context"))
    allowed_sources = _build_allowed_sources(rag_results, include_report)

    # S-1.15.2 / R3: corpus-aware budget, brief and temporal note. See
    # `_answer_policy` for why the statistics must come from the router.
    max_tokens, corpus_note, length_guidance = _answer_policy(
        state.get("corpus_statistics"), state.get("output_length"), "qa_formulate_answer"
    )

    llm = get_llm_for("qa_formulate_answer", temperature=0.0, max_tokens=max_tokens)

    prompt = QA_ANSWER_PROMPT.format(
        question=state["question"],
        allowed_sources=allowed_sources,
        refined_context=state.get("refined_context", "No context available."),
        corpus_note=corpus_note,
        length_guidance=length_guidance,
    )

    response = llm.invoke([
        SystemMessage(content=QA_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    if tally is not None:
        tally.add(response)

    return {"answer": response_text(response)}


def _chunk_document_key(meta: dict) -> str:
    """The per-document part of a chunk's dedupe key.

    D-070: ``document_id`` is the one field every chunk carries once the
    startup backfill has run. ``video_id`` covers chunks the backfill has
    not reached yet; ``source_id`` covers test fixtures. Before this, the
    key was ``video_id`` alone, which is empty for every non-video chunk —
    so two PDFs' chunk 0 collapsed into one entry.
    """
    return str(
        meta.get("document_id") or meta.get("video_id") or meta.get("source_id") or ""
    )


def _chunk_to_reference(chunk: dict) -> tuple[str, dict]:
    """Build a (dedupe_key, reference_dict) pair from a RAG chunk.

    Polymorphic by ``source_type`` per S-1.5.5. The frontend
    `<CitationLink>` component (PR #117) dispatches its rendering on
    the same `source_type` discriminator, so we emit it here on every
    reference. Legacy chunks (pre-S-1.5.4 era — no source_type in
    metadata) fall through to the YouTube path.

    Per-source fields:
      - video       (YouTube): video_url + video_title + channel_name
                               + timestamp_display + youtube_link
      - reddit_post:           permalink (with #comment-<id> when
                               applicable) + thread_title + subreddit
                               + author
      - hn_story:              permalink (HN item URL) + thread_title
                               + author
      - mastodon_post:         permalink (Mastodon status URL — points
                               at the reply when comment_id present) +
                               thread_title + author + instance
      - bluesky_post:          permalink (bsky.app web URL — points
                               at the reply when comment_url present) +
                               thread_title + author
      - podcast_episode:       permalink (episode page URL, optionally
                               with #t=<sec> when chunked from a
                               specific moment) + episode_title +
                               show_name (= author)
      - pdf:                   permalink (upload URL with #page=<N>
                               when chunked from a specific page) +
                               doc_title + page_number
      - article / fb_post / ig_post / li_post / tweet:
                               permalink (the original URL) + title +
                               author. All five paste-mode source
                               types share rendering shape; per-platform
                               glyph differentiation lives in the
                               frontend `<CitationLink>`.
    """
    meta = chunk.get("metadata", {})
    source_type = (meta.get("source_type") or "video").strip() or "video"
    source_id = meta.get("source_id") or meta.get("video_id") or ""
    title = (meta.get("video_title") or meta.get("title") or "Unknown") or "Unknown"

    if source_type == "reddit_post":
        permalink = (
            meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        # Reply-anchor support: if the chunk is from a specific
        # comment, append the #comment-<id> fragment so the citation
        # opens at the right reply.
        comment_id = meta.get("comment_id")
        if comment_id and "#comment-" not in permalink:
            permalink = f"{permalink}#comment-{comment_id}"
        author = meta.get("author") or ""
        subreddit = meta.get("subreddit") or ""
        # Dedupe key includes comment_id so two cites from the same
        # thread but different replies stay distinct.
        key = f"{source_type}:{source_id}_{comment_id or ''}"
        return key, {
            "source_type": "reddit_post",
            "permalink": permalink,
            "thread_title": title,
            "subreddit": subreddit,
            "author": author,
            # YouTube-shaped fields preserved as fallback for the
            # legacy frontend rendering path (still used by tests
            # that haven't migrated to <CitationLink>).
            "video_url": permalink,
            "video_title": title,
            "channel_name": (
                f"r/{subreddit}" if subreddit else (author or "Unknown")
            ),
            "timestamp_seconds": 0.0,
            "timestamp_display": "",
            "youtube_link": permalink,
        }

    if source_type == "hn_story":
        permalink = (
            meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        author = meta.get("author") or ""
        comment_id = meta.get("comment_id")
        # HN's per-comment URL is a separate item endpoint, not an
        # anchor; if a comment_id is set, point at that item directly.
        if comment_id:
            permalink = f"https://news.ycombinator.com/item?id={comment_id}"
        key = f"{source_type}:{source_id}_{comment_id or ''}"
        return key, {
            "source_type": "hn_story",
            "permalink": permalink,
            "thread_title": title,
            "author": author,
            # Legacy YouTube-shaped fallback fields.
            "video_url": permalink,
            "video_title": title,
            "channel_name": author or "HN",
            "timestamp_seconds": 0.0,
            "timestamp_display": "",
            "youtube_link": permalink,
        }

    if source_type == "mastodon_post":
        permalink = (
            meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        author = meta.get("author") or ""
        instance = meta.get("instance") or ""
        comment_id = meta.get("comment_id")
        # Reply-anchor support: Mastodon doesn't have an inline anchor
        # for replies, but each reply is itself a status with its own
        # canonical URL. If `comment_url` was indexed alongside the
        # comment_id, prefer it; otherwise fall through to the OP url.
        comment_url = meta.get("comment_url")
        if comment_id and comment_url:
            permalink = comment_url
        # Dedupe key includes comment_id so two cites from the same
        # thread but different replies stay distinct.
        key = f"{source_type}:{source_id}_{comment_id or ''}"
        return key, {
            "source_type": "mastodon_post",
            "permalink": permalink,
            "thread_title": title,
            "author": author,
            "instance": instance,
            # Legacy YouTube-shaped fallback fields.
            "video_url": permalink,
            "video_title": title,
            "channel_name": author or (instance or "Mastodon"),
            "timestamp_seconds": 0.0,
            "timestamp_display": "",
            "youtube_link": permalink,
        }

    if source_type == "bluesky_post":
        permalink = (
            meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        author = meta.get("author") or ""
        comment_id = meta.get("comment_id")
        # Same reply-anchor pattern as Mastodon: each reply is a
        # standalone post with its own bsky.app web URL. If the
        # chunking pipeline indexed `comment_url`, jump to it.
        comment_url = meta.get("comment_url")
        if comment_id and comment_url:
            permalink = comment_url
        key = f"{source_type}:{source_id}_{comment_id or ''}"
        return key, {
            "source_type": "bluesky_post",
            "permalink": permalink,
            "thread_title": title,
            "author": author,
            # Legacy YouTube-shaped fallback fields.
            "video_url": permalink,
            "video_title": title,
            "channel_name": author or "Bluesky",
            "timestamp_seconds": 0.0,
            "timestamp_display": "",
            "youtube_link": permalink,
        }

    if source_type in ("article", "fb_post", "ig_post", "li_post", "tweet"):
        # All five paste-mode source types share rendering — the
        # permalink is the original URL, the title comes from the
        # extracted document title (or the URL fallback), the author
        # comes from trafilatura's metadata extraction.
        permalink = (
            meta.get("comment_url")
            or meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        author = meta.get("segment_author") or meta.get("author") or ""
        comment_id = meta.get("comment_id") or ""
        # Per-platform tags surface a friendly label in the legacy
        # `channel_name` fallback — `Article`, `Facebook`, `Instagram`,
        # `LinkedIn`, `X / Twitter`.
        platform_label = {
            "article": "Article",
            "fb_post": "Facebook",
            "ig_post": "Instagram",
            "li_post": "LinkedIn",
            "tweet": "X / Twitter",
        }[source_type]
        key = f"{source_type}:{source_id}_{comment_id}"
        return key, {
            "source_type": source_type,
            "permalink": permalink,
            "thread_title": title,
            "author": author,
            # Legacy YouTube-shaped fallback fields.
            "video_url": permalink,
            "video_title": title,
            "channel_name": author or platform_label,
            "timestamp_seconds": 0.0,
            "timestamp_display": "",
            "youtube_link": permalink,
        }

    if source_type == "pdf":
        # PDFs are page-anchored: per-page `comment_url` carries
        # `#page=<N>` so PDF viewers (Chrome built-in, Firefox, Adobe)
        # deep-link to the cited page.
        permalink = (
            meta.get("comment_url")  # carries #page=<N> fragment
            or meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        # Try to surface the page number for the citation label.
        # `comment_id` for PDFs is the synthesised `pdf:<hash>:p<N>`
        # form; the chunker's dominant-segment heuristic also writes
        # the raw page number to `segment_depth` (we use depth=0 for
        # PDFs so it's always 0 — page lives in `comment_id`).
        page_number = ""
        cid = meta.get("comment_id") or ""
        if ":p" in cid:
            page_number = cid.rsplit(":p", 1)[-1]
        key = f"{source_type}:{source_id}_{cid}"
        return key, {
            "source_type": "pdf",
            "permalink": permalink,
            "thread_title": title,  # document title
            "author": meta.get("author") or "",
            "page_number": page_number,
            # Legacy YouTube-shaped fallback fields.
            "video_url": permalink,
            "video_title": title,
            "channel_name": meta.get("author") or "PDF",
            "timestamp_seconds": 0.0,
            "timestamp_display": f"p. {page_number}" if page_number else "",
            "youtube_link": permalink,
        }

    if source_type == "podcast_episode":
        # Per-episode permalink (episode page URL when present, else
        # the audio enclosure). The chunker writes a `comment_url`
        # carrying the episode URL plus a `#t=<sec>` time-fragment
        # so podcast-player apps that honor the fragment deep-link to
        # the cited timestamp.
        permalink = (
            meta.get("comment_url")  # carries #t=<sec> fragment
            or meta.get("permalink")
            or meta.get("source_url")
            or meta.get("video_url")
            or ""
        )
        # Author here is the show host / creator, captured by the
        # connector's `attach_episode_extra` helper.
        author = meta.get("segment_author") or meta.get("author") or ""
        # `comment_id` is the episode URL; use it as part of the dedupe
        # key so two cites from different timestamps in the same
        # episode collapse to the same reference (timestamp lives in
        # `permalink` already).
        comment_id = meta.get("comment_id") or ""
        key = f"{source_type}:{source_id}_{comment_id}"

        # Try to surface a `timestamp_seconds` for the legacy fallback
        # rendering path — pull from `timestamp_start` when chunking
        # wrote it (it always does for podcasts).
        ts = float(meta.get("timestamp_start", 0))
        return key, {
            "source_type": "podcast_episode",
            "permalink": permalink,
            "thread_title": title,  # episode title
            "author": author,
            # Legacy YouTube-shaped fallback fields.
            "video_url": permalink,
            "video_title": title,
            "channel_name": author or "Podcast",
            "timestamp_seconds": ts,
            "timestamp_display": format_timestamp(ts),
            "youtube_link": permalink,
        }

    # Default: video / unknown — preserve the legacy YouTube shape.
    vid = source_id or meta.get("video_id", "")
    ts = float(meta.get("timestamp_start", 0))
    key = f"{vid}_{int(ts)}"
    return key, {
        "source_type": "video",
        "video_url": meta.get("video_url", build_youtube_url(vid)),
        "video_title": title,
        "channel_name": meta.get("channel_name", "Unknown"),
        "timestamp_seconds": ts,
        "timestamp_display": format_timestamp(ts),
        "youtube_link": build_youtube_url(vid, ts),
    }


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


def _references_via_llm(
    rag_results: list[dict], answer: str, tally: _TokenTally | None = None
) -> list[dict]:
    """Ask the LLM which candidate chunks were actually used in the answer."""
    candidates = rag_results[:20]
    if not candidates:
        return []

    # Polymorphic chunk listing per S-1.5.12 T-1.5.12.3. The LLM
    # auditor sees `[source_type]` as a prefix so it can distinguish
    # YouTube videos from Reddit / HN / Mastodon / Bluesky chunks.
    # The id column prefers `source_id` (the namespaced form like
    # `reddit:abc` / `bluesky:at://...`) when present, falling back
    # to legacy `video_id` for older chunks. Title falls back through
    # `video_title` → `title` → "Unknown".
    lines = []
    for i, r in enumerate(candidates):
        m = r.get("metadata", {}) or {}
        source_type = (m.get("source_type") or "video").strip() or "video"
        chunk_id = m.get("source_id") or m.get("video_id") or ""
        title = m.get("video_title") or m.get("title") or "Unknown"
        lines.append(f"{i} | [{source_type}] | {chunk_id} | {title}")
    prompt = USED_SOURCES_PROMPT.format(answer=answer, chunks="\n".join(lines))

    llm = get_llm_for("qa_extract_references", temperature=0.0, max_tokens=1500)
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        if tally is not None:
            tally.add(response)
        content = response_text(response).strip()
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


# Match a `[Source: "TITLE" by CHANNEL at TIMESTAMP]` citation. Title may be
# in straight quotes, curly quotes, or bare; channel runs to " at " or "]".
_CITATION_PATTERN = re.compile(
    r'\[Source:\s*'
    r'(?:["“\'](?P<title_q>[^"”\']+)["”\']|(?P<title_b>[^"”\'][^]]*?))'
    r'\s+by\s+(?P<channel>.+?)'
    r'(?:\s+at\s+[^\]]+)?'
    r'\]',
    re.IGNORECASE,
)
_REPORT_CITATION_PATTERN = re.compile(
    r'\[Source:\s*Research Report[^\]]*\]',
    re.IGNORECASE,
)


def _citation_is_grounded(
    cited_title: str,
    cited_channel: str,
    allowed_titles_lower: set[str],
    allowed_channels_lower: set[str],
    title_keyword_index: dict[str, set[str]],
) -> bool:
    """Decide whether a parsed citation refers to a real allowed source.

    Allow if the cited title (or one of its normalized variants) appears in the
    allowed-titles set, OR the cited channel matches an allowed channel and the
    cited title shares at least one significant keyword with that channel's
    real titles. This mirrors the looser matching used by the reference
    extractor so we don't strip legitimate-but-rephrased citations.
    """
    cited_title = (cited_title or "").strip()
    cited_channel = (cited_channel or "").strip()
    cited_channel_lower = cited_channel.lower()

    # Exact / variant title match against any allowed title.
    for variant in _title_variants(cited_title):
        v_lower = variant.lower()
        if v_lower in allowed_titles_lower:
            return True
        # Also allow if any allowed title is a substring of the cited variant
        # (LLM expanded with a subtitle) or vice versa.
        for allowed in allowed_titles_lower:
            if len(v_lower) >= 10 and (v_lower in allowed or allowed in v_lower):
                return True

    # Channel + keyword fallback.
    if cited_channel_lower in allowed_channels_lower:
        cited_keywords = {w.lower() for w in re.findall(r'\b[A-Za-z]{5,}\b', cited_title)}
        real_keywords = title_keyword_index.get(cited_channel_lower, set())
        if cited_keywords & real_keywords:
            return True

    return False


def _sanitize_citations(answer: str, rag_results: list[dict]) -> tuple[str, int]:
    """Strip [Source: ...] tags whose title doesn't match any real RAG chunk.

    Returns (sanitized_answer, removed_count). Research Report citations are
    always kept (they're grounded by definition when a report exists).
    """
    if not answer:
        return answer, 0

    allowed_titles_lower: set[str] = set()
    allowed_channels_lower: set[str] = set()
    title_keyword_index: dict[str, set[str]] = {}
    for r in rag_results:
        meta = r.get("metadata", {})
        title = (meta.get("video_title") or "").strip()
        channel = (meta.get("channel_name") or "").strip()
        if not title:
            continue
        for variant in _title_variants(title):
            allowed_titles_lower.add(variant.lower())
        if channel:
            allowed_channels_lower.add(channel.lower())
            kw = {w.lower() for w in re.findall(r'\b[A-Za-z]{5,}\b', title)}
            title_keyword_index.setdefault(channel.lower(), set()).update(kw)

    removed = 0

    def _replace(match: re.Match) -> str:
        nonlocal removed
        cited_title = (match.group("title_q") or match.group("title_b") or "").strip()
        cited_channel = match.group("channel").strip()
        if _citation_is_grounded(
            cited_title, cited_channel,
            allowed_titles_lower, allowed_channels_lower, title_keyword_index,
        ):
            return match.group(0)
        removed += 1
        logger.warning(
            "Stripping fabricated citation: title=%r channel=%r",
            cited_title, cited_channel,
        )
        # Replace with a clear marker rather than silently deleting; preserves
        # answer flow but signals that the source could not be verified.
        return "[Source: unverified]"

    sanitized = _CITATION_PATTERN.sub(_replace, answer)
    return sanitized, removed


def extract_references(state: QAAgentState, tally: _TokenTally | None = None) -> dict:
    """Sanitize fabricated citations, then extract structured references.

    1. Strip any `[Source: ...]` tags whose title/channel doesn't match a real
       RAG chunk (LLM hallucination guard).
    2. Run the existing matcher (deterministic + LLM auditor fallback) over
       the sanitized answer.
    """
    rag_results = state.get("rag_results", [])
    answer = state.get("answer", "") or ""

    if not rag_results or not answer:
        return {"answer": answer, "references": []}

    sanitized_answer, removed = _sanitize_citations(answer, rag_results)
    if removed:
        logger.info(f"Sanitized {removed} fabricated citation(s) from Q&A answer")

    references = _references_from_citations(rag_results, sanitized_answer)
    if not references:
        references = _references_via_llm(rag_results, sanitized_answer, tally=tally)

    return {"answer": sanitized_answer, "references": references[:10]}


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
    document_ids: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    usage_out: dict | None = None,
    corpus_statistics: dict | None = None,
    output_length: str | None = None,
    channel_weights: dict[str, float] | None = None,
) -> tuple[str, list[dict]]:
    """
    Run the Q&A agent pipeline node-by-node (same order as the compiled graph).

    ``document_ids`` is the job's approved ``documents.document_id`` set
    (D-070); retrieval is restricted to chunks whose ``document_id`` metadata
    is in it, and an empty set retrieves nothing.

    ``channel_weights`` are the asking tenant's non-neutral trust weights
    (D-068), resolved by the router; retrieval re-ranks by them after the
    relevance threshold. Absent or empty, retrieval is unweighted.

    ``progress_callback`` is invoked with a stage name before each node:
    "retrieving", "refining", "formulating", "extracting_references".
    ``usage_out``, when given a dict, is populated with "prompt_tokens" /
    "completion_tokens" summed across every LLM call in the run (None when
    no provider reported usage metadata).

    Returns:
        (answer_text, references_list)
    """
    tally = _TokenTally()

    def notify(stage: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(stage)
        except Exception:
            logger.exception("Q&A progress callback failed for stage %s", stage)

    state: dict = {
        "messages": [],
        "job_id": job_id,
        "job_type": job_type,
        "question": question,
        "report_html": report_html or "",
        "document_ids": document_ids or [],
        "channel_weights": channel_weights or {},
        "sub_queries": [],
        "rag_results": [],
        "report_context": None,
        "refined_context": "",
        "answer": "",
        "references": [],
        # S-1.15.2 / R3 — both optional; absent means today's behaviour.
        "corpus_statistics": corpus_statistics or {},
        "output_length": output_length,
    }

    notify("retrieving")
    state.update(retrieve_context(state, tally=tally))
    notify("refining")
    state.update(refine_context(state, tally=tally))
    notify("formulating")
    state.update(formulate_answer(state, tally=tally))
    notify("extracting_references")
    state.update(extract_references(state, tally=tally))

    state["prompt_tokens"] = tally.prompt_tokens
    state["completion_tokens"] = tally.completion_tokens
    if usage_out is not None:
        usage_out["prompt_tokens"] = tally.prompt_tokens
        usage_out["completion_tokens"] = tally.completion_tokens
    return state.get("answer", ""), state.get("references", [])


# ---------------------------------------------------------------------------
# Library-wide Q&A (Unit 6). Searches the global library (no job_id scope)
# and supports answering in a requested language.
# ---------------------------------------------------------------------------


def _query_library(
    query_text: str,
    document_ids: list[str] | None = None,
    channel_weights: dict[str, float] | None = None,
) -> list[dict]:
    """Query the library ChromaDB collection, restricted to ``document_ids``.

    S-5.7.1: this previously always passed no scope, i.e. searched EVERY
    tenant's transcripts. The caller now supplies the set the asking tenant
    may see, as ``documents.document_id`` values (D-070). ``None`` means
    unrestricted and is reserved for internal / single-tenant use —
    user-facing callers must pass an explicit list, and an EMPTY list
    retrieves nothing (``query_collection`` enforces that).
    """
    # Pass the query positionally: Unit 2 kept the first param name as
    # `query_or_job_id` for backward compat with the old per-job signature,
    # so `query_text=` as a kwarg raises TypeError.
    try:
        return _scoped_query(query_text, document_ids, channel_weights)
    except TypeError:
        logger.exception(
            "chroma_service.query_collection unexpected signature; "
            "library-wide search unavailable."
        )
        return []


def _dedupe_chunks(
    chunks: list[dict], channel_weights: dict[str, float] | None = None
) -> list[dict]:
    """Dedupe RAG chunks by (document, chunk_index); keep closest distance.

    Ordered by the D-068 weighted score, which is plain distance when
    ``channel_weights`` is empty."""
    merged: dict[str, dict] = {}
    for r in chunks:
        meta = r.get("metadata", {})
        key = f"{_chunk_document_key(meta)}_{meta.get('chunk_index', '')}"
        existing = merged.get(key)
        if existing is None or r.get("distance", 1.0) < existing.get("distance", 1.0):
            merged[key] = r
    return sorted(merged.values(), key=lambda x: _weighted_distance(x, channel_weights))


def _enrich_chunks(chunks: list[dict]) -> None:
    """In-place: add timestamp_display and youtube_link to each chunk."""
    for r in chunks:
        meta = r.get("metadata", {})
        ts = float(meta.get("timestamp_start", 0) or 0)
        vid = meta.get("video_id", "")
        r["timestamp_display"] = format_timestamp(ts)
        r["youtube_link"] = build_youtube_url(vid, ts)


def _build_library_allowed_sources(rag_results: list[dict]) -> str:
    """Allowed-sources list for library Q&A.

    Includes the video_id prefix so the LLM can disambiguate same-titled
    videos across different channels in the global library. Dedupes by
    (id, title, channel). Non-video sources (D-070) have no video_id and
    no channel: the line carries their ``source_id`` and their author.
    """
    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []
    for r in rag_results:
        meta = r.get("metadata", {})
        vid = (meta.get("video_id") or meta.get("source_id") or "").strip()
        title = (meta.get("video_title") or "Unknown").strip()
        channel = (meta.get("channel_name") or meta.get("author") or "Unknown").strip()
        key = (vid, title.lower(), channel.lower())
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f'- {vid} | "{title}" by {channel}'
            + "".join(f" | {p}" for p in _vintage_parts(meta))
        )
    return "\n".join(lines) if lines else "(no sources available)"


def run_library_qa_agent(
    question: str,
    answer_language: str = "en",
    visible_document_ids: list[str] | None = None,
    corpus_statistics: dict | None = None,
    output_length: str | None = None,
    channel_weights: dict[str, float] | None = None,
) -> dict:
    """Run library-wide Q&A against the global video library.

    ``visible_document_ids`` restricts retrieval to the documents the asking
    tenant may see (S-5.7.1), as ``documents.document_id`` values (D-070).
    Passing an EMPTY list means "this tenant has ingested nothing" and
    correctly retrieves nothing; passing None is unrestricted and must not
    be used for user-facing calls.

    ``corpus_statistics`` (S-1.15.2) are the figures for the VISIBLE set —
    the router computes them via `corpus_stats_service`; ``output_length``
    is the request's optional depth override. Both drive the same D-064
    policy as job Q&A; absent, the answer is classified `small`.

    Flow: sub-query expansion -> chroma retrieve over the visible set -> dedupe
    -> LLM context refinement -> LLM answer with language + citation rules
    -> citation sanitizer.

    Returns:
        {"answer": str, "references": list[dict]}
    """
    # 1. Sub-query expansion (reuse the existing prompt; same style of retrieval).
    sub_queries = _generate_sub_queries(question)
    all_queries = [question] + sub_queries
    logger.info("Library Q&A retrieval using %d queries", len(all_queries))

    # 2. Library-wide ChromaDB retrieval.
    raw: list[dict] = []
    for q in all_queries:
        raw.extend(_query_library(q, visible_document_ids, channel_weights))

    # 3. Dedupe + enrich (ordered by the D-068 weighted score).
    rag_results = _dedupe_chunks(raw, channel_weights)
    _enrich_chunks(rag_results)

    # 4. Refine context.
    raw_parts = []
    for i, r in enumerate(rag_results):
        raw_parts.append(f"{_chunk_header(i + 1, r)}\n{r.get('text', '')}")
    raw_context = "\n\n".join(raw_parts)

    llm = get_llm_for("library_qa_refine_context", temperature=0.0, max_tokens=3000)
    refine_prompt = LIBRARY_REFINE_CONTEXT_PROMPT.format(
        question=question,
        raw_context=raw_context,
    )
    refined_response = llm.invoke([HumanMessage(content=refine_prompt)])
    refined_context = response_text(refined_response).strip() or "No context available."

    logger.info(
        "Library Q&A refined context: %d chars from %d chars raw",
        len(refined_context), len(raw_context),
    )

    # 5. Formulate answer with language + allowed-sources constraints and the
    # corpus-aware length policy (S-1.15.2 — this call ran a fixed 4,500
    # tokens with no policy until 2026-10-18).
    allowed_sources = _build_library_allowed_sources(rag_results)
    max_tokens, corpus_note, length_guidance = _answer_policy(
        corpus_statistics, output_length, "library_qa_formulate_answer"
    )
    answer_llm = get_llm_for(
        "library_qa_formulate_answer", temperature=0.0, max_tokens=max_tokens
    )
    system_prompt = LIBRARY_QA_SYSTEM_PROMPT.format(answer_language=answer_language)
    user_prompt = LIBRARY_QA_ANSWER_PROMPT.format(
        question=question,
        answer_language=answer_language,
        allowed_sources=allowed_sources,
        refined_context=refined_context,
        corpus_note=corpus_note,
        length_guidance=length_guidance,
    )
    answer_response = answer_llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    answer = response_text(answer_response)

    # 6. Sanitize fabricated citations using the shared helper, then extract
    # structured references.
    if not rag_results or not answer:
        return {"answer": answer, "references": []}

    sanitized_answer, removed = _sanitize_citations(answer, rag_results)
    if removed:
        logger.info("Sanitized %d fabricated citation(s) from library Q&A answer", removed)
    references = _references_from_citations(rag_results, sanitized_answer)
    if not references:
        references = _references_via_llm(rag_results, sanitized_answer)

    # LibraryReference requires an explicit video_id; the shared helper builds
    # refs without one, so derive it from the video_url.
    library_refs = [
        {**ref, "video_id": extract_video_id(ref.get("video_url", "")) or ""}
        for ref in references[:10]
    ]

    return {"answer": sanitized_answer, "references": library_refs}

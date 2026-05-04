import json
import logging
import re

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
from app.services.llm_service import get_llm_for
from app.utils.youtube_helpers import build_youtube_url, extract_video_id, format_timestamp

logger = logging.getLogger(__name__)

REPORT_CONTEXT_CHAR_CAP = 50000


def _generate_sub_queries(question: str) -> list[str]:
    """Ask the LLM for 2 semantically-focused sub-queries to broaden retrieval."""
    llm = get_llm_for("qa_sub_query_expansion", temperature=0.0)
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
    llm = get_llm_for("qa_refine_context", temperature=0.0)
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
        lines.append(f'- "{title}" by {channel}')
    if include_report:
        lines.append("- Research Report (the synthesized report for this job)")
    return "\n".join(lines) if lines else "(no sources available)"


def formulate_answer(state: QAAgentState) -> dict:
    """Generate answer using LLM with refined context, constrained to allowed sources."""
    # Temperature 0: citations must be deterministic and grounded.
    llm = get_llm_for("qa_formulate_answer", temperature=0.0)

    rag_results = state.get("rag_results", [])
    include_report = bool(state.get("report_context"))
    allowed_sources = _build_allowed_sources(rag_results, include_report)

    prompt = QA_ANSWER_PROMPT.format(
        question=state["question"],
        allowed_sources=allowed_sources,
        refined_context=state.get("refined_context", "No context available."),
    )

    response = llm.invoke([
        SystemMessage(content=QA_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])

    return {"answer": response.content}


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


def _references_via_llm(rag_results: list[dict], answer: str) -> list[dict]:
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

    llm = get_llm_for("qa_extract_references", temperature=0.0)
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


def extract_references(state: QAAgentState) -> dict:
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
        references = _references_via_llm(rag_results, sanitized_answer)

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


# ---------------------------------------------------------------------------
# Library-wide Q&A (Unit 6). Searches the global library (no job_id scope)
# and supports answering in a requested language.
# ---------------------------------------------------------------------------


def _query_library(query_text: str) -> list[dict]:
    """Query the global library ChromaDB collection.

    Unit 2 introduces a new ``query_collection`` signature that accepts
    ``video_ids=None`` for library-wide search. Call that first; fall back to
    the legacy per-job signature (with a sentinel global-collection id) if the
    new signature isn't available yet so Unit 6 is robust to merge ordering.
    """
    # Pass the query positionally: Unit 2 kept the first param name as
    # `query_or_job_id` for backward compat with the old per-job signature,
    # so `query_text=` as a kwarg raises TypeError.
    try:
        return chroma_service.query_collection(
            query_text,
            n_results=settings.RAG_TOP_K,
            video_ids=None,
            distance_threshold=settings.RAG_DISTANCE_THRESHOLD,
        )
    except TypeError:
        logger.exception(
            "chroma_service.query_collection unexpected signature; "
            "library-wide search unavailable."
        )
        return []


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    """Dedupe RAG chunks by (video_id, chunk_index); keep closest distance."""
    merged: dict[str, dict] = {}
    for r in chunks:
        meta = r.get("metadata", {})
        key = f"{meta.get('video_id', '')}_{meta.get('chunk_index', '')}"
        existing = merged.get(key)
        if existing is None or r.get("distance", 1.0) < existing.get("distance", 1.0):
            merged[key] = r
    return sorted(merged.values(), key=lambda x: x.get("distance", 1.0))


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
    (video_id, title, channel).
    """
    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []
    for r in rag_results:
        meta = r.get("metadata", {})
        vid = (meta.get("video_id") or "").strip()
        title = (meta.get("video_title") or "Unknown").strip()
        channel = (meta.get("channel_name") or "Unknown").strip()
        key = (vid, title.lower(), channel.lower())
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'- {vid} | "{title}" by {channel}')
    return "\n".join(lines) if lines else "(no sources available)"


def run_library_qa_agent(
    question: str,
    answer_language: str = "en",
) -> dict:
    """Run library-wide Q&A against the global video library.

    Flow: sub-query expansion -> chroma retrieve across all videos -> dedupe
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
        raw.extend(_query_library(q))

    # 3. Dedupe + enrich.
    rag_results = _dedupe_chunks(raw)
    _enrich_chunks(rag_results)

    # 4. Refine context.
    raw_parts = []
    for i, r in enumerate(rag_results):
        meta = r.get("metadata", {})
        raw_parts.append(
            f"[Chunk {i+1} | Video: \"{meta.get('video_title', 'Unknown')}\" "
            f"by {meta.get('channel_name', 'Unknown')} at {r.get('timestamp_display', '0:00')}]\n"
            f"{r.get('text', '')}"
        )
    raw_context = "\n\n".join(raw_parts)

    llm = get_llm_for("library_qa_refine_context", temperature=0.0)
    refine_prompt = LIBRARY_REFINE_CONTEXT_PROMPT.format(
        question=question,
        raw_context=raw_context,
    )
    refined_response = llm.invoke([HumanMessage(content=refine_prompt)])
    refined_context = (refined_response.content or "").strip() or "No context available."

    logger.info(
        "Library Q&A refined context: %d chars from %d chars raw",
        len(refined_context), len(raw_context),
    )

    # 5. Formulate answer with language + allowed-sources constraints.
    allowed_sources = _build_library_allowed_sources(rag_results)
    answer_llm = get_llm_for("library_qa_formulate_answer", temperature=0.0)
    system_prompt = LIBRARY_QA_SYSTEM_PROMPT.format(answer_language=answer_language)
    user_prompt = LIBRARY_QA_ANSWER_PROMPT.format(
        question=question,
        answer_language=answer_language,
        allowed_sources=allowed_sources,
        refined_context=refined_context,
    )
    answer_response = answer_llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    answer = answer_response.content or ""

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

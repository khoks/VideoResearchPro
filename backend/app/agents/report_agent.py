import json
import logging
import re
import time

import tiktoken
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.report_prompts import (
    CHANNEL_COMPOSE_PROMPT,
    CHANNEL_MAP_PROMPT,
    COMPOSE_SECTION_PROMPT,
    COMPOSE_SUMMARY_PROMPT,
    MAP_CHUNK_PROMPT,
    REPORT_SECTIONS,
)
from app.agents.state import ReportAgentState
from app.services.llm_service import get_llm_for, response_text
from app.services.llm_routing import (
    context_window_for,
    max_output_for,
    resolve_config,
)
from app.services import output_length as output_length_policy
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

# Total consolidated material compose may consume across ALL of its section
# calls (S-1.14.8). Compose now splits each section into as many calls as the
# material needs, so this is a COST guard, not a capability limit — reduce
# stays lossless below it. Sized well above the E-1.14 reference corpus (200
# videos / 1.06M transcript words consolidated to ~370K tokens) so a typical
# job never compresses at all.
_MAX_COMPOSE_INPUT_TOKENS = 1_000_000


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


# --- S-1.14.8: completion budgets scale with the work, not a constant -------
#
# D-055 measured the defect these replace: map emitted <=3,000 tokens per
# ~116K-token batch (5.9% of what was extractable) and reduce <=6,000 per
# merge, so <=0.43% of a 1.39M-token corpus reached the writer and the
# shipped report cited 2 channels out of 92. Ceilings are 128K (measured,
# ``MODEL_MAX_OUTPUT_TOKENS``), so the caps were self-inflicted.

# Share of a batch's INPUT tokens we allow the extraction to occupy. The
# E-1.14 max-effort control extracted at ~44% (608,718 out of 1,393,656).
#
# Raised 0.20 -> 0.40 on 2026-07-30 (S-1.14.13). At 0.20 we were capping the
# whole run at 288K extraction tokens against the control's 609K — i.e. we
# had re-imposed a budget ceiling below what the corpus supports, which is
# the same class of defect D-056 set out to remove. With the volume tier now
# on gpt-5.6-luna at $1.20/M output (D-057), closing that gap costs roughly
# $0.34 on the 200-video benchmark. Still below the control so we are not
# paying for exhaustive restatement.
_MAP_EXTRACTION_RATIO = 0.40

# Floor so tiny batches still get a workable completion budget.
_MIN_COMPLETION_TOKENS = 3_000


def _completion_budget(use_case: str, work_tokens: int, ratio: float) -> int:
    """Completion budget for ``use_case`` derived from the size of the work in
    front of it, clamped to the resolved model's measured output ceiling.

    ``work_tokens`` is the input the call must account for; ``ratio`` is how
    much of it the output may occupy.
    """
    cfg = resolve_config(use_case)
    ceiling = max_output_for(cfg.model)
    want = max(int(work_tokens * ratio), _MIN_COMPLETION_TOKENS)
    return min(want, ceiling)


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

    budget_per_batch = _batch_budget("report_map_chunks")
    # S-1.14.8: the completion budget tracks the batch it must summarize.
    # Previously pinned at 3,000 while batches grew to ~116K (E-1.12), which
    # silently discarded ~94% of the extractable content (D-055).
    map_max_tokens = _completion_budget(
        "report_map_chunks", budget_per_batch, _MAP_EXTRACTION_RATIO
    )
    llm = get_llm_for("report_map_chunks", temperature=0.0, max_tokens=map_max_tokens)
    logger.info(
        "map_chunks: %d chunks, batch budget %d tokens, completion budget %d "
        "(model %s, output ceiling %d)",
        len(chunks), budget_per_batch, map_max_tokens,
        resolve_config("report_map_chunks").model,
        max_output_for(resolve_config("report_map_chunks").model),
    )

    # Group chunks into batches
    batches = []
    current_batch = []
    current_tokens = 0

    for chunk in chunks:
        text = chunk.get("text", "")
        meta = chunk.get("metadata", {})
        # S-1.14.9: the URL must be IN the header. MAP_CHUNK_PROMPT asks for a
        # `video_url` on every extracted item, but nothing ever supplied one —
        # so every citation in every report rendered as href="&t=123", a dead
        # link. Costs ~12 tokens per chunk; buys working citations.
        # The chunker emits `video_url`; `url`/`permalink` are the pre-chunk
        # and non-video-source spellings.
        url = meta.get("video_url") or meta.get("url") or meta.get("permalink") or ""
        formatted = (
            f"[{meta.get('video_title', 'Unknown')} | {meta.get('channel_name', 'Unknown')} | "
            f"{format_timestamp(meta.get('timestamp_start', 0))}"
            f"{' | ' + url if url else ''}]\n{text}"
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
            return json.loads(response_text(response))
        except json.JSONDecodeError:
            return {"raw": response_text(response)}

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


_REDUCE_KEYS = ("facts", "comments", "conclusions", "references", "speakers")


def _item_video(item: dict) -> str:
    """Stable per-video identity for an extracted item.

    Keys on ``video_url`` first because two DISTINCT videos in the reference
    corpus differ only by letter case in their titles (S-1.14.9) — a
    case-insensitive title key silently merges them.
    """
    if not isinstance(item, dict):
        return ""
    return str(item.get("video_url") or item.get("video_title") or "")


def _merge_structurally(summaries: list) -> tuple[dict, dict]:
    """Lossless union of batch summaries — no LLM, no semantic judgement.

    S-1.14.8 / D-055: a control pass over the reference corpus found ZERO
    duplicates within ``(category, video)`` — no exact, substring, or
    Jaccard>=0.90 matches — so the previous LLM "merge and deduplicate" pass
    could only ever destroy content. Only byte-identical items (same content,
    same video, same timestamp) are collapsed here; everything else survives.
    The same claim from a different source is DISTINCT attribution in a
    citation-backed report and is deliberately kept.
    """
    merged: dict[str, list] = {k: [] for k in _REDUCE_KEYS}
    seen: set = set()
    exact_dupes = 0
    unparsed = 0

    for summary in summaries:
        if not isinstance(summary, dict):
            unparsed += 1
            continue
        if not any(k in summary for k in _REDUCE_KEYS):
            # A map batch that failed JSON parsing ({"raw": ...}), a
            # truncated carry-over, or any unexpected shape. Preserve the
            # content as a fact rather than dropping it — silent narrowing
            # is the exact defect this function exists to prevent.
            raw = summary.get("raw") or summary.get("truncated_summary")
            content = str(raw) if raw else json.dumps(summary, default=str)
            merged["facts"].append(
                {"content": content, "video_title": "", "channel_name": ""}
            )
            unparsed += 1
            continue
        for key in _REDUCE_KEYS:
            for item in summary.get(key) or []:
                if not isinstance(item, dict):
                    # A bare string/number is a legitimate model output shape.
                    # Coerce rather than skip — dropping it is exactly the
                    # silent narrowing this stage is meant to eliminate.
                    item = {"content": str(item), "video_title": "", "channel_name": ""}
                identity = (
                    key,
                    _item_video(item),
                    str(item.get("content", "")),
                    str(item.get("timestamp_seconds", "")),
                )
                if identity in seen:
                    exact_dupes += 1
                    continue
                seen.add(identity)
                merged[key].append(item)

    notes = {
        "reduce_exact_duplicates_collapsed": exact_dupes,
        "reduce_unparsed_batches": unparsed,
        "reduce_items_in": sum(len(v) for v in merged.values()) + exact_dupes,
    }
    return merged, notes


def _compress_evenly(merged: dict, budget: int, topic: str) -> tuple[dict, dict]:
    """Fit ``merged`` into ``budget`` tokens WITHOUT dropping any video.

    The shipped pipeline's failure mode was non-uniform loss: whole videos
    vanished (46% of them in the D-055 control) while survivors kept full
    detail. Here every video gets a proportional quota, so a 200-video corpus
    yields a report that mentions 200 videos.
    """
    by_video: dict[str, dict[str, list]] = {}
    for key in _REDUCE_KEYS:
        for item in merged.get(key) or []:
            by_video.setdefault(_item_video(item), {k: [] for k in _REDUCE_KEYS})[key].append(item)

    n_videos = max(1, len(by_video))
    per_video_budget = max(200, budget // n_videos)

    kept: dict[str, list] = {k: [] for k in _REDUCE_KEYS}
    trimmed = 0
    for _vid, groups in by_video.items():
        spent = 0
        # Round-robin across categories so no category is starved for a video.
        pools = {k: list(v) for k, v in groups.items()}
        closed: set = set()
        while spent < per_video_budget and any(
            pools[k] for k in _REDUCE_KEYS if k not in closed
        ):
            for key in _REDUCE_KEYS:
                if key in closed or not pools[key]:
                    continue
                item = pools[key][0]
                cost = _count_tokens(json.dumps(item, default=str))
                if spent + cost > per_video_budget:
                    # Stop this category for this video, but LEAVE the
                    # remaining items in the pool so they are counted as
                    # trimmed rather than silently discarded.
                    closed.add(key)
                    continue
                pools[key].pop(0)
                kept[key].append(item)
                spent += cost
        trimmed += sum(len(v) for v in pools.values())

    return kept, {
        "reduce_items_trimmed": trimmed,
        "reduce_videos_represented": n_videos,
        "reduce_per_video_token_quota": per_video_budget,
    }


def reduce_summaries(state: ReportAgentState) -> dict:
    """Reduce: consolidate batch summaries into ONE dataset, losslessly when
    it fits and evenly across videos when it does not.

    Replaces the S-1.12.3 recursive pairwise LLM merge, which D-055 measured
    as the dominant source of report content loss: it applied a flat 6,000
    token output cap on EVERY round, collapsing a 1.39M-token corpus to
    <=0.43% before the writer ever saw it, and dropped whole videos rather
    than compressing uniformly.
    """
    summaries = state.get("chunk_summaries", [])
    if not summaries or state["job_type"] == "channel":
        return {"chunk_summaries": summaries}

    notes = dict(state.get("processing_notes") or {})

    # Step 1 — lossless structural union. No LLM, no content judgement.
    merged, merge_notes = _merge_structurally(summaries)
    notes.update(merge_notes)

    # Compose splits each section across as many calls as its material needs,
    # so the only bound here is the cost guard — not a per-call window.
    target_budget = _MAX_COMPOSE_INPUT_TOKENS
    total_tokens = _count_tokens(json.dumps(merged, default=str))
    notes["reduce_tokens_lossless"] = total_tokens
    notes["reduce_budget"] = target_budget

    if total_tokens <= target_budget:
        logger.info(
            "reduce_summaries: lossless merge fits (%d <= %d tokens); "
            "%d items across %d videos, 0 LLM calls",
            total_tokens, target_budget,
            sum(len(v) for v in merged.values()),
            len({_item_video(i) for v in merged.values() for i in v}),
        )
        notes["reduce_items_trimmed"] = 0
        return {"chunk_summaries": [merged], "processing_notes": notes}

    # Step 2 — over budget: compress per-video EVENLY so no video is lost.
    logger.info(
        "reduce_summaries: %d tokens over budget %d (%.1fx); compressing "
        "evenly across videos",
        total_tokens, target_budget, total_tokens / max(1, target_budget),
    )
    compressed, trim_notes = _compress_evenly(merged, target_budget, state.get("topic", ""))
    notes.update(trim_notes)
    if trim_notes.get("reduce_items_trimmed"):
        logger.warning(
            "reduce_summaries: %d items trimmed to fit compose budget "
            "(%d videos each kept, quota %d tokens/video)",
            trim_notes["reduce_items_trimmed"],
            trim_notes["reduce_videos_represented"],
            trim_notes["reduce_per_video_token_quota"],
        )
    return {"chunk_summaries": [compressed], "processing_notes": notes}


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

    # Always normalize, even for a single summary: the union is idempotent on
    # already-consolidated input, and it guarantees an unexpected map shape
    # still reaches the writer instead of composing an empty report.
    consolidated, _ = _merge_structurally(summaries)

    topic = state.get("topic", "")
    # Input budget per composition call. Each section is its own call, so this
    # bounds a SECTION's material rather than the whole corpus (S-1.14.8).
    section_input_budget = _batch_budget("report_compose", fraction=0.6)
    ceiling = max_output_for(resolve_config("report_compose").model)

    # R4 / D-064: depth policy. The multiplier shifts where we sit on the
    # derived curve; the guidance is what actually moves length (D-062). This
    # is NOT a cap — the budget still tracks corpus size continuously.
    length_pref = state.get("output_length")
    length_scale = output_length_policy.resolve_scale(statistics, length_pref)
    length_guidance = output_length_policy.guidance(statistics, length_pref)
    logger.info(
        "compose_report: length policy %s",
        output_length_policy.describe(statistics, length_pref),
    )

    parts: list[str] = []
    digest: list[str] = []
    sections_failed = 0

    for spec in REPORT_SECTIONS:
        items = consolidated.get(spec["key"]) or []
        if not items:
            continue
        # Split a large section across several calls so total output scales
        # with the corpus instead of being clipped by one completion cap.
        groups = _split_items_to_budget(items, section_input_budget)
        for idx, group in enumerate(groups, 1):
            material = json.dumps(group, indent=2, default=str)
            material_tokens = _count_tokens(material)
            # Prose expands on structured input; allow generous headroom,
            # then apply the depth policy (R4).
            max_tokens = min(
                int(material_tokens * 1.2 * length_scale) + 1_000, ceiling
            )
            part_note = f", part {idx} of {len(groups)}" if len(groups) > 1 else ""
            heading_note = (
                " (this is a continuation — use <h3> sub-headings only, omit the <h2>)"
                if idx > 1 else ""
            )
            prompt = COMPOSE_SECTION_PROMPT.format(
                topic=topic,
                section_title=spec["title"],
                section_guidance=(
                    spec["guidance"] + "\n\n" + length_guidance
                    if length_guidance
                    else spec["guidance"]
                ),
                item_count=len(group),
                part_note=part_note,
                material=material,
                heading_note=heading_note,
            )
            try:
                html = _invoke_with_retry(
                    "report_compose", prompt, max_tokens=max_tokens, temperature=0.2,
                    label=f"compose_report[{spec['title']}{part_note}]",
                )
                parts.append(html)
                digest.append(f"{spec['title']}{part_note}: {len(group)} items")
            except Exception as e:
                sections_failed += 1
                logger.error(
                    "compose_report: section %s%s failed (%s)", spec["title"], part_note, e
                )

    if not parts:
        return {"final_html": "<p>Report generation failed: no sections could be composed.</p>"}

    # Executive summary LAST, so it summarizes what was actually written.
    summary_html = ""
    try:
        summary_html = _invoke_with_retry(
            "report_compose",
            COMPOSE_SUMMARY_PROMPT.format(
                topic=topic,
                statistics=json.dumps(statistics, indent=2),
                section_digest="\n".join(f"- {d}" for d in digest),
            ),
            max_tokens=min(4_000, ceiling), temperature=0.2,
            label="compose_report[executive summary]",
        )
    except Exception as e:
        logger.error("compose_report: executive summary failed (%s)", e)

    # Statistics are arithmetic, not judgement — render them deterministically
    # so the section is always exact and complete (the LLM-written version
    # undercounted the corpus by 31.5% and dropped ~20 channels; D-055).
    stats_html = _render_statistics_html(statistics)

    html = "\n".join([p for p in [summary_html, *parts, stats_html] if p])
    html, broken = _strip_broken_links(html)
    if broken:
        logger.warning(
            "compose_report: unwrapped %d anchor(s) with no usable URL "
            "(extracted items lacked video_url)", broken,
        )

    logger.info(
        "compose_report: %d section call(s), %d failed, %d chars out (model %s)",
        len(parts) + (1 if summary_html else 0), sections_failed, len(html),
        resolve_config("report_compose").model,
    )

    # S-1.12.4 / S-1.14.8: loud accounting — anything dropped anywhere in the
    # pipeline is disclosed in the report itself, not just in worker logs.
    disclosures: list[str] = []
    if notes.get("map_chunks_dropped"):
        disclosures.append(
            f"{notes['map_chunks_dropped']} of {notes.get('map_chunks_total', '?')} "
            "transcript segments could not be analyzed "
            f"({notes.get('map_batches_failed', 0)} failed batch(es) after retry)"
        )
    if notes.get("reduce_items_trimmed"):
        disclosures.append(
            f"{notes['reduce_items_trimmed']} extracted items were trimmed to fit the "
            f"composition budget, applied evenly across "
            f"{notes.get('reduce_videos_represented', '?')} videos so every source "
            "remains represented"
        )
    if sections_failed:
        disclosures.append(f"{sections_failed} report section(s) failed to compose")
    if disclosures:
        html += (
            "\n<p style=\"color:#8a6d3b;border:1px solid #c9ba9b;padding:8px 12px;"
            "border-radius:4px;margin-top:24px\"><strong>Processing note:</strong> "
            + "; ".join(disclosures) + ".</p>"
        )
    return {"final_html": html}


_BROKEN_ANCHOR = re.compile(
    r'<a\s[^>]*href="(?!https?://)[^"]*"[^>]*>(.*?)</a>', re.I | re.S
)


def _strip_broken_links(html: str) -> tuple[str, int]:
    """Unwrap anchors whose href is not a real URL.

    Defence in depth for S-1.14.9: when an extracted item carries no
    ``video_url`` the prompt says to omit the link, but models still emit
    ``href="&t=123"``. A dead link is worse than plain text — the timestamp
    label is preserved, the broken anchor is not.
    """
    fixed, n = _BROKEN_ANCHOR.subn(r"\1", html)
    return fixed, n


# S-1.14.14: transient provider failures cost whole report sections. A single
# Anthropic 529 ("Overloaded") lost the Speaker Contributions section of the
# D-061 evaluation run — an expensive, fully recoverable loss.
_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "529",
    "overloaded", "rate limit", "timeout", "timed out",
    "temporarily unavailable", "service unavailable", "connection reset",
)
_COMPOSE_RETRIES = 3
_COMPOSE_BACKOFF_SECONDS = (5, 20, 45)


def _is_transient(exc: Exception) -> bool:
    """Whether ``exc`` looks like a retryable provider hiccup rather than a
    permanent error (bad request, auth, context overflow)."""
    msg = str(exc).lower()
    if "context" in msg and ("length" in msg or "window" in msg):
        return False
    if "invalid" in msg or "authentication" in msg or "permission" in msg:
        return False
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _invoke_with_retry(use_case: str, prompt: str, *, max_tokens: int, temperature: float,
                       label: str) -> str:
    """Invoke ``use_case`` with backoff on transient provider errors."""
    last: Exception | None = None
    for attempt in range(_COMPOSE_RETRIES):
        try:
            llm = get_llm_for(use_case, temperature=temperature, max_tokens=max_tokens)
            return response_text(llm.invoke([HumanMessage(content=prompt)]))
        except Exception as e:  # noqa: BLE001 - classified below
            last = e
            if attempt == _COMPOSE_RETRIES - 1 or not _is_transient(e):
                raise
            wait = _COMPOSE_BACKOFF_SECONDS[min(attempt, len(_COMPOSE_BACKOFF_SECONDS) - 1)]
            logger.warning(
                "%s: transient provider error (%s); retrying in %ds (attempt %d/%d)",
                label, str(e)[:120], wait, attempt + 2, _COMPOSE_RETRIES,
            )
            time.sleep(wait)
    raise last if last else RuntimeError("unreachable")


def _split_items_to_budget(items: list, budget: int) -> list[list]:
    """Split ``items`` into groups that each fit ``budget`` tokens.

    Last-line guard (inherited from S-1.12.2): a single item larger than the
    whole budget is truncated rather than sent, so no composition call can
    ever receive an over-budget prompt.
    """
    groups: list[list] = []
    current: list = []
    current_tokens = 0
    for item in items:
        cost = _count_tokens(json.dumps(item, default=str))
        if cost > budget:
            content = str(item.get("content", "")) if isinstance(item, dict) else str(item)
            logger.warning(
                "compose: single item of %d tokens exceeds the %d-token "
                "section budget; truncating it",
                cost, budget,
            )
            # Leave room for the item's own metadata keys.
            item = {**(item if isinstance(item, dict) else {}),
                    "content": _truncate_to_tokens(content, max(200, int(budget * 0.8)))}
            cost = _count_tokens(json.dumps(item, default=str))
        if current and current_tokens + cost > budget:
            groups.append(current)
            current, current_tokens = [], 0
        current.append(item)
        current_tokens += cost
    if current:
        groups.append(current)
    return groups or [[]]


def _render_statistics_html(statistics: dict) -> str:
    """Render the Statistics section deterministically from computed values."""
    if not statistics:
        return ""
    rows = sorted(
        statistics.get("channel_breakdown") or [],
        key=lambda c: c.get("word_count", 0),
        reverse=True,
    )
    total_words = statistics.get("total_words", 0) or 0
    out = [
        '<div class="section"><h2>Statistics</h2>',
        "<ul>",
        f"<li>Videos analyzed: {statistics.get('video_count', 0):,}</li>",
        f"<li>Transcripts: {statistics.get('transcript_count', 0):,}</li>",
        f"<li>Total words: {total_words:,}</li>",
        f"<li>Total minutes: {statistics.get('total_minutes', 0):,}</li>",
        f"<li>Channels represented: {len(rows):,}</li>",
        "</ul>",
    ]
    if rows:
        out.append(
            '<table class="stats-table"><thead><tr><th>Channel</th>'
            "<th>Videos</th><th>Words</th><th>Minutes</th><th>Share</th>"
            "</tr></thead><tbody>"
        )
        for c in rows:
            words = c.get("word_count", 0) or 0
            share = (words / total_words * 100) if total_words else 0
            out.append(
                f"<tr><td>{c.get('channel_name', 'Unknown')}</td>"
                f"<td>{c.get('video_count', 0):,}</td><td>{words:,}</td>"
                f"<td>{c.get('minutes', 0):,}</td><td>{share:.1f}%</td></tr>"
            )
        out.append("</tbody></table>")
    out.append("</div>")
    return "\n".join(out)


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
                parsed = json.loads(response_text(response))
            except json.JSONDecodeError:
                logger.warning("Channel map for %r returned non-JSON output", channel_name)
                parsed = {
                    "channel_name": channel_name,
                    "themes": [],
                    "highlights": [response_text(response).strip()[:500]],
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
        return {"final_html": response_text(response)}
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
    output_length: str | None = None,
) -> tuple[dict, str]:
    """
    Run the report agent.

    Returns:
    ``output_length`` (R4) is the user's optional depth override —
    None/'auto' lets the corpus size bracket decide. It scales the derived
    completion budget and changes the composer's brief; it is never a cap.

        lightweight per-channel narrative; for topic jobs it is the full
        research report composed from map-reduce summaries.
    """
    graph = build_report_graph()
    result = graph.invoke({
        "messages": [],
        "job_type": job_type,
        "topic": topic,
        "output_length": output_length,
        "transcript_chunks": transcript_chunks,
        "chunk_summaries": [],
        "report_sections": {},
        "statistics": {},
        "final_html": "",
        "processing_notes": {},
    })
    return result.get("statistics", {}), result.get("final_html", "")

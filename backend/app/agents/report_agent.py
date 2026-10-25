import html as html_lib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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
from app.agents.prompts.shared import (
    MODALITY_BOTH,
    MODALITY_FIELD_RULE,
    MODALITY_SAID,
    MODALITY_SHOWN,
    MODALITY_TAGS_NOTE,
    MODALITY_UNKNOWN,
    VISUAL_MARKER_OPEN,
    CODE_MIXED_QUOTE_FORMS,
    CODE_MIXING_NOTE,
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    compose_block,
    TEMPORAL_AWARENESS,
    TEMPORAL_EXTRACTION_NOTE,
    VISUAL_ANNOTATION_CONTRACT,
)
from app.agents.state import ReportAgentState
from app.config import settings
from app.services import attribution_guard, code_mixing_service, language_service, quote_fidelity
from app.services.visual_service import strip_annotations
from app.services.llm_service import get_llm_for, response_text
from app.services.llm_routing import (
    context_window_for,
    max_output_for,
    resolve_config,
)
from app.services import output_length as output_length_policy
from app.services import temporal_service
from app.utils import html_balance
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
#
# Raised 0.40 -> 1.0 on 2026-10-19 (S-1.14.19). The ratio was only safe while
# batches were 120K: there the model self-limits at 14K-21K output tokens.
# A 15K batch wants ~7K (47%) and was cut at 5,916, and the truncated JSON
# lost the whole batch. A completion budget is a ceiling, not a charge (only
# generated tokens are billed), so the cap itself is the right ceiling; the
# measured output ceiling still clamps it.
_MAP_EXTRACTION_RATIO = 1.0

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

    channel_agg: dict[str, dict] = {}
    unique_videos: set[str] = set()
    # Words are counted once per DOCUMENT, never summed over chunks: chunks
    # overlap by CHUNK_OVERLAP, and on a visual run they carry the
    # `[VISUAL @ ...]` descriptions. The 200-video reference job reported
    # 1,057,331 words where its transcripts held 947,239 (the overlap), and R1
    # run 10's annotated arm 55,443 where speech was 42,999 (the descriptions).
    doc_words: dict[str, int] = {}
    doc_channel: dict[str, str] = {}
    unstamped: dict[str, list[tuple[int, float, str]]] = {}
    loose_words: dict[str, int] = {}
    last_ends: dict[str, float] = {}
    # R3 / D-066: publish dates per video. The corpus spans time, and a claim
    # made in 2024 is not the same claim made in 2026 — but no prompt has ever
    # been told when anything was published.
    published_by_video: dict[str, str] = {}
    # R3 / S-1.17.2: the era each source DISCUSSES, from chunk metadata.
    era_by_video: dict[str, dict] = {}
    # T-1.16.1.6: corpus-level script profile, so a non-English corpus can
    # announce itself to the composer.
    texts_for_language: list[dict] = []

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        vid = meta.get("video_id", "")
        channel = meta.get("channel_name", "Unknown")
        ts_end = meta.get("timestamp_end", 0) or 0
        pub = meta.get("published_at") or ""
        if vid and pub and vid not in published_by_video:
            published_by_video[vid] = str(pub)[:10]
        if vid and vid not in era_by_video:
            era = temporal_service.era_from_chunk_metadata(meta)
            if era is not None:
                era_by_video[vid] = era
        texts_for_language.append({"text": chunk.get("text", "")})

        doc = _source_identity(meta)
        if not doc:
            # No identity to de-duplicate on: the chunk is all we know.
            words = len(strip_annotations(chunk.get("text", "")).split())
            loose_words[channel] = loose_words.get(channel, 0) + words
        else:
            doc_channel.setdefault(doc, channel)
            stamped = meta.get("document_word_count")
            if stamped is not None:
                doc_words.setdefault(doc, int(stamped))
            else:
                unstamped.setdefault(doc, []).append((
                    int(meta.get("chunk_index") or 0), float(meta.get("timestamp_start") or 0),
                    strip_annotations(chunk.get("text", "")),
                ))

        agg = channel_agg.get(channel)
        if agg is None:
            agg = {"videos": set(), "words": 0, "last_ends": {}}
            channel_agg[channel] = agg

        if vid:
            agg["videos"].add(vid)
            unique_videos.add(vid)
            if ts_end > agg["last_ends"].get(vid, 0):
                agg["last_ends"][vid] = ts_end
            if ts_end > last_ends.get(vid, 0):
                last_ends[vid] = ts_end

    total_minutes = round(sum(last_ends.values()) / 60) if last_ends else 0

    # Chunks built before `chunk_transcript` stamped `document_word_count`:
    # put the document back together in order without its overlap (the same
    # merge the quote check uses) and count that.
    for doc, pieces in unstamped.items():
        if doc not in doc_words:
            merged = quote_fidelity.merge_chunk_texts(text for _, _, text in sorted(pieces))
            doc_words[doc] = len(merged.split())
    for doc, words in doc_words.items():
        channel_agg[doc_channel[doc]]["words"] += words
    for channel, words in loose_words.items():
        channel_agg[channel]["words"] += words
    total_words = sum(doc_words.values()) + sum(loose_words.values())

    channel_breakdown = [
        {
            "channel_name": name,
            "video_count": len(agg["videos"]),
            "word_count": agg["words"],
            "minutes": round(sum(agg["last_ends"].values()) / 60) if agg["last_ends"] else 0,
        }
        for name, agg in channel_agg.items()
    ]

    dates = sorted(d for d in published_by_video.values() if d)
    year_counts: dict[str, int] = {}
    for d in dates:
        year_counts[d[:4]] = year_counts.get(d[:4], 0) + 1

    statistics = {
        "video_count": len(unique_videos),
        "transcript_count": len(unique_videos),
        "total_words": total_words,
        "total_minutes": total_minutes,
        "channel_breakdown": channel_breakdown,
        # R3: verified publication span. These are COMPUTED, which is exactly
        # what lets the summary describe the corpus's vintage without breaking
        # the D-062 anti-invention rule — it quotes these rather than guessing.
        # The v3 report mis-dated the corpus "2024-2025-era" when the bulk was
        # 2026 precisely because it had no such figure to quote.
        "earliest_published": dates[0] if dates else None,
        "latest_published": dates[-1] if dates else None,
        "median_published": dates[len(dates) // 2] if dates else None,
        "videos_by_year": dict(sorted(year_counts.items(), reverse=True)),
        "dated_video_count": len(dates),
        # R3 / S-1.17.2: what period the corpus is ABOUT, as distinct from
        # when it was posted. Unknown (zero known) for pre-R3 chunks.
        **temporal_service.summarize_eras(era_by_video.values()),
        # T-1.16.1.6: script shares across the corpus. `switch_points` are
        # dropped — per-chunk indices are meaningless at corpus level.
        "language_profile": {
            k: v
            for k, v in language_service.profile_segments(texts_for_language).items()
            if k != "switch_points"
        },
    }

    return {"statistics": statistics}


class MapOutputError(RuntimeError):
    """A map response that cannot be used as-is: cut off at the completion
    budget, or not JSON. Raised so the bisect-retry path re-runs the batch in
    halves; before S-1.14.19 it came back as ``{"raw": text}``, counted as a
    success, and reached the composer as one unattributed half-written fact.
    """


# finish_reason / stop_reason values meaning "ran out of output budget":
# OpenAI `length`, Anthropic `max_tokens`, Google `MAX_TOKENS`.
_LENGTH_STOPS = frozenset({"length", "max_tokens", "max_output_tokens"})


def _stopped_for_length(response: object) -> bool:
    meta = getattr(response, "response_metadata", None)
    if not isinstance(meta, dict):
        return False
    reason = meta.get("finish_reason") or meta.get("stop_reason") or ""
    return str(reason).strip().lower() in _LENGTH_STOPS


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _parse_map_json(text: str) -> dict:
    """Strict JSON object, tolerating only a code fence around it."""
    body = _FENCE.sub("", (text or "").strip())
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise MapOutputError(f"map output is not JSON ({len(text or '')} chars): {e}") from e
    if not isinstance(parsed, dict):
        raise MapOutputError(f"map output is JSON but not an object ({type(parsed).__name__})")
    return parsed


# S-1.14.19 review fixes.
# A map batch is capped so its output fits the model's output ceiling: a
# small batch writes ~47% of its input (measured), so 1.5x the ceiling leaves
# margin. Without this, a model with the 4,096-token default ceiling truncated
# every batch, and both bisected halves too, and the content was lost.
_MAP_INPUT_PER_OUTPUT = 1.5
_MIN_MAP_BATCH_TOKENS = 2_000
# A truncated response is bisected until it fits, up to 2**4 pieces. Any
# other failure keeps the single level of S-1.12.6.
_MAP_MAX_BISECT_DEPTH = 4
# Completion budgets are rounded up to this step, so a handful of clients
# serve every batch size.
_MAP_BUDGET_STEP = 4_096

# S-1.14.20: a source a packed batch starved is re-mapped on its own. Solo,
# no source in the R1 corpus extracted below 0.77 items per chunk; inside a
# 120K packed batch, starved ones sat at 0.00-0.17 (notes/2026-10-19-
# map-coverage.md). Sources under 10 chunks may legitimately yield little.
_STARVED_DENSITY = 0.2
_STARVED_MIN_CHUNKS = 10
_STARVED_REMAP_TOKENS = 30_000


def _item_source_index(metas: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """(url key -> source identity, title -> source identity) for map items."""
    by_url: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for meta in metas:
        sid = _source_identity(meta)
        key = _source_key(meta.get("video_url") or meta.get("url") or meta.get("permalink"))
        if key:
            by_url.setdefault(key, sid)
        if meta.get("video_title"):
            by_title.setdefault(str(meta["video_title"]), sid)
    return by_url, by_title


def _item_source(item: dict, by_url: dict[str, str], by_title: dict[str, str]) -> str | None:
    return by_url.get(_source_key(item.get("video_url"))) or by_title.get(str(item.get("video_title") or ""))


def _starved_sources(metas: list[dict], summaries: list, by_url: dict, by_title: dict) -> list[str]:
    """Sources with at least ``_STARVED_MIN_CHUNKS`` chunks whose items per
    chunk fell under ``_STARVED_DENSITY``, in first-appearance order."""
    chunk_counts: dict[str, int] = {}
    for meta in metas:
        sid = _source_identity(meta)
        chunk_counts[sid] = chunk_counts.get(sid, 0) + 1
    item_counts: dict[str, int] = {}
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        for key in _REDUCE_KEYS:
            for item in summary.get(key) or []:
                if isinstance(item, dict):
                    sid = _item_source(item, by_url, by_title)
                    if sid:
                        item_counts[sid] = item_counts.get(sid, 0) + 1
    return [
        sid for sid, n in chunk_counts.items()
        if n >= _STARVED_MIN_CHUNKS and item_counts.get(sid, 0) / n < _STARVED_DENSITY
    ]


def _without_sources(summary: dict, drop: set[str], by_url: dict, by_title: dict) -> dict:
    """``summary`` minus the items of the sources in ``drop``."""
    if not isinstance(summary, dict):
        return summary
    out = dict(summary)
    for key in _REDUCE_KEYS:
        items = summary.get(key)
        if isinstance(items, list):
            out[key] = [it for it in items
                        if not (isinstance(it, dict) and _item_source(it, by_url, by_title) in drop)]
    return out


def _map_call_budget(batch_tokens: int, cap: int) -> int:
    """Completion budget for ONE map call: its own input size times
    ``_MAP_EXTRACTION_RATIO``, rounded up to ``_MAP_BUDGET_STEP``, at least
    ``_MIN_COMPLETION_TOKENS`` and at most ``cap``. Sizing each call to its own
    batch keeps the tokens a call reserves against a rate limit in proportion
    to what it can write (a 2K single-source batch no longer reserves 30K)."""
    want = max(_MIN_COMPLETION_TOKENS, int(batch_tokens * _MAP_EXTRACTION_RATIO))
    stepped = -(-want // _MAP_BUDGET_STEP) * _MAP_BUDGET_STEP
    return max(1, min(stepped, cap))


def _invoke_map_with_retry(llm, prompt: str, label: str):
    """``llm.invoke`` with backoff on transient provider errors. Map calls run
    concurrently, so a 429 is expected rather than exceptional; bisecting on
    it would halve a batch for no reason and could drop content."""
    for attempt in range(_COMPOSE_RETRIES):
        try:
            return llm.invoke([HumanMessage(content=prompt)])
        except Exception as e:  # noqa: BLE001 - classified below
            if attempt == _COMPOSE_RETRIES - 1 or not _is_transient(e):
                raise
            wait = _COMPOSE_BACKOFF_SECONDS[min(attempt, len(_COMPOSE_BACKOFF_SECONDS) - 1)]
            logger.warning(
                "%s: transient provider error (%s); retrying in %ds (attempt %d/%d)",
                label, str(e)[:120], wait, attempt + 2, _COMPOSE_RETRIES,
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")


def map_chunks(state: ReportAgentState) -> dict:
    """Map: process transcript chunks in batches, extract structured data."""
    if state["job_type"] == "channel":
        return {"chunk_summaries": []}

    chunks = state.get("transcript_chunks", [])
    if not chunks:
        return {"chunk_summaries": []}

    # S-1.14.19: the map cap is its own setting. Item yield per call
    # saturates, so the window-derived budget (120K) starved late sources.
    budget_per_batch = min(_batch_budget("report_map_chunks"), int(settings.REPORT_MAP_BATCH_TOKENS))
    map_model = resolve_config("report_map_chunks").model
    budget_per_batch = min(
        budget_per_batch, max(_MIN_MAP_BATCH_TOKENS, int(max_output_for(map_model) * _MAP_INPUT_PER_OUTPUT))
    )
    batching = str(settings.REPORT_MAP_BATCHING or "packed").strip().lower()
    if batching not in ("packed", "source"):
        logger.warning("map_chunks: unknown REPORT_MAP_BATCHING %r; using 'packed'", batching)
        batching = "packed"
    # S-1.14.8: the completion budget tracks the batch it must summarize.
    # Previously pinned at 3,000 while batches grew to ~116K (E-1.12), which
    # silently discarded ~94% of the extractable content (D-055).
    map_max_tokens = _completion_budget(
        "report_map_chunks", budget_per_batch, _MAP_EXTRACTION_RATIO
    )
    llms: dict[int, object] = {}
    llms_lock = threading.Lock()

    def _llm_for(batch_tokens: int) -> tuple[int, object]:
        budget = _map_call_budget(batch_tokens, map_max_tokens)
        with llms_lock:
            if budget not in llms:
                llms[budget] = get_llm_for("report_map_chunks", temperature=0.0, max_tokens=budget)
            return budget, llms[budget]

    logger.info(
        "map_chunks: %d chunks, %s batching, batch budget %d tokens, completion budget up to %d "
        "(model %s, output ceiling %d)",
        len(chunks), batching, budget_per_batch, map_max_tokens,
        map_model, max_output_for(map_model),
    )

    # S-1.18.8: sources that carry at least one visual annotation. Every item
    # from any OTHER source is speech by construction, so its label is fixed
    # here rather than trusted to the model.
    visual_sources = _visual_source_keys(ch.get("metadata") or {} for ch in chunks)
    # N-002: every source's own text, so kept `original` wording can be
    # checked against the transcript it claims to come from.
    source_texts = _source_texts_for_verification(chunks)
    # S-1.18.9: each source's speech and spans, so an item's details shown on
    # screen and not found in the speech around its moment are named from
    # evidence, not from how they read.
    guard_evidence = _guard_evidence(chunks)

    # Group chunks into batches. `batch_metas` runs parallel to `batches` so
    # the S-1.14.6 audit record can say which videos a batch covered.
    batches = []
    batch_metas: list[list[dict]] = []
    batch_tokens: list[list[int]] = []
    current_batch = []
    current_metas: list[dict] = []
    current_item_tokens: list[int] = []
    current_tokens = 0
    current_source: str | None = None

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
        # R3: the extractor cannot date a claim it was never told the date of.
        pub = str(meta.get("published_at") or "")[:10]
        # S-1.17.2: ... nor tell a 2026 source about 2019 from a 2019 source.
        era = temporal_service.era_for_prompt(temporal_service.era_from_chunk_metadata(meta))
        # N-002: the source's measured language mix and quote form, so the
        # extractor knows romanised Hindi is Hindi and when to keep wording.
        # Empty for English sources.
        speech = code_mixing_service.source_note(meta)
        formatted = (
            f"[{meta.get('video_title', 'Unknown')} | {meta.get('channel_name', 'Unknown')} | "
            f"{format_timestamp(meta.get('timestamp_start', 0))}"
            f"{' | published ' + pub if pub else ''}"
            f"{' | ' + era if era else ''}"
            f"{' | ' + speech if speech else ''}"
            f"{' | ' + url if url else ''}]\n{text}"
        )
        tokens = _count_tokens(formatted)
        source = _source_identity(meta)
        # S-1.14.19: in `source` mode a new source always starts a new call,
        # so no batch ever mixes two sources' speech, spans or scripts.
        new_source = batching == "source" and source != current_source

        if current_batch and (new_source or current_tokens + tokens > budget_per_batch):
            batches.append(current_batch)
            batch_metas.append(current_metas)
            batch_tokens.append(current_item_tokens)
            current_batch = []
            current_metas = []
            current_item_tokens = []
            current_tokens = 0

        current_batch.append(formatted)
        current_metas.append(meta)
        current_item_tokens.append(tokens)
        current_tokens += tokens
        current_source = source

    if current_batch:
        batches.append(current_batch)
        batch_metas.append(current_metas)
        batch_tokens.append(current_item_tokens)

    def _invoke_batch(batch_items: list[str], item_tokens: list[int],
                      modality_counts: dict, original_counts: dict, guard_counts: dict) -> dict:
        """One map call. Returns the parsed summary; raises on invocation
        failure, on a response cut off at the completion budget, and on a
        response that is not a JSON object (S-1.14.19), so the caller's
        bisect-retry handles all three alike."""
        # T-1.16.1.6: per-batch script profile. Empty for plain English, so
        # the common case costs no tokens.
        language_note = language_service.describe_for_prompt(
            language_service.profile_segments([{"text": t} for t in batch_items])
        )
        prompt = MAP_CHUNK_PROMPT.format(
            topic=state.get("topic", ""),
            chunks="\n\n".join(batch_items),
            english_contract=ENGLISH_OUTPUT_CONTRACT,
            code_mixing=CODE_MIXING_NOTE,
            temporal_extraction=TEMPORAL_EXTRACTION_NOTE,
            visual_annotations=VISUAL_ANNOTATION_CONTRACT,
            modality_rule=MODALITY_FIELD_RULE,
            language_note=language_note,
        )
        budget, call_llm = _llm_for(sum(item_tokens))
        response = _invoke_map_with_retry(call_llm, prompt, label=f"map ({len(batch_items)} chunks)")
        if _stopped_for_length(response):
            raise MapOutputError(
                f"map output reached the {budget}-token completion budget "
                f"over {len(batch_items)} chunks"
            )
        parsed = _parse_map_json(response_text(response))
        # S-1.18.8: fix the label at the stage that read the speech.
        batch_has_visual = any(VISUAL_MARKER_OPEN in t for t in batch_items)
        _label_modality(parsed, visual_sources, batch_has_visual, modality_counts)
        # S-1.18.9: then correct the label from the item's own details. A guard
        # failure must never fail the batch: that would bisect and drop content.
        if guard_evidence is not None:
            try:
                attribution_guard.label_items(parsed, guard_evidence, guard_counts)
            except Exception:  # noqa: BLE001 - counted and logged; the labels stand as mapped
                logger.exception("map_chunks: attribution guard failed on one batch; its labels stand")
                guard_counts["failed"] = guard_counts.get("failed", 0) + 1
        # N-002: "copied EXACTLY" enforced in code, before the audit record.
        _verify_originals(parsed, source_texts, original_counts)
        return parsed

    def _run_batch(i: int) -> dict:
        """Map batch ``i`` with bisect-retry (S-1.12.6): a failed batch is split
        in half and each half retried before any content is declared lost. A
        truncated or non-JSON response (MapOutputError) keeps halving until
        it fits, up to ``_MAP_MAX_BISECT_DEPTH`` levels; any other failure
        gets the single level it always had. Counts are local to the batch
        and merged in batch order afterwards, so concurrent batches never
        share a counter. Bisected pieces are numbered 0, 1, ... in order."""
        out = {"pairs": [], "failed": 0, "dropped": 0,
               "modality": {}, "originals": {"kept": 0, "dropped": 0}, "guard": {}}
        leaf = [0]

        def _sub(depth: int) -> int | None:
            if depth == 0:
                return None
            n = leaf[0]
            leaf[0] += 1
            return n

        def _attempt(items: list[str], metas: list[dict], toks: list[int], depth: int) -> None:
            try:
                summary = _invoke_batch(items, toks, out["modality"], out["originals"], out["guard"])
            except Exception as e:  # noqa: BLE001 - every failure is bisected or recorded
                limit = _MAP_MAX_BISECT_DEPTH if isinstance(e, MapOutputError) else 1
                if len(items) >= 2 and depth < limit:
                    logger.warning(
                        f"Map batch {i + 1}/{len(batches)} failed ({e}); "
                        f"bisecting {len(items)} chunks and retrying halves"
                    )
                    mid = len(items) // 2
                    _attempt(items[:mid], metas[:mid], toks[:mid], depth + 1)
                    _attempt(items[mid:], metas[mid:], toks[mid:], depth + 1)
                    return
                out["failed"] += 1
                out["dropped"] += len(items)
                out["pairs"].append((None, _map_record(i, _sub(depth), None, metas, map_model, error=e)))
                if depth == 0:
                    logger.error(f"Map batch {i + 1} unrecoverable (single chunk); content dropped")
                else:
                    logger.error(
                        f"Map batch {i + 1} piece failed after bisect ({e}); "
                        f"{len(items)} chunks dropped from the report"
                    )
                return
            out["pairs"].append((summary, _map_record(i, _sub(depth), summary, metas, map_model)))

        _attempt(batches[i], batch_metas[i], batch_tokens[i], 0)
        return out

    # S-1.14.19: batches are independent; run several at once. `map` keeps
    # results in batch order whatever order the calls finish in.
    workers = max(1, min(int(settings.REPORT_MAP_CONCURRENCY or 1), len(batches)))
    if workers == 1:
        results = [_run_batch(i) for i in range(len(batches))]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_run_batch, range(len(batches))))

    # S-1.14.20: a packed batch can starve a source (the model writes a
    # roughly fixed number of items per call). Re-map each starved source on
    # its own and let those items replace the thin ones; the other sources
    # keep their packed extraction.
    all_metas = [m for ms in batch_metas for m in ms]
    by_url, by_title = _item_source_index(all_metas)
    first_pass = [summary for res in results for summary, _ in res["pairs"] if summary is not None]
    starved = _starved_sources(all_metas, first_pass, by_url, by_title) if batching == "packed" else []
    remap_start = len(batches)
    if starved:
        groups: dict[str, tuple[list, list, list]] = {sid: ([], [], []) for sid in starved}
        for items_, metas_, toks_ in zip(batches, batch_metas, batch_tokens):
            for item, meta, tok in zip(items_, metas_, toks_):
                sid = _source_identity(meta)
                if sid in groups:
                    groups[sid][0].append(item)
                    groups[sid][1].append(meta)
                    groups[sid][2].append(tok)
        for sid in starved:
            items_, metas_, toks_ = groups[sid]
            cur: tuple[list, list, list] = ([], [], [])
            for item, meta, tok in zip(items_, metas_, toks_):
                if cur[0] and sum(cur[2]) + tok > min(_STARVED_REMAP_TOKENS, budget_per_batch):
                    batches.append(cur[0]); batch_metas.append(cur[1]); batch_tokens.append(cur[2])
                    cur = ([], [], [])
                cur[0].append(item); cur[1].append(meta); cur[2].append(tok)
            if cur[0]:
                batches.append(cur[0]); batch_metas.append(cur[1]); batch_tokens.append(cur[2])
        logger.warning(
            "map_chunks: %d source(s) starved by packed batching; re-mapping them alone in %d call(s)",
            len(starved), len(batches) - remap_start,
        )
        remap_ids = list(range(remap_start, len(batches)))
        if workers == 1 or len(remap_ids) == 1:
            remap_results = [_run_batch(i) for i in remap_ids]
        else:
            with ThreadPoolExecutor(max_workers=min(workers, len(remap_ids))) as pool:
                remap_results = list(pool.map(_run_batch, remap_ids))
        drop = set(starved)
        for res in results:
            res["pairs"] = [(_without_sources(sm, drop, by_url, by_title) if sm is not None else None, rec)
                            for sm, rec in res["pairs"]]
        results = results + remap_results

    summaries = []
    records: list[dict] = []
    modality_counts: dict[str, int] = {}
    original_counts: dict = {"kept": 0, "dropped": 0}
    guard_counts: dict[str, int] = {}
    failed_batches = 0
    dropped_chunk_groups = 0
    for res in results:
        for summary, record in res["pairs"]:
            if summary is not None:
                summaries.append(summary)
            records.append(record)
        failed_batches += res["failed"]
        dropped_chunk_groups += res["dropped"]
        for k, v in res["modality"].items():
            modality_counts[k] = modality_counts.get(k, 0) + v
        for k, v in res["guard"].items():
            guard_counts[k] = guard_counts.get(k, 0) + v
        original_counts["kept"] += res["originals"]["kept"]
        original_counts["dropped"] += res["originals"]["dropped"]
        original_counts["trimmed"] = original_counts.get("trimmed", 0) + res["originals"].get("trimmed", 0)
        for k, v in (res["originals"].get("reasons") or {}).items():
            original_counts.setdefault("reasons", {})
            original_counts["reasons"][k] = original_counts["reasons"].get(k, 0) + v

    notes = dict(state.get("processing_notes") or {})
    notes.update(
        {
            "map_batches": remap_start,
            "map_batching": batching,
            "map_sources_remapped": len(starved),
            "map_remap_calls": len(batches) - remap_start,
            "map_batch_tokens": budget_per_batch,
            "map_batches_failed": failed_batches,
            "map_chunks_dropped": dropped_chunk_groups,
            "map_chunks_total": len(chunks),
            "map_modality": dict(sorted(modality_counts.items())),
            # S-1.18.9: items whose details were screen-only around their
            # moment, listed for compose (never relabelled, T-1.18.9.11).
            "map_attribution_guard": dict(sorted(guard_counts.items())),
            "map_originals_kept": original_counts["kept"],
            "map_originals_dropped": original_counts["dropped"],
            # Kept after the speaker's words were separated from a
            # transliteration / translation the model appended (counted in kept).
            "map_originals_trimmed": original_counts.get("trimmed", 0),
            "map_originals_dropped_by_reason": dict(sorted(original_counts.get("reasons", {}).items())),
        }
    )
    if original_counts["dropped"]:
        logger.warning(
            "map_chunks: dropped %d of %d `original` quotes not found word for "
            "word in their own source's transcript",
            original_counts["dropped"], original_counts["kept"] + original_counts["dropped"],
        )
    if failed_batches:
        logger.error(
            "map_chunks: %d batch(es) failed permanently; ~%d of %d chunks "
            "excluded from the report",
            failed_batches, dropped_chunk_groups, len(chunks),
        )
    return {
        "chunk_summaries": summaries,
        "processing_notes": notes,
        "map_batch_records": records,
    }


_REDUCE_KEYS = ("facts", "comments", "conclusions", "references", "speakers")


# --- N-002: kept wording must be the source's own words ------------------------

def _source_identity(meta: dict) -> str:
    return str(
        meta.get("document_id") or meta.get("video_id")
        or _source_key(meta.get("video_url") or meta.get("url") or meta.get("permalink"))
        or meta.get("video_title") or ""
    )


def _source_texts_for_verification(chunks: list[dict]) -> dict:
    """``{"videos": {source: VideoText}, "by_url": {...}, "by_title": {...}}``.

    Each source's chunks are put back in order, merged without their overlap
    (so a quote spanning a chunk boundary still matches) and stripped of
    `[VISUAL @]` spans: an `original` is something SAID.
    """
    by_source: dict[str, list[tuple[float, int, str]]] = {}
    titles: dict[str, str] = {}
    by_url: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for ch in chunks:
        meta = ch.get("metadata") or {}
        sid = _source_identity(meta)
        if not sid:
            continue
        order = (float(meta.get("timestamp_start") or 0), int(meta.get("chunk_index") or 0))
        by_source.setdefault(sid, []).append((*order, strip_annotations(ch.get("text") or "")))
        titles.setdefault(sid, str(meta.get("video_title") or ""))
        for key in (meta.get("video_url"), meta.get("url"), meta.get("permalink")):
            if _source_key(key):
                by_url.setdefault(_source_key(key), sid)
        if meta.get("video_title"):
            by_title.setdefault(str(meta["video_title"]), sid)
    videos = {
        sid: quote_fidelity.VideoText.from_raw(
            titles[sid], quote_fidelity.merge_chunk_texts(t for _, _, t in sorted(parts))
        )
        for sid, parts in by_source.items()
    }
    return {"videos": videos, "by_url": by_url, "by_title": by_title}


def _verify_originals(parsed: object, sources: dict, counts: dict) -> None:
    """Drop any `original` that does not trace back to its own source's speech.

    The rule is `quote_fidelity.problem` — the same definition the R1 run-6
    gate (`scripts/audit_quote_fidelity.py`) audits with, so the pipeline keeps
    exactly what the gate passes: verbatim or near (caption spelling) against
    the item's OWN source, no word mixing two scripts, no script other than
    the source's. The source is resolved through the item's `video_url`, then
    its title; an item that resolves to none cannot be checked and loses its
    `original` too. A dropped value is kept as `original_rejected` (with
    `original_rejected_reason`) so the persisted map record shows what was
    removed; the composer never sees it. The English `content` always
    survives.

    `quote_fidelity.keepable` also separates the speaker's words from what a
    model appended (a transliteration line, a translation, a bracketed gloss
    the speaker never said) and keeps the speech, with the rest recorded as
    `original_stripped`; that reading must pass the same check in full.
    """
    if not isinstance(parsed, dict):
        return
    for key in _REDUCE_KEYS:
        for item in parsed.get(key) or []:
            if not isinstance(item, dict) or not item.get("original"):
                continue
            original = str(item["original"])
            sid = sources["by_url"].get(_source_key(item.get("video_url"))) or sources["by_title"].get(
                str(item.get("video_title") or "")
            )
            own = sources["videos"].get(sid) if sid else None
            reading, removed, reason = quote_fidelity.keepable(original, own)
            if reading is not None:
                if reading != original:
                    # Speech kept; the transliteration / translation / gloss
                    # the model appended is recorded for the audit.
                    item["original"] = reading
                    item["original_stripped"] = removed
                    counts["trimmed"] = counts.get("trimmed", 0) + 1
                counts["kept"] += 1
                continue
            item.pop("original", None)
            item["original_rejected"] = original
            item["original_rejected_reason"] = reason
            counts["dropped"] += 1
            counts.setdefault("reasons", {})
            counts["reasons"][reason] = counts["reasons"].get(reason, 0) + 1


# --- S-1.18.8: modality provenance -----------------------------------------
#
# D-075: the composer inferred said-vs-shown from interleaved text and got it
# wrong in both directions, worst where it could not read the speech. The
# label is now fixed at map, where the model reads one chunk of native speech
# at a time; reduce carries it; compose renders it as a tag.

_MODALITY_SYNONYMS = {
    "said": MODALITY_SAID, "spoken": MODALITY_SAID, "speech": MODALITY_SAID,
    "audio": MODALITY_SAID, "verbal": MODALITY_SAID,
    "shown": MODALITY_SHOWN, "screen": MODALITY_SHOWN, "on_screen": MODALITY_SHOWN,
    "on-screen": MODALITY_SHOWN, "on screen": MODALITY_SHOWN, "visual": MODALITY_SHOWN,
    "displayed": MODALITY_SHOWN,
    "both": MODALITY_BOTH, "said+shown": MODALITY_BOTH, "said and shown": MODALITY_BOTH,
    "said/shown": MODALITY_BOTH,
}

_MODALITY_TAG = {
    MODALITY_SAID: "[SAID]",
    MODALITY_SHOWN: "[SHOWN]",
    MODALITY_BOTH: "[SAID+SHOWN]",
    MODALITY_UNKNOWN: "[UNLABELLED]",
}


def _source_keys_of(meta_or_item: dict) -> list[str]:
    """Identity keys of a source, shared by chunk metadata and map items."""
    keys = [
        _source_key(meta_or_item.get(k))
        for k in ("video_url", "url", "permalink")
        if _source_key(meta_or_item.get(k))
    ]
    title = meta_or_item.get("video_title")
    if title:
        keys.append(f"title:{title}")
    return keys


def _visual_source_keys(metas) -> set[str]:
    """Keys of every source with at least one visual annotation in its chunks."""
    keys: set[str] = set()
    for meta in metas:
        if int(meta.get("visual_frame_count") or 0) > 0:
            keys.update(_source_keys_of(meta))
    return keys


def _normalise_modality(value: object) -> str:
    text = str(value or "").strip().lower()
    return _MODALITY_SYNONYMS.get(text, MODALITY_UNKNOWN)


def _label_modality(
    summary: object,
    visual_sources: set[str],
    batch_has_visual: bool,
    counts: dict[str, int] | None = None,
) -> None:
    """Set ``modality`` on every item of one parsed map summary, in place.

    An item from a source with no visual annotation is "said" whatever the
    model wrote: there was nothing on screen for it to come from. Elsewhere
    the model's label stands after normalisation, and a missing or unusable
    label becomes "unknown" rather than a guess. Where the pipeline overrides
    the model, the model's own value is kept as ``modality_model`` so the
    persisted map record (S-1.14.6) shows both.
    """
    if not isinstance(summary, dict):
        return
    for key in _REDUCE_KEYS:
        items = summary.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw = item.get("modality")
            item_keys = _source_keys_of(item)
            if item_keys:
                has_visual = any(k in visual_sources for k in item_keys)
            else:
                has_visual = batch_has_visual
            label = MODALITY_SAID if not has_visual else _normalise_modality(raw)
            if raw is not None and str(raw).strip().lower() != label:
                item["modality_model"] = raw
            item["modality"] = label
            if counts is not None:
                counts[label] = counts.get(label, 0) + 1
                if not has_visual and _normalise_modality(raw) in (MODALITY_SHOWN, MODALITY_BOTH):
                    counts["forced_said"] = counts.get("forced_said", 0) + 1


def _combine_modality(a: object, b: object) -> str:
    """Union of two pieces of evidence for the same item."""
    labels = {str(a or MODALITY_UNKNOWN), str(b or MODALITY_UNKNOWN)} - {MODALITY_UNKNOWN}
    if not labels:
        return MODALITY_UNKNOWN
    if MODALITY_BOTH in labels or labels == {MODALITY_SAID, MODALITY_SHOWN}:
        return MODALITY_BOTH
    return labels.pop()


def _uses_modality_tags(consolidated: dict) -> bool:
    """Tags are rendered only when some item was shown on screen.

    A corpus with no visual evidence would get [SAID] on every item and an
    instruction block about tags it can never act on — tokens for nothing.
    """
    return any(
        isinstance(item, dict) and item.get("modality") in (MODALITY_SHOWN, MODALITY_BOTH)
        for items in consolidated.values()
        for item in items or []
    )


_PIPELINE_ONLY_KEYS = (
    "modality", "modality_model", "original_rejected", "original_rejected_reason",
    "original_stripped", "screen_only", "modality_before_guard",
)


def _render_items_for_compose(items: list, tagged: bool) -> list:
    """Copies of ``items`` as the composer should read them.

    With tags: content is prefixed with the evidence tag. An item whose
    details were screen-only around its moment (S-1.18.9, `screen_only`) names them in
    the tag — "[SAID+SHOWN; shown on screen: 17,363.10 | 18,158.38]" — so the
    composer knows exactly what it may not credit to the speaker. Either way
    the pipeline-only keys are dropped — the tag carries the label, a
    rejected original must never reach the composer, and the persisted
    records keep the raw fields. Never mutates the consolidated items.
    """
    rendered: list = []
    for item in items:
        if not isinstance(item, dict):
            rendered.append(item)
            continue
        copy = {k: v for k, v in item.items() if k not in _PIPELINE_ONLY_KEYS}
        if tagged:
            tag = _MODALITY_TAG.get(item.get("modality"), _MODALITY_TAG[MODALITY_UNKNOWN])
            listed = [str(d) for d in item.get("screen_only") or [] if str(d).strip()]
            if listed and item.get("modality") != MODALITY_SHOWN:
                tag = f"[SAID+SHOWN; shown on screen: {' | '.join(dict.fromkeys(listed))}]"
            copy["content"] = f"{tag} {copy.get('content', '')}"
        rendered.append(copy)
    return rendered


# Speaker fields that name a role, not a person: no use for telling who a sentence credits.
_GENERIC_SPEAKERS = {"", "presenter", "speaker", "instructor", "host", "narrator", "unknown", "teacher",
                     "tutor", "creator", "author", "the presenter", "the instructor", "the speaker"}


def _guard_evidence(chunks: list[dict], items: dict | None = None) -> "attribution_guard.Evidence | None":
    """S-1.18.9 evidence for ``chunks``, or None when the guard is off or no source has a span.

    ``items`` (the consolidated map items) contributes speakers' names, so
    "Vivek says ..." is read as a credit.
    """
    if not settings.REPORT_ATTRIBUTION_GUARD_ENABLED or not chunks:
        return None
    names = {
        str(item.get("speaker") or "").strip()
        for group in (items or {}).values() for item in group or []
        if isinstance(item, dict)
    }
    evidence = attribution_guard.build_evidence(
        chunks, [n for n in names if n.lower() not in _GENERIC_SPEAKERS]
    )
    return evidence if evidence.has_visual else None


def _count_items(summary: object) -> int:
    """Items across the five reduce keys of one summary dict."""
    if not isinstance(summary, dict):
        return 0
    return sum(
        len(summary.get(k) or []) for k in _REDUCE_KEYS
        if isinstance(summary.get(k), list)
    )


def _map_record(
    batch_index: int,
    sub_index: int | None,
    summary: dict | None,
    metas: list[dict],
    model: str,
    error: Exception | None = None,
) -> dict:
    """S-1.14.6 audit record for one map call, serialised NOW.

    Compose later mutates the very item dicts map produced (quote forms,
    S-1.18.8 tags); serialising here keeps the record faithful to what map
    emitted.
    """
    from app.models.job_report_intermediate import MAP_FAILED, MAP_PARSED, MAP_UNPARSED

    videos = list(dict.fromkeys(
        str(m.get("video_title") or m.get("video_id") or "") for m in metas
    ))
    if error is not None:
        status = MAP_FAILED
    elif isinstance(summary, dict) and any(k in summary for k in _REDUCE_KEYS):
        status = MAP_PARSED
    else:
        status = MAP_UNPARSED
    notes: dict = {"videos": [v for v in videos if v]}
    if error is not None:
        notes["error"] = f"{type(error).__name__}: {str(error)[:500]}"
    return {
        "batch_index": batch_index,
        "sub_index": sub_index,
        "status": status,
        "chunk_count": len(metas),
        "item_count": _count_items(summary),
        "payload_json": (
            None if summary is None
            else json.dumps(summary, ensure_ascii=False, default=str)
        ),
        "notes_json": json.dumps(notes, ensure_ascii=False),
        "model": model,
    }


def _reduce_record(dataset: dict, notes: dict, status: str) -> dict:
    """S-1.14.6 audit record for the reduce output, serialised NOW."""
    kept = {
        k: v for k, v in notes.items()
        if k.startswith("reduce_") or k.startswith("map_")
    }
    return {
        "batch_index": 0,
        "sub_index": None,
        "status": status,
        "chunk_count": None,
        "item_count": _count_items(dataset),
        "payload_json": json.dumps(dataset, ensure_ascii=False, default=str),
        "notes_json": json.dumps(kept, ensure_ascii=False, default=str),
        "model": None,
    }


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
    seen: dict = {}
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
                    # S-1.18.8: the same item extracted twice (overlapping
                    # chunks) may carry different evidence — once from the
                    # speech, once from a span. Keep the union, not the first.
                    kept = seen[identity]
                    if item.get("modality") != kept.get("modality") and (
                        "modality" in item or "modality" in kept
                    ):
                        kept["modality"] = _combine_modality(
                            kept.get("modality"), item.get("modality")
                        )
                    continue
                seen[identity] = item
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
                cost = _count_tokens(json.dumps(item, ensure_ascii=False, default=str))
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
    total_tokens = _count_tokens(json.dumps(merged, ensure_ascii=False, default=str))
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
        return {
            "chunk_summaries": [merged],
            "processing_notes": notes,
            "reduce_record": _reduce_record(merged, notes, "lossless"),
        }

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
    return {
        "chunk_summaries": [compressed],
        "processing_notes": notes,
        "reduce_record": _reduce_record(compressed, notes, "compressed"),
    }


def _corpus_facts(statistics: dict) -> str:
    """The verified corpus figures as short prose lines for EVERY compose call.

    S-1.14.15: the summary received the statistics as a raw JSON dump (with
    a 92-entry channel breakdown burying the dates) and the body sections
    received nothing — so Conclusions wrote "well over 150 distinct videos"
    while the table said 200, and the summary mis-dated the corpus. Every
    section now gets the same compact block, and the prompts say to quote
    it exactly.
    """
    stats = statistics or {}
    lines: list[str] = []
    videos = int(stats.get("video_count") or 0)
    channels = len(stats.get("channel_breakdown") or [])
    lines.append(
        f"- Videos: {videos:,} (exact count — every section must use this figure)"
        + (f"; channels: {channels:,}" if channels else "")
    )
    words = int(stats.get("total_words") or 0)
    minutes = int(stats.get("total_minutes") or 0)
    if words or minutes:
        lines.append(f"- Transcript words: {words:,}; total minutes: {minutes:,}")
    if stats.get("earliest_published"):
        by_year = stats.get("videos_by_year") or {}
        year_text = ", ".join(f"{y}: {n}" for y, n in by_year.items())
        dated = int(stats.get("dated_video_count") or 0)
        lines.append(
            f"- Published between {stats['earliest_published']} and "
            f"{stats['latest_published']} (median {stats.get('median_published')})"
            + (f"; by year: {year_text}" if year_text else "")
            + (f"; {dated:,} of {videos:,} videos carry a publish date" if videos else "")
        )
    else:
        lines.append("- Publication dates: not available for this corpus")
    eras = temporal_service.describe_corpus_eras(stats)
    if eras:
        lines.append(f"- Discussed era: {eras[0].upper() + eras[1:]}")
    else:
        lines.append("- Discussed era: not available (sources not yet dated by content)")
    return "\n".join(lines)


_HTML_TAG = re.compile(r"<[^>]+>")
_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)


def _section_text_digest(parts: list[str], budget_tokens: int) -> str:
    """Plain-text rendering of the written sections for the summary call.

    S-1.14.15 (T-1.14.15.2): the summary used to receive only section
    titles with item counts ("Key Facts, part 1 of 2: 1,128 items"), so it
    had nothing to summarise except pipeline mechanics — and wrote them into
    the prose. It now reads what the sections SAY. Each part is abridged to
    its share of the budget so the call stays bounded on large corpora.
    """
    if not parts:
        return "(no sections)"
    per_part = max(budget_tokens // len(parts), 500)
    rendered: list[str] = []
    for html in parts:
        html = html or ""
        m = _H2.search(html)
        title = _HTML_TAG.sub("", m.group(1)).strip() if m else "Section"
        body = html[:m.start()] + html[m.end():] if m else html
        text = _HTML_TAG.sub(" ", body)
        text = re.sub(r"\s+", " ", text).strip()
        rendered.append(f"=== {title} ===\n{_truncate_to_tokens(text, per_part)}")
    return "\n\n".join(rendered)


# Tokens of written-section text the executive summary may read. Bounded for
# cost, not capability: 60K tokens is ~45K words, more than most reports.
_SUMMARY_INPUT_TOKENS = 60_000


def _source_key(value: object) -> str:
    """A source's URL without the `&t=` timestamp the map may append."""
    return str(value or "").split("&t=")[0].split("?t=")[0].strip()


def _quote_forms_by_source(chunk_metas: list[dict]) -> dict[str, str]:
    """Quote form per source (by URL and by title) for non-English sources."""
    forms: dict[str, str] = {}
    for meta in chunk_metas:
        form = code_mixing_service.quote_form(meta)
        if not form:
            continue
        for key in (meta.get("video_url"), meta.get("url"), meta.get("permalink")):
            if _source_key(key):
                forms.setdefault(_source_key(key), form)
        if meta.get("video_title"):
            forms.setdefault(f"title:{meta['video_title']}", form)
    return forms


_PLAIN_ENGLISH_FORM = "plain English (translate the borrowed words inline; no original form)"


def _attach_quote_forms(consolidated: dict, forms: dict[str, str]) -> int:
    """Set `quote_form` on every item that kept `original` wording.

    The SOURCE decides the script; the span still decides whether it is
    English at all (T-1.16.2.4's resolution). Without the second half the
    held-out evaluation quoted an English sentence the speaker said in
    Devanagari-captioned Hinglish in full three-part form.
    """
    if not forms:
        return 0
    n = 0
    for items in consolidated.values():
        for item in items or []:
            if not isinstance(item, dict) or not item.get("original"):
                continue
            form = forms.get(_source_key(item.get("video_url"))) or forms.get(
                f"title:{item.get('video_title', '')}"
            )
            if not form:
                continue
            span_mode = code_mixing_service.rendering_mode(
                code_mixing_service.analyse_span(str(item["original"]))
            )
            item["quote_form"] = (
                _PLAIN_ENGLISH_FORM if span_mode == code_mixing_service.PLAIN_ENGLISH else form
            )
            n += 1
    return n


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

    # S-1.14.15 / T-1.16.1.6: the same verified facts and language note go
    # to EVERY compose call, so no section can contradict the Statistics
    # table and a non-English corpus announces itself to the composer.
    corpus_facts = _corpus_facts(statistics)
    language_note = language_service.describe_for_prompt(
        statistics.get("language_profile") or {}
    )
    # N-002 / T-1.16.2.5: the quotation half of the bidirectional split. Map
    # items carry English `content` (what the analysis reads) and, for
    # quotable wording from a non-English source, the speaker's `original`.
    # Each such item gets its source's quote form here — from the chunk
    # metadata, deterministically — so every quote from one source is shown
    # the same way. Script profiling cannot see romanised Hindi, so the
    # corpus note counts sources from their measured profiles instead.
    chunk_metas = [ch.get("metadata") or {} for ch in state.get("transcript_chunks") or []]
    _attach_quote_forms(consolidated, _quote_forms_by_source(chunk_metas))
    language_note = compose_block(language_note, code_mixing_service.corpus_note(chunk_metas))

    # S-1.18.8 / D-075: attribute from provenance, not from how text reads.
    tagged = _uses_modality_tags(consolidated)
    modality_labels = MODALITY_TAGS_NOTE if tagged else ""

    parts: list[str] = []
    digest: list[str] = []
    sections_failed = 0
    # S-1.14.17: sections whose HTML came back unfinished and were composed
    # again, and ``(name, outcome)`` for those closed where they stopped.
    sections_retried = 0
    sections_repaired: list[tuple[str, str]] = []

    for spec in REPORT_SECTIONS:
        items = consolidated.get(spec["key"]) or []
        if not items:
            continue
        # Split a large section across several calls so total output scales
        # with the corpus instead of being clipped by one completion cap.
        groups = _split_items_to_budget(items, section_input_budget)
        for idx, group in enumerate(groups, 1):
            # ensure_ascii=False: with the default, every Devanagari or Bengali
            # `original` (and any non-English title) reached the composer as
            # \uXXXX escapes — several tokens a character, and wording the
            # model had to decode before it could quote it.
            material = json.dumps(
                _render_items_for_compose(group, tagged), ensure_ascii=False,
                indent=2, default=str,
            )
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
                english_contract=ENGLISH_OUTPUT_CONTRACT,
                quote_rules=compose_block(QUOTE_RENDERING_RULES, CODE_MIXED_QUOTE_FORMS),
                temporal=TEMPORAL_AWARENESS,
                visual_annotations=VISUAL_ANNOTATION_CONTRACT,
                modality_labels=modality_labels,
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
                corpus_facts=corpus_facts,
                language_note=language_note,
            )
            try:
                html, outcome = _compose_checked(
                    prompt, max_tokens=max_tokens, ceiling=ceiling,
                    label=f"compose_report[{spec['title']}{part_note}]",
                )
                parts.append(html)
                digest.append(f"{spec['title']}{part_note}: {len(group)} items")
                if outcome != _COMPOSED_CLEAN:
                    sections_retried += 1
                if outcome in _CLOSED_OUTCOMES:
                    sections_repaired.append((f"{spec['title']}{part_note}", outcome))
            except Exception as e:
                sections_failed += 1
                logger.error(
                    "compose_report: section %s%s failed (%s)", spec["title"], part_note, e
                )

    if not parts:
        return {"final_html": "<p>Report generation failed: no sections could be composed.</p>"}

    # S-1.18.9: a screen-only detail that a section still credits to a
    # speaker is marked where it stands. The sections are guarded BEFORE the
    # summary reads them (R1 run 8's error was the summary condensing a body
    # passage into "X reads ..."), and the summary is guarded after.
    guard_evidence = _guard_evidence(state.get("transcript_chunks") or [], consolidated)
    guard_rewrites: list = []
    guard_failures = 0

    def _guard(html: str) -> str:
        nonlocal guard_failures
        try:
            html, rewrites = attribution_guard.guard_report(html, guard_evidence)
        except Exception:  # noqa: BLE001 - disclosed below; the text stays as composed
            logger.exception("compose_report: attribution guard failed on one passage; left unguarded")
            guard_failures += 1
            return html
        guard_rewrites.extend(rewrites)
        return html

    if guard_evidence is not None:
        parts = [_guard(part) for part in parts]

    # Executive summary LAST, so it summarizes what was actually written —
    # and it now reads the written text, not a digest of item counts
    # (S-1.14.15). `digest` stays for the log line below.
    summary_html = ""
    try:
        # S-1.14.17: checked like the sections. It is placed FIRST, so an
        # unfinished summary would swallow every section after it.
        summary_html, outcome = _compose_checked(
            COMPOSE_SUMMARY_PROMPT.format(
                english_contract=ENGLISH_OUTPUT_CONTRACT,
                temporal=TEMPORAL_AWARENESS,
                visual_annotations=VISUAL_ANNOTATION_CONTRACT,
                topic=topic,
                corpus_facts=corpus_facts,
                section_text=_section_text_digest(
                    parts, min(_batch_budget("report_compose", fraction=0.5), _SUMMARY_INPUT_TOKENS)
                ),
                language_note=language_note,
            ),
            max_tokens=min(4_000, ceiling), ceiling=ceiling,
            label="compose_report[executive summary]",
        )
        if outcome != _COMPOSED_CLEAN:
            sections_retried += 1
        if outcome in _CLOSED_OUTCOMES:
            sections_repaired.insert(0, ("Executive Summary", outcome))
    except Exception as e:
        logger.error("compose_report: executive summary failed (%s)", e)
    if guard_evidence is not None and summary_html:
        summary_html = _guard(summary_html)
    if guard_rewrites:
        logger.warning(
            "compose_report: attribution guard changed %d place(s): %s", len(guard_rewrites),
            "; ".join(f"{r.kind} {r.tokens[:3]}" for r in guard_rewrites[:20]),
        )
    logger.info("compose_report: sections written — %s", "; ".join(digest))

    # Statistics are arithmetic, not judgement — render them deterministically
    # so the section is always exact and complete (the LLM-written version
    # undercounted the corpus by 31.5% and dropped ~20 channels; D-055).
    stats_html = _render_statistics_html(statistics)

    # N-002: native-script text the COMPOSER wrote must trace back to speech
    # too. The map check keeps only true originals, but R1 run 7's composer
    # back-translated an item's English into Devanagari ("वेरी इंपॉर्टेंट
    # लाइब्रेरी (very important library)") and put it in the speaker's mouth.
    # Checked on the prose only: the statistics table is ours, not quotation.
    prose = "\n".join([p for p in [summary_html, *parts] if p])
    prose, scrubbed = _scrub_unverified_quotes(prose, state.get("transcript_chunks") or [])
    html = "\n".join([p for p in [prose, stats_html] if p])
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
    if notes.get("map_originals_dropped"):
        dropped = notes["map_originals_dropped"]
        disclosures.append(
            f"{dropped} quoted passage(s) the analysis attributed to a speaker were "
            "not found word for word in that speaker's transcript and were left out "
            "(the points they supported were kept, in English)"
        )
    if scrubbed:
        disclosures.append(
            f"{sum(r['occurrences'] for r in scrubbed)} passage(s) of non-English text "
            "in the report did not match any source's speech and were removed "
            "(the English beside them was kept)"
        )
    guard_counts = {
        kind: sum(1 for r in guard_rewrites if r.kind == kind)
        for kind in ("screen_detail_marked", "speech_as_screen_marked", "screen_claim_removed")
    }
    # A detail the guard cannot find in the transcript is unmatched, not unsaid
    # (T-1.18.9.7, .11): the note says what was matched, never "only", and names
    # the sources it could not read.
    if guard_counts["screen_detail_marked"]:
        disclosures.append(
            f"{guard_counts['screen_detail_marked']} detail(s) in sentences crediting a speaker appear "
            "in a description of the screen near the cited moment but could not be matched to the "
            "speech there, and are marked \"on screen\" where they appear"
        )
    if guard_counts["speech_as_screen_marked"]:
        disclosures.append(
            f"{guard_counts['speech_as_screen_marked']} detail(s) described as shown on screen matched "
            "the speech but no captured frame of that source, and are marked as said"
        )
    if guard_counts["screen_claim_removed"]:
        disclosures.append(
            f"{guard_counts['screen_claim_removed']} claim(s) that a spoken detail was also on screen "
            "matched no captured frame of that source and were removed"
        )
    unchecked = 0
    if guard_evidence is not None:
        unchecked = sum(1 for src in guard_evidence.sources.values() if src.spans and not src.readable)
    if unchecked:
        disclosures.append(
            f"on-screen details credited to a speaker were not checked in {unchecked} source(s) whose "
            "speech is not English in Latin script, which the check cannot read"
        )
    if guard_failures:
        disclosures.append(
            f"the check that keeps on-screen details from being credited to speakers failed on "
            f"{guard_failures} passage(s), which are shown as written"
        )
    if sections_failed:
        disclosures.append(f"{sections_failed} report section(s) failed to compose")
    disclosures.extend(_closed_section_disclosures(sections_repaired))
    if disclosures:
        html += _processing_note_html(disclosures)
    out_notes = dict(notes)
    out_notes["report_sections_retried"] = sections_retried
    out_notes["report_sections_repaired"] = [name for name, _ in sections_repaired]
    out_notes["report_quotes_removed"] = sum(r["occurrences"] for r in scrubbed)
    out_notes["report_attribution_marked"] = guard_counts["screen_detail_marked"]
    out_notes["report_attribution_speech_marked"] = guard_counts["speech_as_screen_marked"]
    out_notes["report_screen_claims_removed"] = guard_counts["screen_claim_removed"]
    out_notes["report_attribution_unchecked_sources"] = unchecked
    out_notes["report_attribution_guard_failures"] = guard_failures
    out_notes["report_attribution_rewrites"] = [r.as_dict() for r in guard_rewrites]
    return {"final_html": html, "processing_notes": out_notes}


def _scrub_unverified_quotes(prose: str, chunks: list[dict]) -> tuple[str, list[dict]]:
    """Remove native-script runs in composed prose that no source said.

    Same rule as the R1 quote-fidelity gate (`quote_fidelity.scrub_report`),
    against every source's speech. Each source's title and channel name are
    admitted as well: a Devanagari video title in a citation label is not
    speech, and removing it would break the attribution rather than a quote.
    """
    if not quote_fidelity.report_native_runs(prose):
        return prose, []
    sources = _source_texts_for_verification(chunks)
    corpus = dict(sources["videos"])
    labels: dict[str, str] = {}
    for ch in chunks:
        meta = ch.get("metadata") or {}
        sid = _source_identity(meta)
        if sid and sid not in labels:
            labels[sid] = f"{meta.get('video_title') or ''} {meta.get('channel_name') or ''}"
    for sid, label in labels.items():
        if label.strip():
            corpus[f"label:{sid}"] = quote_fidelity.VideoText.from_raw(label, label)
    prose, removed = quote_fidelity.scrub_report(prose, corpus)
    if removed:
        logger.warning(
            "compose_report: removed %d native-script passage(s) not found in any "
            "source's speech: %s", sum(r["occurrences"] for r in removed),
            "; ".join(r["run"][:60] for r in removed),
        )
    return prose, removed


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


# S-1.14.17: what `_compose_checked` had to do to get finished HTML.
_COMPOSED_CLEAN = "clean"        # the first answer was finished
_COMPOSED_RETRIED = "retried"    # unfinished; the retry was finished
_COMPOSED_REPAIRED = "repaired"  # unfinished twice; the longer closed where it stopped
_COMPOSED_CLOSED = "closed"      # unfinished; the retry failed or came back empty,
                                 # so the one attempt was closed where it stopped
_CLOSED_OUTCOMES = (_COMPOSED_REPAIRED, _COMPOSED_CLOSED)


def _compose_checked(prompt: str, *, max_tokens: int, ceiling: int, label: str,
                     use_case: str = "report_compose") -> tuple[str, str]:
    """One compose call whose HTML must be finished before it is kept.

    Sections are concatenated, so a section that stops inside a tag or
    attribute value folds the next section's headings into it (S-1.14.17;
    job ``419e691d``). An unfinished answer is composed once more with twice
    the completion budget (still clamped to the model's ceiling: the likely
    cause is the budget, and a ceiling is not a charge). If that answer is
    unfinished too, the longer attempt is cut before its unfinished tag and
    its open elements are closed (``_COMPOSED_REPAIRED``); if the retry call
    fails or comes back empty, the first attempt is (``_COMPOSED_CLOSED``).
    The caller discloses either. A failure of the FIRST call propagates as
    before.

    Returns ``(html, outcome)``, ``outcome`` one of the ``_COMPOSED_*`` values.
    """
    html = _invoke_with_retry(
        use_case, prompt, max_tokens=max_tokens, temperature=0.2, label=label,
    )
    found = html_balance.check(html)
    if found.balanced:
        return html, _COMPOSED_CLEAN
    logger.warning("%s: the HTML %s; composing it once more", label, found.describe())
    retry = ""
    try:
        retry = _invoke_with_retry(
            use_case, prompt, max_tokens=min(max_tokens * 2, ceiling),
            temperature=0.2, label=f"{label} retry",
        )
    except Exception as e:  # noqa: BLE001 - the first attempt is closed and kept instead
        logger.error("%s: the retry failed (%s); closing the first attempt", label, e)
    if not retry.strip():
        # Nothing to compare: an empty retry is not a finished section, and
        # the note must not claim a second attempt that never produced text.
        logger.warning(
            "%s: no second attempt to keep (%s); closed where it stopped",
            label, found.describe(),
        )
        return html_balance.repair(html), _COMPOSED_CLOSED
    found = html_balance.check(retry)
    if found.balanced:
        return retry, _COMPOSED_RETRIED
    keep = retry if len(retry) >= len(html) else html
    logger.warning(
        "%s: still unfinished after one retry (%s); closed where it stopped",
        label, html_balance.check(keep).describe(),
    )
    return html_balance.repair(keep), _COMPOSED_REPAIRED


def _quoted_names(names: list[str]) -> str:
    return ", ".join(f"\"{html_lib.escape(name, quote=False)}\"" for name in names)


def _closed_section_disclosures(closed: list[tuple[str, str]]) -> list[str]:
    """Processing-note clauses for the sections `_compose_checked` closed.

    ``closed`` is ``(section name, outcome)`` in report order. A section cut
    off on both attempts and one whose retry failed or came back empty are
    worded apart: the second was written once, not twice.
    """
    out: list[str] = []
    twice = [name for name, outcome in closed if outcome == _COMPOSED_REPAIRED]
    once = [name for name, outcome in closed if outcome == _COMPOSED_CLOSED]
    if twice:
        names = _quoted_names(twice)
        out.append(
            f"the {names} section was cut off mid-markup on both attempts to write it and was "
            "closed where it stopped, so it may end abruptly"
            if len(twice) == 1 else
            f"{len(twice)} sections ({names}) were cut off mid-markup on both attempts "
            "to write them and were closed where they stopped, so they may end abruptly"
        )
    if once:
        names = _quoted_names(once)
        out.append(
            f"the {names} section was cut off mid-markup and could not be composed again, so it "
            "was closed where it stopped and may end abruptly"
            if len(once) == 1 else
            f"{len(once)} sections ({names}) were cut off mid-markup and could not be composed "
            "again, so they were closed where they stopped and may end abruptly"
        )
    return out


def _processing_note_html(disclosures: list[str]) -> str:
    """The report's processing-note paragraph (S-1.12.4).

    ``processing-note`` is how the reading room finds this paragraph
    (T-8.8.4.4): it sanitises ``style`` away and shows the note itself.
    """
    return (
        "\n<p class=\"processing-note\" style=\"color:#8a6d3b;border:1px solid #c9ba9b;"
        "padding:8px 12px;border-radius:4px;margin-top:24px\"><strong>Processing note:</strong> "
        + "; ".join(disclosures) + ".</p>"
    )


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
        cost = _count_tokens(json.dumps(item, ensure_ascii=False, default=str))
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
            cost = _count_tokens(json.dumps(item, ensure_ascii=False, default=str))
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
            # T-1.18.1.12: a channel job that opts into visual analysis gets
            # annotated chunks too; without the contract the model reads the
            # descriptions as speech.
            visual_annotations=VISUAL_ANNOTATION_CONTRACT,
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

    compose_prompt = CHANNEL_COMPOSE_PROMPT.format(
        statistics=json.dumps(statistics, indent=2),
        channel_summaries=json.dumps(channel_summaries, indent=2, default=str),
    )
    # S-1.14.17: the narrative is the whole body, and the template's closing
    # tags follow it, so it is checked, retried and closed like a section.
    ceiling = max_output_for(resolve_config("report_compose_channel_section").model)
    try:
        html, outcome = _compose_checked(
            compose_prompt, max_tokens=min(4_000, ceiling), ceiling=ceiling,
            label="compose_channel_report", use_case="report_compose_channel_section",
        )
    except Exception as e:
        logger.exception("Channel report composition failed")
        return {"final_html": f"<p>Channel narrative generation failed: {e}</p>"}
    closed = [("Channel narrative", outcome)] if outcome in _CLOSED_OUTCOMES else []
    disclosures = _closed_section_disclosures(closed)
    if disclosures:
        html += _processing_note_html(disclosures)
    return {
        "final_html": html,
        "processing_notes": {
            "report_sections_retried": int(outcome != _COMPOSED_CLEAN),
            "report_sections_repaired": [name for name, _ in closed],
        },
    }


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
    intermediates_out: dict | None = None,
) -> tuple[dict, str]:
    """Run the report agent. Returns ``(statistics, html_body)``.

    For channel jobs the body is the lightweight per-channel narrative; for
    topic jobs it is the full research report composed from map-reduce
    summaries.

    ``output_length`` (R4) is the user's optional depth override —
    None/'auto' lets the corpus size bracket decide. It scales the derived
    completion budget and changes the composer's brief; it is never a cap.

    ``intermediates_out`` (S-1.14.6), when given, is filled with
    ``{"map": [record, ...], "reduce": record | None}`` — what each map call
    emitted and what reduce handed to compose — for the caller to persist
    (`job_tasks._persist_report_intermediates`). Same shape as the
    ``candidates_out`` hook on the search agent. Channel jobs have no
    map/reduce stage and produce none. When the S-1.18.9 attribution guard
    changed the prose, ``"attribution_guard"`` lists each change.
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
        "map_batch_records": [],
        "reduce_record": {},
    })
    if intermediates_out is not None:
        intermediates_out["map"] = list(result.get("map_batch_records") or [])
        intermediates_out["reduce"] = result.get("reduce_record") or None
        # S-1.18.9: every place the attribution guard changed the prose, when it did.
        rewrites = (result.get("processing_notes") or {}).get("report_attribution_rewrites")
        if rewrites:
            intermediates_out["attribution_guard"] = list(rewrites)
    return result.get("statistics", {}), result.get("final_html", "")

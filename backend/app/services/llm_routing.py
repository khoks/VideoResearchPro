"""LLM use-case registry: single source of truth for fast/primary routing.

Every LLM call site in this codebase has a named ``UseCase`` entry here. The
``default_route`` column decides whether the call hits the *primary* model
(OpenAI GPT / Anthropic Claude / Google Gemini — set by
``LLM_PRIMARY_PROVIDER``) or the *fast* model (typically a local
OpenAI-compatible server like LM Studio — set by ``LLM_FAST_BASE_URL``).

Flipping a single use case at runtime
-------------------------------------
Set the ``LLM_ROUTE_OVERRIDES`` env var to a comma-separated list of
``use_case=route`` pairs. Examples::

    # Keep the heavy report-compose step on the primary model even if you
    # later mark it as a "fast" default here.
    LLM_ROUTE_OVERRIDES=report_compose=primary

    # Experiment with routing the knowledge map phase to the local model.
    LLM_ROUTE_OVERRIDES=knowledge_extract_batch=fast,qa_history_refine_context=fast

Unknown use-case names are logged and ignored — they never raise.

Picking a default route for a new call site
-------------------------------------------
Think about three things:

1. **Input token pressure.** If ``p95_input_tokens`` exceeds the context
   window of the local model you run in LM Studio, *do not* default to fast.
   A 4096-token Gemma instance will silently truncate a 45k-token refine
   context call and return garbage.
2. **Output quality bar.** Final-answer composition, citation-bearing
   synthesis, and ranking decisions need the best reasoning available. Use
   ``primary``.
3. **Volume × cost.** Map-reduce loops (report_map_chunks,
   knowledge_extract_batch) fire dozens of calls per job. Even if each call
   could run on the primary model, routing to fast saves serious money
   without hurting the end user's experience.

Why the registry, not ``purpose=`` at each call site?
-----------------------------------------------------
Previously every call site had a hard-coded ``purpose="fast"`` or
``purpose="primary"``. Flipping one decision meant a code change + deploy.
With the registry:

  * All 19 decisions are listed in one place; easy to audit.
  * Each decision carries its rationale + token budget so you understand
    what you're flipping.
  * A single env var flips any decision at runtime for A/B tests.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

Route = Literal["primary", "fast"]

# Named use cases — one per LLM call site. Adding a new LLM call site?
# Add a literal here AND a USE_CASE_REGISTRY entry below.
UseCase = Literal[
    # Job Q&A pipeline (app/agents/qa_agent.py, app/routers/qa.py)
    "qa_clarification",
    "qa_sub_query_expansion",
    "qa_refine_context",
    "qa_formulate_answer",
    "qa_extract_references",
    # Library-wide Q&A (app/agents/qa_agent.py library path, app/routers/library.py)
    "library_qa_clarification",
    "library_qa_refine_context",
    "library_qa_formulate_answer",
    # Q&A History ("Personal Wiki" meta-chat) — app/agents/qa_history_agent.py
    "qa_history_refine_context",
    "qa_history_formulate_answer",
    # Per-video Knowledge extraction — app/agents/knowledge_agent.py
    "knowledge_extract_batch",
    "knowledge_synthesize_report",
    # Topic search — app/agents/search_agent.py
    "search_plan_queries",
    "search_rank_and_curate",
    # Report generation (map-reduce) — app/agents/report_agent.py
    "report_map_chunks",
    "report_reduce_summaries",
    "report_compose",
    "report_channel",
    "report_compose_channel_section",
]


@dataclass(frozen=True)
class UseCaseInfo:
    """Metadata and default routing for one LLM call site.

    Attributes:
        default_route: Where this call goes when there's no env override.
        summary: One-line plain-English description of what the LLM is asked
            to do here.
        typical_input_tokens: Median input size we observe in production.
        p95_input_tokens: 95th-percentile input size. This is the number you
            care about when sizing a local model's context window — if your
            local model can't hold this, route to primary.
        typical_output_tokens: Median output size.
        min_context_recommended: Minimum local-model context window (in
            tokens) that can run this call comfortably. Pick your local
            model's ``n_ctx`` to cover the max of this field across every
            use case you want to route to fast.
        rationale: Why this default was chosen. Explains the trade-off so a
            future editor understands what they're changing.
    """

    default_route: Route
    summary: str
    typical_input_tokens: int
    p95_input_tokens: int
    typical_output_tokens: int
    min_context_recommended: int
    rationale: str


# ---------------------------------------------------------------------------
# Registry. One entry per UseCase literal above.
# ---------------------------------------------------------------------------
#
# Token estimates are from production observation + tiktoken measurements on
# representative inputs (2026-04). They are order-of-magnitude correct, not
# precise — use them as sizing hints, not SLAs.
USE_CASE_REGISTRY: dict[UseCase, UseCaseInfo] = {
    # --- Job Q&A --------------------------------------------------------
    "qa_clarification": UseCaseInfo(
        default_route="fast",
        summary=(
            "Generate a short clarifying follow-up question after the user "
            "asks about a job's videos (e.g. 'Did you mean the pricing "
            "changes in 2023 or 2024?')."
        ),
        typical_input_tokens=400,
        p95_input_tokens=900,
        typical_output_tokens=200,
        min_context_recommended=2048,
        rationale=(
            "Tiny prompt, tiny output, pattern-matching task. Safe on any "
            "local instruct model down to 2k context."
        ),
    ),
    "qa_sub_query_expansion": UseCaseInfo(
        default_route="fast",
        summary=(
            "Rephrase the user's question into 2 semantically-focused "
            "sub-queries to broaden RAG retrieval coverage."
        ),
        typical_input_tokens=300,
        p95_input_tokens=600,
        typical_output_tokens=150,
        min_context_recommended=2048,
        rationale=(
            "Very short in, very short out. Local model quality barely "
            "matters — we just need semantic rewording."
        ),
    ),
    "qa_refine_context": UseCaseInfo(
        default_route="fast",
        summary=(
            "Compact the raw RAG hits + report context down to a focused "
            "excerpt that the final-answer LLM can reason over. Input is "
            "large (top-K transcript chunks + relevant report sections)."
        ),
        typical_input_tokens=8_000,
        p95_input_tokens=45_000,
        typical_output_tokens=2_000,
        min_context_recommended=65_536,
        rationale=(
            "Map-reduce 'map' style: the whole point is to thin a huge "
            "context down. Fast-route saves OpenAI tokens. BUT: if your "
            "local model has a <32k context, this will truncate and the "
            "downstream final answer will be wrong — override to primary "
            "until you load a larger-context model."
        ),
    ),
    "qa_formulate_answer": UseCaseInfo(
        default_route="primary",
        summary=(
            "Produce the final user-facing answer with citations. Runs at "
            "temperature 0 so citations remain deterministic."
        ),
        typical_input_tokens=5_000,
        p95_input_tokens=15_000,
        typical_output_tokens=3_000,
        min_context_recommended=32_768,
        rationale=(
            "End of the pipeline; the user judges the whole system on this "
            "output. Keep on the best model available."
        ),
    ),
    "qa_extract_references": UseCaseInfo(
        default_route="primary",
        summary=(
            "Parse the answer back into a structured reference list "
            "(video_id, timestamp, quote). Must be accurate."
        ),
        typical_input_tokens=3_000,
        p95_input_tokens=8_000,
        typical_output_tokens=1_000,
        min_context_recommended=16_384,
        rationale=(
            "Structured extraction — a local 13B model will sometimes "
            "hallucinate a video_id that wasn't in the answer. Keep "
            "primary until you've validated a specific local model."
        ),
    ),
    # --- Library-wide Q&A ----------------------------------------------
    "library_qa_clarification": UseCaseInfo(
        default_route="fast",
        summary=(
            "Same as qa_clarification, but for questions asked across the "
            "whole video library instead of a single job."
        ),
        typical_input_tokens=400,
        p95_input_tokens=900,
        typical_output_tokens=200,
        min_context_recommended=2048,
        rationale="Same characteristics as qa_clarification.",
    ),
    "library_qa_refine_context": UseCaseInfo(
        default_route="fast",
        summary=(
            "Compact the library-wide RAG hits into focused context before "
            "the final answer. Input can be very large."
        ),
        typical_input_tokens=8_000,
        p95_input_tokens=45_000,
        typical_output_tokens=2_000,
        min_context_recommended=65_536,
        rationale=(
            "Same reasoning as qa_refine_context. Override to primary if "
            "your local model context is too small."
        ),
    ),
    "library_qa_formulate_answer": UseCaseInfo(
        default_route="primary",
        summary="Final library-wide answer with citations across videos.",
        typical_input_tokens=5_000,
        p95_input_tokens=15_000,
        typical_output_tokens=3_000,
        min_context_recommended=32_768,
        rationale="End-of-pipeline output; keep on the best model.",
    ),
    # --- Q&A History (Personal Wiki meta-chat) -------------------------
    "qa_history_refine_context": UseCaseInfo(
        default_route="primary",
        summary=(
            "Compact a handful of retrieved past Q&A exchanges into focused "
            "context before the history-chat final answer."
        ),
        typical_input_tokens=2_000,
        p95_input_tokens=8_000,
        typical_output_tokens=1_000,
        min_context_recommended=16_384,
        rationale=(
            "Candidate for fast once a local model with ≥16k context is "
            "loaded. Currently on primary because the user's reported "
            "local model (gemma-4-26b-a4b) was loaded with 4096 context — "
            "override to fast after reloading with 16k+."
        ),
    ),
    "qa_history_formulate_answer": UseCaseInfo(
        default_route="primary",
        summary=(
            "Synthesize a meta-answer across the user's past exchanges and "
            "cite which exchange IDs it drew from."
        ),
        typical_input_tokens=2_000,
        p95_input_tokens=6_000,
        typical_output_tokens=2_000,
        min_context_recommended=16_384,
        rationale=(
            "User-facing synthesis; citations must be grounded. Keep on "
            "the best model available."
        ),
    ),
    # --- Per-video Knowledge extraction --------------------------------
    "knowledge_extract_batch": UseCaseInfo(
        default_route="primary",
        summary=(
            "Map phase of the knowledge agent: extract structured "
            "{topics, concepts, events, facts} JSON from a batch of "
            "transcript chunks (up to KNOWLEDGE_EXTRACT_BATCH_TOKENS)."
        ),
        typical_input_tokens=6_000,
        p95_input_tokens=10_000,
        typical_output_tokens=2_000,
        min_context_recommended=16_384,
        rationale=(
            "Strong candidate for fast routing — it's a map-phase batch "
            "over many chunks per video. Currently primary because the "
            "output is structured JSON and small local models are flaky at "
            "JSON grammar. Flip to fast once you've confirmed your local "
            "model reliably emits valid JSON for the extraction schema."
        ),
    ),
    "knowledge_synthesize_report": UseCaseInfo(
        default_route="primary",
        summary=(
            "Reduce phase of the knowledge agent: compose a Markdown "
            "knowledge report from the deduped {topics, concepts, events, "
            "facts} structure."
        ),
        typical_input_tokens=3_000,
        p95_input_tokens=6_000,
        typical_output_tokens=6_000,
        min_context_recommended=16_384,
        rationale=(
            "Long user-facing output (Wikipedia-paragraph style). Keep "
            "primary."
        ),
    ),
    # --- Topic search --------------------------------------------------
    "search_plan_queries": UseCaseInfo(
        default_route="fast",
        summary=(
            "Plan 3-5 YouTube search queries from a user's topic + "
            "instructions prompt."
        ),
        typical_input_tokens=500,
        p95_input_tokens=1_000,
        typical_output_tokens=400,
        min_context_recommended=2048,
        rationale="Tiny, pattern-matching. Safe on any local model.",
    ),
    "search_rank_and_curate": UseCaseInfo(
        default_route="primary",
        summary=(
            "Rank YouTube search results and curate a final video list. "
            "Requires judgment about relevance, authority, and dedup."
        ),
        typical_input_tokens=4_000,
        p95_input_tokens=12_000,
        typical_output_tokens=2_000,
        min_context_recommended=16_384,
        rationale=(
            "Reasoning-heavy. A 7-13B local model will rank poorly. Keep "
            "primary."
        ),
    ),
    # --- Report generation (map-reduce over transcripts) ---------------
    "report_map_chunks": UseCaseInfo(
        default_route="fast",
        summary=(
            "Map phase: extract key facts from each batch of transcript "
            "chunks. Batches are token-budgeted up to LLM_MAX_CONTEXT_TOKENS."
        ),
        typical_input_tokens=4_000,
        p95_input_tokens=32_000,
        typical_output_tokens=2_000,
        min_context_recommended=32_768,
        rationale=(
            "Highest-volume LLM call in the codebase — dozens per job. "
            "Routing to fast is where most OpenAI spend is saved. Context "
            "can be large though; load your local model with ≥32k context."
        ),
    ),
    "report_reduce_summaries": UseCaseInfo(
        default_route="fast",
        summary=(
            "Reduce phase: consolidate the per-batch summaries into a "
            "single structured summary."
        ),
        typical_input_tokens=6_000,
        p95_input_tokens=20_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale=(
            "Batches the map outputs together. Similar context pressure "
            "to report_map_chunks; same sizing advice."
        ),
    ),
    "report_compose": UseCaseInfo(
        default_route="primary",
        summary=(
            "Compose the final HTML report from the reduced summary + "
            "statistics. Produces thousands of tokens of user-facing text."
        ),
        typical_input_tokens=10_000,
        p95_input_tokens=30_000,
        typical_output_tokens=16_000,
        min_context_recommended=131_072,
        rationale=(
            "Long, polished output that the user reads top-to-bottom. "
            "Keep on the primary model."
        ),
    ),
    "report_channel": UseCaseInfo(
        default_route="primary",
        summary="Channel-level report composition for channel jobs.",
        typical_input_tokens=6_000,
        p95_input_tokens=15_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale="Same reasoning as report_compose.",
    ),
    "report_compose_channel_section": UseCaseInfo(
        default_route="primary",
        summary="Per-channel section composer inside channel-report pipeline.",
        typical_input_tokens=6_000,
        p95_input_tokens=15_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale="Same reasoning as report_compose.",
    ),
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
_VALID_ROUTES: tuple[str, ...] = ("primary", "fast")


def _parse_overrides(raw: str) -> dict[str, Route]:
    """Parse ``LLM_ROUTE_OVERRIDES`` into a ``{use_case: route}`` dict.

    Format: comma-separated ``use_case=route`` pairs. Whitespace tolerated.
    Invalid entries log a warning and are ignored — the point of this
    mechanism is operator convenience, so we never crash the app because
    of a typo in an env var.
    """
    if not raw:
        return {}
    out: dict[str, Route] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            logger.warning(
                "LLM_ROUTE_OVERRIDES: skipping malformed entry %r "
                "(expected 'use_case=route')",
                item,
            )
            continue
        key, _, val = item.partition("=")
        key = key.strip()
        val = val.strip().lower()
        if key not in USE_CASE_REGISTRY:
            logger.warning(
                "LLM_ROUTE_OVERRIDES: unknown use_case %r; ignoring. "
                "Known names: %s",
                key, ", ".join(sorted(USE_CASE_REGISTRY.keys())),
            )
            continue
        if val not in _VALID_ROUTES:
            logger.warning(
                "LLM_ROUTE_OVERRIDES: invalid route %r for use_case %r; "
                "must be one of %s",
                val, key, _VALID_ROUTES,
            )
            continue
        out[key] = val  # type: ignore[assignment]
    return out


def resolve_route(use_case: UseCase) -> Route:
    """Return the current route (``"primary"`` | ``"fast"``) for ``use_case``.

    Checks ``LLM_ROUTE_OVERRIDES`` first; falls back to the registry's
    ``default_route``. Raises ``KeyError`` if ``use_case`` is not a known
    literal — that's a programming error worth catching loudly at test time.
    """
    if use_case not in USE_CASE_REGISTRY:
        raise KeyError(
            f"Unknown LLM use_case {use_case!r}. Add it to "
            f"app/services/llm_routing.USE_CASE_REGISTRY and to the "
            f"UseCase literal."
        )
    overrides = _parse_overrides(getattr(settings, "LLM_ROUTE_OVERRIDES", "") or "")
    if use_case in overrides:
        return overrides[use_case]
    return USE_CASE_REGISTRY[use_case].default_route


def describe_registry() -> str:
    """Return a human-readable dump of the full registry.

    Useful from a debug endpoint or a REPL when you're about to edit
    ``LLM_ROUTE_OVERRIDES`` and want to see the options.
    """
    lines: list[str] = ["LLM use-case registry:"]
    for name in USE_CASE_REGISTRY:
        info = USE_CASE_REGISTRY[name]
        current = resolve_route(name)
        marker = "" if current == info.default_route else f" [overridden: {current}]"
        lines.append(
            f"  - {name} → {info.default_route}{marker}\n"
            f"      summary: {info.summary}\n"
            f"      input  p50={info.typical_input_tokens:>6}  p95={info.p95_input_tokens:>6}  "
            f"output p50={info.typical_output_tokens:>5}\n"
            f"      min local context: {info.min_context_recommended:>6} tokens\n"
            f"      why: {info.rationale}"
        )
    return "\n".join(lines)

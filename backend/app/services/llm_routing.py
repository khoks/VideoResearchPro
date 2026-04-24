"""LLM use-case registry: single source of truth for per-call-site LLM config.

Every LLM call site in this codebase has a named ``UseCase`` entry here.
Each entry carries a ``default_config`` describing which provider, which
model, and which reasoning level to use — the defaults that production
runs with when no env override is set.

Three concepts you need:

* **UseCase** — a named call site (e.g. ``qa_formulate_answer``). The
  literal is the contract between code and config.
* **UseCaseConfig** — a (provider, model, reasoning) triple. This is the
  actionable instruction the LLM service consumes to build a chat client.
* **UseCaseInfo** — the registry entry carrying ``default_config`` plus
  metadata (token budgets, rationale) so a human reading this file
  understands why each decision was made.

Flipping a single use case at runtime — two mechanisms
-------------------------------------------------------

**Preferred: ``LLM_USE_CASE_CONFIG``** (provider + model + reasoning per
call site). Comma-separated ``use_case=provider:model[:reasoning]``::

    LLM_USE_CASE_CONFIG=qa_formulate_answer=openai:gpt-5.4:high,qa_clarification=local:qwen/qwen3.5-9b:off

**Legacy: ``LLM_ROUTE_OVERRIDES``** (binary primary/fast). Still honored
for back-compat. When a use case is listed here *and not* in
``LLM_USE_CASE_CONFIG``, the route flips the *provider* of the default
config between its primary-provider setting (``openai`` by default for
use cases we ship) and ``local``. Intended transition: new deployments
should move to ``LLM_USE_CASE_CONFIG``.

Unknown use-case names, providers, or reasoning levels are logged and
ignored — never raise. The whole point of this mechanism is operator
convenience, so a typo in an env var does not take down the app.

Picking a default for a new call site
-------------------------------------

Think about four things:

1. **Output quality bar.** Final-answer composition, citation-bearing
   synthesis, and ranking decisions need the best model + medium/high
   reasoning. Put these on flagship (``gpt-5.4`` / Opus / 2.5 Pro).
2. **Input token pressure.** Context-compression calls (refine) often hit
   p95 inputs of 30-45k tokens. Whatever model you pick must have a
   context window that holds ``p95_input_tokens`` comfortably.
3. **Volume × cost.** Map-reduce loops (``report_map_chunks``,
   ``knowledge_extract_batch``) fire dozens of calls per job. Keep these
   on the economy model with reasoning off; the cost multiplier is
   brutal otherwise.
4. **Reasoning fit.** Reasoning HELPS for ranking, final-answer
   grounding, and ambiguity resolution. Reasoning HURTS for
   pattern-match rephrasing, structured-JSON extraction (often violates
   schema during internal thinking), and high-volume calls (thinking
   tokens dominate cost).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Route = Literal["primary", "fast"]
Provider = Literal["openai", "anthropic", "google", "local"]
ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "auto"]

_VALID_ROUTES: tuple[str, ...] = ("primary", "fast")
_VALID_PROVIDERS: tuple[str, ...] = ("openai", "anthropic", "google", "local")
_VALID_REASONING: tuple[str, ...] = ("off", "minimal", "low", "medium", "high", "auto")


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
class UseCaseConfig:
    """Actionable instruction the LLM service consumes.

    Attributes:
        provider: Which chat backend to build. ``local`` routes to the
            OpenAI-compatible endpoint configured by ``LLM_LOCAL_BASE_URL``
            (or legacy ``LLM_FAST_BASE_URL``). ``openai`` / ``anthropic``
            / ``google`` route to the corresponding SaaS endpoint.
        model: Provider-specific model identifier. For local this is
            whatever LM Studio / Ollama / vLLM reports (can be anything
            non-empty).
        reasoning: Effort level, normalized across providers:
            * ``off`` — no reasoning budget
            * ``minimal`` / ``low`` / ``medium`` / ``high`` — escalating
              effort (mapped to ``reasoning_effort`` on OpenAI,
              ``thinking.budget_tokens`` on Anthropic,
              ``thinkingBudget`` on Google)
            * ``auto`` — let the provider decide (Google's
              ``thinkingBudget=-1``; falls back to ``medium`` on providers
              without adaptive modes)
    """

    provider: Provider
    model: str
    reasoning: ReasoningLevel = "off"

    def as_label(self) -> str:
        """Short string for logs: ``openai:gpt-5.4:medium``."""
        return f"{self.provider}:{self.model}:{self.reasoning}"


@dataclass(frozen=True)
class UseCaseInfo:
    """Registry entry: default config + sizing metadata + rationale.

    The ``default_route`` field is kept for back-compat introspection and
    for the legacy ``LLM_ROUTE_OVERRIDES`` knob. New code reads
    ``default_config`` instead.
    """

    default_route: Route
    default_config: UseCaseConfig
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
# Defaults below target OpenAI (the codebase's historical default provider)
# with model tiers chosen per use case. Flip an individual call to Claude
# or Gemini via LLM_USE_CASE_CONFIG without editing this file:
#
#   LLM_USE_CASE_CONFIG=knowledge_synthesize_report=anthropic:claude-opus-4-5:medium
#
# Token estimates are from production observation + tiktoken measurements
# on representative inputs (2026-04). Order-of-magnitude correct, not
# precise — use them as sizing hints, not SLAs.
USE_CASE_REGISTRY: dict[UseCase, UseCaseInfo] = {
    # --- Job Q&A --------------------------------------------------------
    "qa_clarification": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
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
            "Tiny prompt, tiny output, pattern-matching task. gpt-5.4-mini "
            "with reasoning off is cheap and fast. Safe to route to local "
            "(any instruct model ≥7B handles this cleanly)."
        ),
    ),
    "qa_sub_query_expansion": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
        summary=(
            "Rephrase the user's question into 2 semantically-focused "
            "sub-queries to broaden RAG retrieval coverage."
        ),
        typical_input_tokens=300,
        p95_input_tokens=600,
        typical_output_tokens=150,
        min_context_recommended=2048,
        rationale=(
            "Short in, short out. gpt-5.4-mini is more than sufficient. "
            "Candidate for local routing if retrieval recall is acceptable."
        ),
    ),
    "qa_refine_context": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4", "low"),
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
            "Feeds the final answer — compression quality matters. Flagship "
            "model with low reasoning keeps coherence over long input "
            "without burning excessive thinking tokens."
        ),
    ),
    "qa_formulate_answer": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "medium"),
        summary=(
            "Produce the final user-facing answer with citations. Runs at "
            "temperature 0 so citations remain deterministic."
        ),
        typical_input_tokens=5_000,
        p95_input_tokens=15_000,
        typical_output_tokens=3_000,
        min_context_recommended=32_768,
        rationale=(
            "User judges the system on this output. Flagship + medium "
            "reasoning reduces citation hallucinations."
        ),
    ),
    "qa_extract_references": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
        summary=(
            "Parse the answer back into a structured reference list "
            "(video_id, timestamp, quote). Must be accurate."
        ),
        typical_input_tokens=3_000,
        p95_input_tokens=8_000,
        typical_output_tokens=1_000,
        min_context_recommended=16_384,
        rationale=(
            "Structured extraction — reasoning OFF is deliberate because "
            "reasoning models often violate schema during internal "
            "thinking. gpt-5.4-mini + strict schema is more reliable."
        ),
    ),
    # --- Library-wide Q&A ----------------------------------------------
    "library_qa_clarification": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
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
        default_config=UseCaseConfig("openai", "gpt-5.4", "low"),
        summary=(
            "Compact the library-wide RAG hits into focused context before "
            "the final answer. Input can be very large."
        ),
        typical_input_tokens=8_000,
        p95_input_tokens=45_000,
        typical_output_tokens=2_000,
        min_context_recommended=65_536,
        rationale="Same reasoning as qa_refine_context.",
    ),
    "library_qa_formulate_answer": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "medium"),
        summary="Final library-wide answer with citations across videos.",
        typical_input_tokens=5_000,
        p95_input_tokens=15_000,
        typical_output_tokens=3_000,
        min_context_recommended=32_768,
        rationale="End-of-pipeline output; flagship + medium reasoning.",
    ),
    # --- Q&A History (Personal Wiki meta-chat) -------------------------
    "qa_history_refine_context": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "low"),
        summary=(
            "Compact a handful of retrieved past Q&A exchanges into focused "
            "context before the history-chat final answer."
        ),
        typical_input_tokens=2_000,
        p95_input_tokens=8_000,
        typical_output_tokens=1_000,
        min_context_recommended=16_384,
        rationale=(
            "Smaller input than qa_refine_context — gpt-5.4-mini + low "
            "reasoning is sufficient. Flip to local if you want to cut "
            "per-turn latency."
        ),
    ),
    "qa_history_formulate_answer": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "medium"),
        summary=(
            "Synthesize a meta-answer across the user's past exchanges and "
            "cite which exchange IDs it drew from."
        ),
        typical_input_tokens=2_000,
        p95_input_tokens=6_000,
        typical_output_tokens=2_000,
        min_context_recommended=16_384,
        rationale=(
            "User-facing synthesis; citations must be grounded. Flagship "
            "+ medium reasoning."
        ),
    ),
    # --- Per-video Knowledge extraction --------------------------------
    "knowledge_extract_batch": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
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
            "High-volume (dozens per video) structured JSON extraction. "
            "Reasoning OFF + strict schema — reasoning mode often violates "
            "schema during internal thinking."
        ),
    ),
    "knowledge_synthesize_report": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "medium"),
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
            "Long user-facing output (Wikipedia-paragraph style). "
            "Flagship + medium reasoning. Consider anthropic:claude-opus-4-5 "
            "for higher prose quality."
        ),
    ),
    # --- Topic search --------------------------------------------------
    "search_plan_queries": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "low"),
        summary=(
            "Plan 3-5 YouTube search queries from a user's topic + "
            "instructions prompt."
        ),
        typical_input_tokens=500,
        p95_input_tokens=1_000,
        typical_output_tokens=400,
        min_context_recommended=2048,
        rationale=(
            "One-shot per job — low volume, high leverage (drives every "
            "downstream search result). Low reasoning helps produce "
            "diverse, complementary queries."
        ),
    ),
    "search_rank_and_curate": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "high"),
        summary=(
            "Rank YouTube search results and curate a final video list. "
            "Requires judgment about relevance, authority, and dedup."
        ),
        typical_input_tokens=4_000,
        p95_input_tokens=12_000,
        typical_output_tokens=2_000,
        min_context_recommended=16_384,
        rationale=(
            "This is the single biggest reasoning-mode win in the app. "
            "Explicit step-by-step scoring + dedup is exactly what "
            "reasoning was built for."
        ),
    ),
    # --- Report generation (map-reduce over transcripts) ---------------
    "report_map_chunks": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
        summary=(
            "Map phase: extract key facts from each batch of transcript "
            "chunks. Batches are token-budgeted up to LLM_MAX_CONTEXT_TOKENS."
        ),
        typical_input_tokens=4_000,
        p95_input_tokens=32_000,
        typical_output_tokens=2_000,
        min_context_recommended=32_768,
        rationale=(
            "Highest-volume LLM call in the codebase (dozens per job). "
            "Reasoning OFF is mandatory at this volume — thinking tokens "
            "dominate cost otherwise. Good candidate for local routing."
        ),
    ),
    "report_reduce_summaries": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "low"),
        summary=(
            "Reduce phase: consolidate the per-batch summaries into a "
            "single structured summary."
        ),
        typical_input_tokens=6_000,
        p95_input_tokens=20_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale=(
            "Consolidation benefits from a little planning. Low reasoning "
            "on the economy model is the right trade-off."
        ),
    ),
    "report_compose": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "medium"),
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
            "Flagship + medium reasoning."
        ),
    ),
    "report_channel": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "medium"),
        summary="Channel-level report composition for channel jobs.",
        typical_input_tokens=6_000,
        p95_input_tokens=15_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale="Same reasoning as report_compose.",
    ),
    "report_compose_channel_section": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4", "low"),
        summary="Per-channel section composer inside channel-report pipeline.",
        typical_input_tokens=6_000,
        p95_input_tokens=15_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale=(
            "Section-level composition (multiple per job). Flagship + low "
            "reasoning keeps quality up without burning tokens at high "
            "volume."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Resolution — config (preferred) and route (legacy)
# ---------------------------------------------------------------------------


def _parse_use_case_config(raw: str) -> dict[str, UseCaseConfig]:
    """Parse ``LLM_USE_CASE_CONFIG`` into a ``{use_case: UseCaseConfig}`` dict.

    Format: comma-separated ``use_case=provider:model[:reasoning]``.
    Whitespace tolerated. Invalid entries log a warning and are ignored.
    """
    if not raw:
        return {}
    out: dict[str, UseCaseConfig] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            logger.warning(
                "LLM_USE_CASE_CONFIG: skipping malformed entry %r "
                "(expected 'use_case=provider:model[:reasoning]')",
                item,
            )
            continue
        use_case, _, spec = item.partition("=")
        use_case = use_case.strip()
        spec = spec.strip()
        if use_case not in USE_CASE_REGISTRY:
            logger.warning(
                "LLM_USE_CASE_CONFIG: unknown use_case %r; ignoring. "
                "Known names: %s",
                use_case,
                ", ".join(sorted(USE_CASE_REGISTRY.keys())),
            )
            continue
        parts = spec.split(":")
        if len(parts) < 2 or len(parts) > 3:
            logger.warning(
                "LLM_USE_CASE_CONFIG: skipping %r — spec must be "
                "'provider:model' or 'provider:model:reasoning'",
                item,
            )
            continue
        provider_raw = parts[0].strip().lower()
        model = parts[1].strip()
        reasoning_raw = parts[2].strip().lower() if len(parts) == 3 else "off"
        if provider_raw not in _VALID_PROVIDERS:
            logger.warning(
                "LLM_USE_CASE_CONFIG: unknown provider %r for %r; must be "
                "one of %s. Ignoring.",
                provider_raw, use_case, _VALID_PROVIDERS,
            )
            continue
        if not model:
            logger.warning(
                "LLM_USE_CASE_CONFIG: empty model for %r; ignoring.",
                use_case,
            )
            continue
        if reasoning_raw not in _VALID_REASONING:
            logger.warning(
                "LLM_USE_CASE_CONFIG: unknown reasoning %r for %r; must be "
                "one of %s. Defaulting to 'off'.",
                reasoning_raw, use_case, _VALID_REASONING,
            )
            reasoning_raw = "off"
        out[use_case] = UseCaseConfig(
            provider=provider_raw,  # type: ignore[arg-type]
            model=model,
            reasoning=reasoning_raw,  # type: ignore[arg-type]
        )
    return out


def _parse_route_overrides(raw: str) -> dict[str, Route]:
    """Legacy ``LLM_ROUTE_OVERRIDES`` parser (binary primary/fast).

    Kept for back-compat. Unknown entries log and are ignored.
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
                "LLM_ROUTE_OVERRIDES: unknown use_case %r; ignoring.",
                key,
            )
            continue
        if val not in _VALID_ROUTES:
            logger.warning(
                "LLM_ROUTE_OVERRIDES: invalid route %r for %r; must be "
                "one of %s",
                val, key, _VALID_ROUTES,
            )
            continue
        out[key] = val  # type: ignore[assignment]
    return out


def _local_substitute(default: UseCaseConfig) -> UseCaseConfig:
    """Legacy ``route=fast`` → ``local`` provider with local model name.

    Reads ``LLM_FAST_MODEL`` (or falls back to the default's model) so
    that older setups which only set ``LLM_ROUTE_OVERRIDES`` still route
    to the local endpoint as intended.
    """
    local_model = getattr(settings, "LLM_FAST_MODEL", None) or default.model
    return UseCaseConfig(provider="local", model=local_model, reasoning="off")


def resolve_config(use_case: UseCase) -> UseCaseConfig:
    """Return the effective ``UseCaseConfig`` for ``use_case``.

    Precedence (highest first):

    1. ``LLM_USE_CASE_CONFIG`` — inline per-use-case provider/model/reasoning
    2. ``LLM_ROUTE_OVERRIDES`` legacy — flips provider to ``local`` when
       route=fast, or keeps the default when route=primary
    3. Registry ``default_config``

    Raises ``KeyError`` for unknown use cases (programmer error).
    """
    if use_case not in USE_CASE_REGISTRY:
        raise KeyError(
            f"Unknown LLM use_case {use_case!r}. Add it to "
            f"app/services/llm_routing.USE_CASE_REGISTRY and to the "
            f"UseCase literal."
        )
    info = USE_CASE_REGISTRY[use_case]

    inline = _parse_use_case_config(
        getattr(settings, "LLM_USE_CASE_CONFIG", "") or ""
    )
    if use_case in inline:
        return inline[use_case]

    legacy = _parse_route_overrides(
        getattr(settings, "LLM_ROUTE_OVERRIDES", "") or ""
    )
    if use_case in legacy:
        if legacy[use_case] == "fast":
            return _local_substitute(info.default_config)
        # route=primary → keep the registry default
        return info.default_config

    return info.default_config


def resolve_route(use_case: UseCase) -> Route:
    """Back-compat: return ``"primary"`` or ``"fast"`` for ``use_case``.

    Preserved for external callers still thinking in binary terms. New
    code should call ``resolve_config`` directly.
    """
    cfg = resolve_config(use_case)
    return "fast" if cfg.provider == "local" else "primary"


def describe_registry() -> str:
    """Human-readable dump of the registry + effective resolved config."""
    lines: list[str] = ["LLM use-case registry:"]
    for name in USE_CASE_REGISTRY:
        info = USE_CASE_REGISTRY[name]
        effective = resolve_config(name)
        marker = (
            ""
            if effective == info.default_config
            else f" [overridden: {effective.as_label()}]"
        )
        lines.append(
            f"  - {name} → {info.default_config.as_label()}{marker}\n"
            f"      summary: {info.summary}\n"
            f"      input  p50={info.typical_input_tokens:>6}  "
            f"p95={info.p95_input_tokens:>6}  "
            f"output p50={info.typical_output_tokens:>5}\n"
            f"      min local context: {info.min_context_recommended:>6} tokens\n"
            f"      why: {info.rationale}"
        )
    return "\n".join(lines)

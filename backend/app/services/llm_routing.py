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

    LLM_USE_CASE_CONFIG=qa_formulate_answer=openai:gpt-5.5:high,qa_clarification=local:qwen/qwen3.5-9b:off

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
   reasoning. Put these on flagship (``gpt-5.5`` / Opus / 2.5 Pro).
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
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

# E-1.13: per-user overrides for the current request/Celery task. Populated
# by ``llm_service.byok_context`` (which already brackets every user-scoped
# LLM entry point per D-041); maps use_case -> UseCaseConfig.
user_override_context: ContextVar[dict | None] = ContextVar(
    "user_llm_overrides", default=None
)

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
    # Social-media candidate classification (S-1.5.3) — D-007 / D-014 / D-021
    "social_classify_stance",
    # Report generation (map-reduce) — app/agents/report_agent.py
    "report_map_chunks",
    "report_reduce_summaries",
    "report_compose",
    "report_channel",
    "report_compose_channel_section",
    # Visual understanding (R1) — app/agents/visual_agent.py
    "visual_select_moments",
    "visual_describe_frame",
    # Discussed-era extraction (R3 / S-1.17.2) — app/services/temporal_service.py
    "temporal_scope_extract",
    # Code-mixed speech (R5 / S-1.16.2) — app/services/code_mixing_service.py
    "code_mixing_detect",
    "code_mixing_render_english",
]

# Use cases whose prompts carry IMAGES, not just text.
#
# This matters for two things that would otherwise fail silently:
#
# 1. **Model choice is not freely swappable.** Every other entry in the
#    registry can be pointed at any model of any provider. A vision entry
#    cannot — a text-only model does not error helpfully on an image part,
#    it either 400s with a schema complaint or, worse, ignores the image
#    and confabulates a description from the surrounding text. That failure
#    reads as a working feature producing bad output.
# 2. **The startup smoke check would lie.** `llm_smoke.probe_config` sends a
#    text-only probe. A vision use case misconfigured onto a text model
#    would probe green and fail on the first real call.
VISION_USE_CASES: frozenset[str] = frozenset({"visual_describe_frame"})

# Models known to accept image inputs. Used to WARN on a misconfiguration,
# never to block one — same fail-soft rule as the rest of this module
# (D-067): an operator pointing a vision use case at an unlisted model gets
# a loud log line, not a dead app, because this list will always lag new
# model releases.
VISION_CAPABLE_MODELS: frozenset[str] = frozenset({
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.5", "gpt-5.5-pro",
    "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
    "gpt-4.1", "gpt-4.1-mini",
    "claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5",
    "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite", "gemini-3.1-pro-preview",
    "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
})


def is_vision_use_case(use_case: str) -> bool:
    """True when this call site sends images and needs a vision model."""
    return use_case in VISION_USE_CASES


def vision_choice_unverified(use_case: str, cfg: "UseCaseConfig") -> bool:
    """True when a vision use case resolves to a non-local model that is not
    on ``VISION_CAPABLE_MODELS``. Shared by the startup log line and the
    settings-page warning (``assess_choice``)."""
    return (
        is_vision_use_case(use_case)
        and cfg.provider != "local"
        and cfg.model not in VISION_CAPABLE_MODELS
    )


def warn_if_not_vision_capable(use_case: str, cfg: "UseCaseConfig") -> bool:
    """Log when a vision use case resolves to a model we don't know to be
    multimodal. Returns True when the pairing looks safe.

    Deliberately advisory. `local` is exempt because we have no way to know
    what an operator has loaded into LM Studio, and refusing to run would be
    worse than letting them find out.
    """
    if not vision_choice_unverified(use_case, cfg):
        return True
    logger.warning(
        "Use case %r sends images but resolved to %s:%s, which is not in "
        "VISION_CAPABLE_MODELS. If that model is text-only it will either "
        "reject the request or silently describe the image from surrounding "
        "text. Verify before relying on the output.",
        use_case, cfg.provider, cfg.model,
    )
    return False


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
        """Short string for logs: ``openai:gpt-5.5:medium``."""
        return f"{self.provider}:{self.model}:{self.reasoning}"


# ---------------------------------------------------------------------------
# Measured guidance (S-1.14.7)
# ---------------------------------------------------------------------------
#
# E-1.14 measured, per use case, how much quality a tier gives up on the real
# corpus (D-055 → D-062, D-073). Those verdicts lived only in decisions.md,
# so the per-user override page offered a raw model picker. ``guidance``
# carries them to the user: what was measured against the flagship tier,
# what breaks on a downgrade, and which models measured unacceptable.
#
# Rules for writing an entry:
# * ``measured`` only when THIS use case's own output was graded. A use case
#   that merely sat inside a graded chain, or moved tier alongside one that
#   was graded, is ``unmeasured`` with a ``note`` saying so.
# * A ``ModelVerdict`` cites the decision that measured it, which may differ
#   from the entry's decision (a measured failure can exist for a use case
#   whose quality delta is unmeasured).
# * Advisory, never enforced: the settings page warns, it does not refuse
#   (same fail-soft rule as VISION_CAPABLE_MODELS).

GuidanceStatus = Literal["measured", "unmeasured"]
VerdictKind = Literal["unacceptable", "weaker"]

# Every level except ``off``. A verdict scoped to these covers "reasoning on"
# whatever the level is called — ``minimal`` remaps to ``low`` on gpt-5.x.
_REASONING_ON: tuple[str, ...] = ("minimal", "low", "medium", "high", "auto")


@dataclass(frozen=True)
class ModelVerdict:
    """A measured verdict on one model for one use case.

    ``unacceptable`` means the measurement found unusable output (empty,
    unparseable, or substantively wrong at a rate nobody would accept).
    ``weaker`` means measurably worse than the default on the grading the
    decision used, but not unusable.
    """

    model: str
    verdict: VerdictKind
    why: str
    decision_id: str
    # Reasoning levels the verdict covers; empty = every level.
    reasoning: tuple[str, ...] = ()

    def applies_to(self, cfg: "UseCaseConfig") -> bool:
        if cfg.model != self.model:
            return False
        return not self.reasoning or cfg.reasoning in self.reasoning

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "verdict": self.verdict,
            "why": self.why,
            "decision_id": self.decision_id,
            "reasoning": list(self.reasoning),
        }


@dataclass(frozen=True)
class UseCaseGuidance:
    """What the measurements say about choosing a model for a use case.

    ``measured`` entries carry ``decision_id`` + ``decided_on`` (ISO date)
    and the two texts the settings page shows beside the controls:
    ``flagship_delta`` (the measured gap to the flagship or max-effort tier)
    and ``downgrade_risk`` (what fails on a cheaper choice). ``unmeasured``
    entries carry no ``decision_id``; ``note`` says what evidence exists, if
    any, and ``related_decisions`` points at it.
    """

    status: GuidanceStatus
    decision_id: str | None = None
    decided_on: str | None = None
    flagship_delta: str = ""
    downgrade_risk: str = ""
    measured_cost: str = ""
    model_verdicts: tuple[ModelVerdict, ...] = ()
    related_decisions: tuple[str, ...] = ()
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "decision_id": self.decision_id,
            "decided_on": self.decided_on,
            "flagship_delta": self.flagship_delta,
            "downgrade_risk": self.downgrade_risk,
            "measured_cost": self.measured_cost,
            "model_verdicts": [v.as_dict() for v in self.model_verdicts],
            "related_decisions": list(self.related_decisions),
            "note": self.note,
        }


def _unmeasured(
    note: str,
    *,
    related: tuple[str, ...] = (),
    verdicts: tuple[ModelVerdict, ...] = (),
) -> UseCaseGuidance:
    return UseCaseGuidance(
        status="unmeasured",
        note=note,
        related_decisions=related,
        model_verdicts=verdicts,
    )


# Shared verdicts — one measurement, several call sites.

# D-052 amendment: live on qa_refine_context, then applied to every mini site.
_MINI_REASONING_EMPTY = ModelVerdict(
    model="gpt-5.4-mini",
    verdict="unacceptable",
    reasoning=_REASONING_ON,
    why=(
        "With reasoning on, gpt-5.4-mini spent its completion budget thinking "
        "and returned empty output (live, 2026-07-29). Run it with reasoning off."
    ),
    decision_id="D-052",
)

# Moved with the volume tier (D-057) on map-batch evidence alone.
_VOLUME_TIER_NOTE = (
    "Moved from gpt-5.4-nano to gpt-5.6-luna with the rest of the volume tier "
    "(D-057, same price) on map-extraction evidence; this function's own "
    "output has not been graded."
)


@dataclass(frozen=True)
class UseCaseInfo:
    """Registry entry: default config + sizing metadata + rationale.

    The ``default_route`` field is kept for back-compat introspection and
    for the legacy ``LLM_ROUTE_OVERRIDES`` knob. New code reads
    ``default_config`` instead.

    ``guidance`` is the user-facing summary of the measurements behind the
    default (S-1.14.7); ``rationale`` stays the engineer-facing history.
    """

    default_route: Route
    default_config: UseCaseConfig
    summary: str
    typical_input_tokens: int
    p95_input_tokens: int
    typical_output_tokens: int
    min_context_recommended: int
    rationale: str
    guidance: UseCaseGuidance


# ---------------------------------------------------------------------------
# Model context windows (S-1.12.2 / E-1.12)
# ---------------------------------------------------------------------------
#
# INPUT-token limits, EMPIRICALLY MEASURED 2026-07-29 by sending each model
# an oversized prompt and parsing the API's own 400 message ("Input tokens
# exceed the configured limit of N tokens"). Rejected requests are unbilled,
# so re-measuring after a model refresh is free — see D-052.
#
# Callers that assemble large prompts (report map/reduce/channel batching)
# derive their budgets from the RESOLVED model via `context_window_for()`
# instead of the legacy global `LLM_MAX_CONTEXT_TOKENS` constant.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # measured 2026-07-29
    "gpt-5.4-nano": 272_000,
    "gpt-5.4-mini": 272_000,
    "gpt-5.4": 922_000,
    "gpt-5.5": 922_000,
    "gpt-5.5-pro": 922_000,
    "gpt-5.6-luna": 922_000,
    "gpt-5.6-sol": 922_000,
    "gpt-5.6-terra": 922_000,
    "gpt-4.1-mini": 1_047_576,
    # measured 2026-07-29 (Anthropic 400: "prompt is too long: N > M maximum")
    "claude-sonnet-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-haiku-4-5": 200_000,
    # Gemini: models.list metadata (2026-07-29). NOTE: on the FREE tier the
    # effective per-request ceiling is ~250K tokens/min/model and all Pro
    # models are hard-blocked (limit 0) — see D-054 amendment.
    "gemini-3.6-flash": 1_048_576,
    "gemini-3.5-flash": 1_048_576,
    "gemini-3.5-flash-lite": 1_048_576,
    "gemini-3.1-flash-lite": 1_048_576,
    "gemini-3.1-pro-preview": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.5-flash-lite": 1_048_576,
    # documented family values (pre-cutoff knowledge, not re-measured)
    "gpt-4.1": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}

# Unknown models (typos, brand-new releases, local models) get this
# conservative floor so oversized batches fail split, not silent.
DEFAULT_CONTEXT_WINDOW: int = 128_000


def context_window_for(model: str) -> int:
    """Input-token window for ``model``, falling back to prefix matching
    (dated snapshots like ``gpt-5.5-2026-04-23``) then the conservative
    default."""
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    for known, window in sorted(
        MODEL_CONTEXT_WINDOWS.items(), key=lambda kv: -len(kv[0])
    ):
        if model.startswith(known):
            return window
    return DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Model OUTPUT ceilings (S-1.14.8 / D-055)
# ---------------------------------------------------------------------------
#
# Max completion tokens per request, EMPIRICALLY MEASURED 2026-07-30 with the
# same free technique used for the input windows: request an absurd
# ``max_tokens`` and parse the API's own 400 ("This model supports at most N
# completion tokens" / "> N, which is the maximum allowed number of output
# tokens"). Rejected requests are unbilled, so re-measuring is free.
#
# These exist because the report pipeline was starving itself: map emitted at
# most 3,000 tokens per ~116K-token batch and reduce 6,000 per merge, against
# ceilings of 128,000. Call sites now derive their completion budget from the
# work in front of them and clamp to these values instead of hardcoding a
# constant that silently truncates.
MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "gpt-5.4": 128_000,
    "gpt-5.4-mini": 128_000,
    "gpt-5.4-nano": 128_000,
    "gpt-5.5": 128_000,
    "gpt-5.6-luna": 128_000,
    "gpt-5.6-terra": 128_000,
    "gpt-5.6-sol": 128_000,
    "claude-sonnet-5": 128_000,
    "claude-opus-5": 128_000,
    "claude-fable-5": 128_000,
    "claude-haiku-4-5": 64_000,
}

# Conservative floor for unmeasured models (older OpenAI chat models and most
# local servers cap here or lower).
DEFAULT_MAX_OUTPUT_TOKENS = 4_096


def max_output_for(model: str) -> int:
    """Max completion tokens for ``model`` (prefix match for dated snapshots),
    falling back to a conservative default for unmeasured models."""
    if model in MODEL_MAX_OUTPUT_TOKENS:
        return MODEL_MAX_OUTPUT_TOKENS[model]
    for known, limit in sorted(
        MODEL_MAX_OUTPUT_TOKENS.items(), key=lambda kv: -len(kv[0])
    ):
        if model.startswith(known):
            return limit
    return DEFAULT_MAX_OUTPUT_TOKENS


# ---------------------------------------------------------------------------
# Registry. One entry per UseCase literal above.
# ---------------------------------------------------------------------------
#
# Defaults below target OpenAI (the codebase's historical default provider)
# with model tiers chosen per use case. Flip an individual call to Claude
# or Gemini via LLM_USE_CASE_CONFIG without editing this file:
#
#   LLM_USE_CASE_CONFIG=knowledge_synthesize_report=anthropic:claude-sonnet-5:medium
#
# Model lineup re-audited 2026-07-29 (D-052): gpt-5.4 / gpt-5.4-mini are
# back on the account (they were absent at the E-4.9 audit), enabling a
# proper three-tier stack — nano (272K) for high-volume mechanical calls,
# 5.4-mini (272K, reasoning OFF — its reasoning burns the visible
# completion budget; live-validated 2026-07-29) for mid-tier synthesis,
# 5.5 (922K) for flagship
# user-facing output. gpt-5.6-luna/sol/terra are live but undated and
# unprofiled — deliberately NOT defaults until they stabilize. Anthropic
# Claude 5 models (sonnet-5 for long-context refine/compose, haiku-4.5
# for map/classify volume) are strong alternates once ANTHROPIC_API_KEY
# is configured. D-053 (2026-07-29, key now present): claude-sonnet-5
# (measured 1M window, ~79 tok/s, ~2x faster than gpt-5.5 on identical
# generations) owns the four user-facing synthesis sites; qa_history
# formulate stays on 5.5 pending a quality pass. gpt-5.6-luna/sol/terra
# profiled: non-reasoning speed tiers (120/60/16 tok/s) — luna is a
# future volume-tier candidate once dated snapshots + pricing appear.
#
# Token estimates are from production observation + tiktoken measurements
# on representative inputs (2026-04). Order-of-magnitude correct, not
# precise — use them as sizing hints, not SLAs.
USE_CASE_REGISTRY: dict[UseCase, UseCaseInfo] = {
    # --- Job Q&A --------------------------------------------------------
    "qa_clarification": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
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
            "Tiny prompt, tiny output, pattern-matching task. gpt-5.4-nano "
            "with reasoning off is cheap and fast. Safe to route to local "
            "(any instruct model ≥7B handles this cleanly)."
        ),
        guidance=_unmeasured(_VOLUME_TIER_NOTE, related=("D-057",)),
    ),
    "qa_sub_query_expansion": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "Rephrase the user's question into 2 semantically-focused "
            "sub-queries to broaden RAG retrieval coverage."
        ),
        typical_input_tokens=300,
        p95_input_tokens=600,
        typical_output_tokens=150,
        min_context_recommended=2048,
        rationale=(
            "Short in, short out. gpt-5.4-nano is more than sufficient. "
            "Candidate for local routing if retrieval recall is acceptable."
        ),
        guidance=_unmeasured(_VOLUME_TIER_NOTE, related=("D-057",)),
    ),
    "qa_refine_context": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
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
        guidance=_unmeasured(
            "Graded only as part of the whole Q&A chain in D-055 (5.8 vs 8.5 "
            "and 7.2 vs 7.7 against a max-effort challenger); how much of that "
            "gap belongs to this compression step was not isolated.",
            related=("D-055", "D-052"),
            verdicts=(_MINI_REASONING_EMPTY,),
        ),
    ),
    "qa_formulate_answer": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("anthropic", "claude-sonnet-5", "medium"),
        summary=(
            "Produce the final user-facing answer with citations. Runs at "
            "temperature 0 so citations remain deterministic."
        ),
        typical_input_tokens=5_000,
        p95_input_tokens=15_000,
        typical_output_tokens=4_500,
        min_context_recommended=32_768,
        rationale=(
            "User judges the system on this output. Flagship + medium "
            "reasoning reduces citation hallucinations. Reasoning raised "
            "low->medium 2026-07-30 (S-1.14.8): blind judging in D-055 scored "
            "this call 4/10 on completeness (it answered one half of a "
            "two-part question) and 4/10 on synthesis — a judge described the "
            "output as 'an annotated bibliography' that enumerates sources "
            "instead of explaining mechanism. The gap was synthesis depth, "
            "not budget; measured output stayed under the old 4,500 cap."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-056",
            decided_on="2026-07-30",
            flagship_delta=(
                "The whole Q&A chain against Claude Fable 5 at max effort on "
                "the 200-video reference job: 5.8 vs 8.5 on one question, 7.2 "
                "vs 7.7 on the other. The default won citation hygiene, 8 vs "
                "6: every citation resolved to a seekable timestamp. Measured "
                "at low reasoning; not re-judged since the move to medium."
            ),
            downgrade_risk=(
                "At low reasoning, judges scored completeness 4/10 (it "
                "answered one half of a two-part question) and synthesis "
                "4/10: sources listed one after another instead of explained, "
                "'an annotated bibliography'."
            ),
            related_decisions=("D-055",),
        ),
    ),
    "qa_extract_references": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
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
            "thinking. gpt-5.4-nano + strict schema is more reliable."
        ),
        guidance=_unmeasured(_VOLUME_TIER_NOTE, related=("D-057",)),
    ),
    # --- Library-wide Q&A ----------------------------------------------
    "library_qa_clarification": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "Same as qa_clarification, but for questions asked across the "
            "whole video library instead of a single job."
        ),
        typical_input_tokens=400,
        p95_input_tokens=900,
        typical_output_tokens=200,
        min_context_recommended=2048,
        rationale="Same characteristics as qa_clarification.",
        guidance=_unmeasured(_VOLUME_TIER_NOTE, related=("D-057",)),
    ),
    "library_qa_refine_context": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
        summary=(
            "Compact the library-wide RAG hits into focused context before "
            "the final answer. Input can be very large."
        ),
        typical_input_tokens=8_000,
        p95_input_tokens=45_000,
        typical_output_tokens=2_000,
        min_context_recommended=65_536,
        rationale="Same reasoning as qa_refine_context.",
        guidance=_unmeasured(
            "The library path was not part of any quality run.",
            related=("D-052",),
            verdicts=(_MINI_REASONING_EMPTY,),
        ),
    ),
    "library_qa_formulate_answer": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("anthropic", "claude-sonnet-5", "medium"),
        summary="Final library-wide answer with citations across videos.",
        typical_input_tokens=5_000,
        p95_input_tokens=15_000,
        typical_output_tokens=3_000,
        min_context_recommended=32_768,
        rationale="End-of-pipeline output; flagship + medium reasoning.",
        guidance=_unmeasured(
            "Shares the job answer's length policy and moved to medium "
            "reasoning with it on the job path's evidence (D-056); the "
            "library answer itself has not been graded.",
            related=("D-055", "D-056"),
        ),
    ),
    # --- Q&A History (Personal Wiki meta-chat) -------------------------
    "qa_history_refine_context": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "low"),
        summary=(
            "Compact a handful of retrieved past Q&A exchanges into focused "
            "context before the history-chat final answer."
        ),
        typical_input_tokens=2_000,
        p95_input_tokens=8_000,
        typical_output_tokens=1_000,
        min_context_recommended=16_384,
        rationale=(
            "Reasoning raised low->medium 2026-07-30 (S-1.14.8) to mirror "
            "qa_formulate_answer; same synthesis-depth finding applies. "
            "Smaller input than qa_refine_context — gpt-5.4-nano + low "
            "reasoning is sufficient. Flip to local if you want to cut "
            "per-turn latency."
        ),
        guidance=_unmeasured(_VOLUME_TIER_NOTE, related=("D-057",)),
    ),
    "qa_history_formulate_answer": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.5", "medium"),
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
        guidance=_unmeasured(
            "Kept on gpt-5.5 pending a dedicated quality pass (D-053) that "
            "has not run yet.",
            related=("D-053",),
        ),
    ),
    # --- Per-video Knowledge extraction --------------------------------
    "knowledge_extract_batch": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
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
        guidance=_unmeasured(
            "Graded only inside the knowledge chain in D-055, where judges "
            "traced the gap to the synthesis step. " + _VOLUME_TIER_NOTE,
            related=("D-055", "D-057"),
        ),
    ),
    "knowledge_synthesize_report": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("anthropic", "claude-sonnet-5", "medium"),
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
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-055",
            decided_on="2026-07-29",
            flagship_delta=(
                "The knowledge chain against Claude Fable 5 at max effort on "
                "identical input: 5.8 vs 9.0 on a short video, 7.0 vs 8.4 on "
                "a long one. Signal density scored 5 vs 9 and 4 vs 9. Measured "
                "against the report production had stored; not re-judged "
                "since."
            ),
            downgrade_risk=(
                "This is where model tier mattered regardless of pipeline "
                "fixes: the weaker report left speakers unnamed and dropped "
                "the quantitative findings the challenger kept."
            ),
        ),
    ),
    # --- Topic search --------------------------------------------------
    "search_plan_queries": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "low"),
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
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-055",
            decided_on="2026-07-29",
            flagship_delta=(
                "Against Claude Fable 5 at max effort on identical input: 5.6 "
                "vs 7.8. Measured on gpt-5.4-nano; the slot moved to "
                "gpt-5.6-luna (D-057) and has not been re-judged."
            ),
            downgrade_risk=(
                "Already on the cheapest tier, and the measured gap points "
                "upward: the plan decides what every later search can find, "
                "so a weaker plan narrows the whole corpus. One call per job, "
                "so a stronger model here costs cents."
            ),
            related_decisions=("D-057",),
        ),
    ),
    "search_rank_and_curate": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.5", "high"),
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
        guidance=_unmeasured(
            "No head-to-head yet: D-055 could not replay ranking because the "
            "rejected candidates were not stored. An audit graded the picks "
            "6.5/10, and the model did not reliably follow preferred-channel "
            "instructions, so D-059 now enforces those rules in code after "
            "ranking. The stored candidate pool (S-1.14.6) makes a re-rank "
            "comparison possible; it has not been run.",
            related=("D-055", "D-059"),
        ),
    ),
    # --- Report generation (map-reduce over transcripts) ---------------
    "report_map_chunks": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "Map phase: extract key facts from each batch of transcript "
            "chunks. Batches are token-budgeted up to LLM_MAX_CONTEXT_TOKENS."
        ),
        typical_input_tokens=110_000,
        p95_input_tokens=120_000,
        typical_output_tokens=20_000,
        min_context_recommended=32_768,
        rationale=(
            "Sizing corrected 2026-07-30 (S-1.14.8): the registry claimed "
            "p95_input=32,000 while E-1.12 had raised real batches to ~116,000, "
            "and the call site pinned max_tokens=3,000 — so D-055 measured only "
            "5.9% of the extractable content surviving this stage. The completion "
            "budget is now derived from the batch size at the call site. "
            "Highest-volume LLM call in the codebase (dozens per job). "
            "Reasoning OFF is mandatory at this volume — thinking tokens "
            "dominate cost otherwise. Good candidate for local routing."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-057",
            decided_on="2026-07-30",
            flagship_delta=(
                "With the extraction ceiling lifted (D-060), gpt-5.6-luna "
                "extracted 3,233 items covering 189 of 200 videos: about 55% "
                "of a max-effort control's 5,861 items (D-061). On two real "
                "120K-token batches it yielded 1.6-2x gpt-5.4-nano's items "
                "with exact attribution (25 titles for 25 videos)."
            ),
            downgrade_risk=(
                "The report can only contain what this step extracts; "
                "anything it misses never reaches a later stage. gpt-5.4-nano "
                "wrote 52 title variants for 25 videos, which splits "
                "citations, and returned unparseable JSON on one of two "
                "batches, which forces a retry at double cost."
            ),
            measured_cost=(
                "Per 120K-token batch luna cost $0.042-0.049 against "
                "gpt-5.4-nano's $0.042-0.046. Lifting the extraction ceiling "
                "to 0.40 added about $0.34 per 200-video job (D-060)."
            ),
            model_verdicts=(
                ModelVerdict(
                    model="gpt-5.4-nano",
                    verdict="unacceptable",
                    why=(
                        "Unparseable JSON on one of two measured batches, and "
                        "52 title variants for 25 videos on the other."
                    ),
                    decision_id="D-057",
                ),
                ModelVerdict(
                    model="gpt-5.6-luna",
                    verdict="unacceptable",
                    reasoning=_REASONING_ON,
                    why=(
                        "At high reasoning it spent the whole 24,000-token "
                        "completion budget thinking and emitted nothing on "
                        "one of two batches; OpenAI counts reasoning tokens "
                        "against that budget. Keep luna at reasoning off here."
                    ),
                    decision_id="D-057",
                ),
            ),
            related_decisions=("D-056", "D-060", "D-061"),
        ),
    ),
    "report_reduce_summaries": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
        summary=(
            "Reduce phase: consolidate the per-batch summaries into a "
            "single structured summary."
        ),
        typical_input_tokens=6_000,
        p95_input_tokens=20_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale=(
            "DEPRECATED as an LLM call 2026-07-30 (S-1.14.8). reduce_summaries "
            "is now deterministic: a lossless structural union, with even "
            "per-video trimming only past a cost guard. D-055 found ZERO "
            "duplicates in map output on the reference corpus, so the old "
            "LLM merge-and-dedupe could only destroy content — it applied a "
            "flat 6,000-token cap every pairwise round and dropped 46% of "
            "videos wholesale. Entry retained so existing user overrides and "
            "env config keep resolving; changing it has no effect on topic jobs. "
            "Consolidation benefits from a little planning. Low reasoning "
            "on the economy model is the right trade-off."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-056",
            decided_on="2026-07-30",
            flagship_delta=(
                "No longer an LLM call on topic jobs. The deterministic merge "
                "that replaced it keeps 5,861 of 5,861 items; the LLM merge "
                "lost 91.2% of items and 46% of videos on the same corpus."
            ),
            downgrade_risk=(
                "None: changing this model has no effect on topic jobs. The "
                "setting remains only so existing overrides keep resolving."
            ),
            related_decisions=("D-055",),
        ),
    ),
    "report_compose": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("anthropic", "claude-opus-5", "medium"),
        summary=(
            "Compose the final HTML report from the reduced summary + "
            "statistics. Produces thousands of tokens of user-facing text."
        ),
        typical_input_tokens=10_000,
        p95_input_tokens=30_000,
        typical_output_tokens=16_000,
        min_context_recommended=131_072,
        rationale=(
            "Upgraded sonnet-5 -> opus-5 2026-07-31 (D-062) on measured evidence, "
            "not intuition. Synthesis was the ONE dimension that never moved: "
            "6.33/10 across two independent blind rounds while attribution, "
            "coverage and citation integrity all responded to prompt work. A "
            "head-to-head on identical section input had both judges pick opus "
            "(synthesis 9 vs 6-7, tension-handling 9 vs 6). The length prior was "
            "tested and REJECTED: opus ran 2.6x longer AND ~1.4x denser in claims "
            "per 100 words, so ~3.5x total payload. sonnet dropped ~8 debates "
            "present in the corpus, named 18 tools vs 47, contradicted itself by "
            "declaring a consensus it held the rebuttal to, and invented two "
            "unverifiable host names. sonnet wins readability only (8 vs 7). "
            "Costs +$4.55 on the 200-video benchmark ($7.65 -> $12.20). "
            "Long, polished output that the user reads top-to-bottom. "
            "Flagship + medium reasoning."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-062",
            decided_on="2026-07-31",
            flagship_delta=(
                "On claude-sonnet-5 the whole report scored 7.22 against 8.67 "
                "for a max-effort control, and synthesis stayed at 6.33 "
                "through two rounds of prompt fixes. On identical section "
                "input claude-opus-5 beat sonnet-5 on synthesis (9 vs 6-7), "
                "tension handling (9 vs 6) and specificity (9-10 vs "
                "5.5-6); sonnet-5 read better (8 vs 7)."
            ),
            downgrade_risk=(
                "On claude-sonnet-5 the report dropped about 8 debates present "
                "in the corpus, named 18 tools instead of 47, declared a "
                "consensus while quoting the rebuttal, and invented two host "
                "names. opus-5 ran 2.6x longer and was denser per word, so "
                "the length was not padding."
            ),
            measured_cost=(
                "claude-opus-5 adds $4.55 per 200-video job over "
                "claude-sonnet-5 ($7.65 to $12.20 for the whole job)."
            ),
            model_verdicts=(
                ModelVerdict(
                    model="claude-sonnet-5",
                    verdict="weaker",
                    why=(
                        "Synthesis 6-7 vs 9 on identical input; dropped about "
                        "8 corpus debates and invented two host names. Reads "
                        "slightly better."
                    ),
                    decision_id="D-062",
                ),
            ),
            related_decisions=("D-061",),
        ),
    ),
    "report_channel": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.4-mini", "off"),
        summary="Channel-level report composition for channel jobs.",
        typical_input_tokens=6_000,
        p95_input_tokens=15_000,
        typical_output_tokens=4_000,
        min_context_recommended=32_768,
        rationale="Same reasoning as report_compose.",
        guidance=_unmeasured(
            "Channel jobs have not been part of any quality run.",
            related=("D-052",),
            verdicts=(_MINI_REASONING_EMPTY,),
        ),
    ),
    "report_compose_channel_section": UseCaseInfo(
        default_route="primary",
        default_config=UseCaseConfig("openai", "gpt-5.5", "low"),
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
        guidance=_unmeasured("Channel jobs have not been part of any quality run."),
    ),
    # --- Visual understanding (R1 / E-1.18) ----------------------------
    "visual_select_moments": UseCaseInfo(
        default_route="primary",
        # S-1.18.5 (2026-10-19, D-073): medium → low. Same model, same picks
        # 76% of the time (medium agrees with itself 85%), $0.067 instead of
        # $0.097 per video; cheaper models agreed 59% (luna) and 24% (mini).
        default_config=UseCaseConfig("openai", "gpt-5.5", "low"),
        summary=(
            "Read a timestamped transcript and decide WHERE something "
            "visually important happens — a demo, a slide, a chart, a "
            "screen share, a physical object being shown. Returns "
            "[{timestamp_seconds, reason, expected_content}]. Text-only; "
            "it never sees an image."
        ),
        typical_input_tokens=12_000,
        p95_input_tokens=40_000,
        typical_output_tokens=800,
        min_context_recommended=128_000,
        rationale=(
            "This is a JUDGEMENT call, not extraction, and it is the "
            "expensive decision in the pipeline: every moment it picks "
            "costs a video seek plus a vision call, and every moment it "
            "misses is invisible forever. Reasoning MEDIUM on flagship. "
            "One call per video, so the cost is amortised over the frames "
            "it authorises — under-spending here to save one call is a "
            "false economy. p95 input is a full long-form transcript."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-073",
            decided_on="2026-10-19",
            flagship_delta=(
                "Re-run on the same 11 transcripts and scored by agreement "
                "with gpt-5.5's picks at medium reasoning (which agrees with "
                "itself 85% of the time, the noise floor): gpt-5.5 at low "
                "76%, gpt-5.6-luna 59%, gpt-5.4-mini 24%, "
                "gemini-3.1-flash-lite 23%."
            ),
            downgrade_risk=(
                "Each moment picked costs a video seek and a vision call; "
                "each moment missed never reaches the report. Agreement is "
                "not quality, so cheaper models are unproven rather than "
                "proven bad, but mini and flash-lite pick mostly different "
                "moments from the default."
            ),
            measured_cost=(
                "Per video: $0.067 at low against $0.097 at medium; "
                "gpt-5.6-luna $0.002, gpt-5.4-mini $0.009, "
                "gemini-3.1-flash-lite $0.003."
            ),
            model_verdicts=(
                ModelVerdict(
                    model="gpt-5.4-mini",
                    verdict="weaker",
                    why="Agreed with the default's picks 24% of the time (noise floor 85%).",
                    decision_id="D-073",
                ),
                ModelVerdict(
                    model="gemini-3.1-flash-lite",
                    verdict="weaker",
                    why="Agreed with the default's picks 23% of the time (noise floor 85%).",
                    decision_id="D-073",
                ),
            ),
        ),
    ),
    "visual_describe_frame": UseCaseInfo(
        default_route="primary",
        # S-1.18.5 (2026-10-19, D-073): image-grounded blind grading on 33
        # frames x 2 graders — gpt-5.5 4.52/5 (3 of 66 unusable), this model
        # 4.21 (5 unusable), gpt-5.6-luna 3.97 (22 unusable). Flash-lite costs
        # $0.008 per video against $0.122 for gpt-5.5 and keeps the whole
        # visual pass under the $0.10 ceiling the R1 protocol fixed.
        default_config=UseCaseConfig("google", "gemini-3.1-flash-lite", "off"),
        summary=(
            "MULTIMODAL. Describe one captured frame IN TRANSCRIPT "
            "CONTEXT: what is on screen, and specifically what it adds "
            "beyond what is being said. Also judges whether the frame is "
            "informative at all. See VISION_USE_CASES — the model here is "
            "not freely swappable."
        ),
        typical_input_tokens=2_500,
        p95_input_tokens=5_000,
        typical_output_tokens=250,
        min_context_recommended=32_768,
        rationale=(
            "Volume is the constraint: up to VISUAL_MAX_FRAMES_PER_JOB "
            "calls, each carrying an image. Reasoning LOW rather than off "
            "— the task is not pure transcription, it has to decide what "
            "in the frame is NEW relative to the words, and reasoning-off "
            "reliably degrades into 'a man is speaking to a camera'. Not "
            "on the economy tier: a mis-read chart axis becomes a "
            "confident false statement in the report, and unlike a weak "
            "text summary nothing downstream can catch it. Image tokens "
            "dominate the input cost, so the model-tier delta on the text "
            "half is a rounding error."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-073",
            decided_on="2026-10-19",
            flagship_delta=(
                "Blind per-frame grading, two graders per frame, each opening "
                "the image. First pass (33 frames): gpt-5.5 4.52/5 (3 of 66 "
                "gradings unusable), gemini-3.1-flash-lite 4.21 (5), "
                "gpt-5.6-luna 3.97 (22). Second pass (31 frames): "
                "gemini-3.5-flash 4.70 (0 of 62), gpt-5.5 4.54 (5), "
                "gpt-5.4-mini 4.37 (5), claude-haiku-4-5 2.39 (55). At report "
                "level the small per-frame gap was not small: with gpt-5.5 "
                "descriptions the annotated report beat the plain one with 3 "
                "of 3 judges, with flash-lite it tied, 1 of 3 (D-075)."
            ),
            downgrade_risk=(
                "Per-frame grades did not predict the report-level loss, so a "
                "cheaper describer can look fine frame by frame and still "
                "erase the benefit of the visual pass. A misread chart axis "
                "becomes a confident false statement nothing downstream "
                "catches, and a model that cannot see images does not fail "
                "loudly: it describes the frame from the transcript."
            ),
            measured_cost=(
                "Per video: $0.008 on gemini-3.1-flash-lite against $0.133 on "
                "gpt-5.5; gemini-3.5-flash $0.051, claude-haiku-4-5 $0.026, "
                "gpt-5.4-mini $0.018, gpt-5.6-luna $0.004."
            ),
            # Both verdicts are on VISION_CAPABLE_MODELS: accepting an image
            # is not the same as reading one.
            model_verdicts=(
                ModelVerdict(
                    model="gpt-5.6-luna",
                    verdict="unacceptable",
                    why=(
                        "22 of 66 gradings unusable, with substantive "
                        "misreads: wrong dates on an axis, a code cell "
                        "reported as output, wrong variable names."
                    ),
                    decision_id="D-073",
                ),
                ModelVerdict(
                    model="claude-haiku-4-5",
                    verdict="unacceptable",
                    why=(
                        "55 of 62 gradings unusable (2.39/5), with 146 "
                        "misreads and 68 hallucinated details counted across "
                        "them, although it accepts images."
                    ),
                    decision_id="D-075",
                ),
            ),
            related_decisions=("D-071", "D-075"),
        ),
    ),
    # --- Discussed-era extraction (R3 / S-1.17.2) ----------------------
    "temporal_scope_extract": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "Per-document: which period does this source DISCUSS, as "
            "distinct from when it was published? Returns strict JSON "
            "{era_start, era_end, era_confidence, is_retrospective, "
            "era_label} from the title, description, publish date and three "
            "sampled transcript windows. Persisted on "
            "documents.discussed_era_json and reused by every later job."
        ),
        typical_input_tokens=5_000,
        p95_input_tokens=6_500,
        typical_output_tokens=80,
        min_context_recommended=16_384,
        rationale=(
            "Map-phase volume (one call per NEW document, then cached "
            "forever) and a tiny structured output, so the economy tier "
            "with reasoning OFF. Off is mandatory, not a preference: "
            "max_completion_tokens includes reasoning tokens on OpenAI "
            "models, and the call site caps at 400 — a thinking model "
            "spends the whole budget thinking and returns nothing (the "
            "D-052 trap, hit three times). Fail-soft at the call site: a "
            "failed probe or call leaves the era unknown and the job "
            "continues, which is why this use case is deliberately NOT in "
            "llm_smoke.FEATURE_TO_USE_CASES."
        ),
        guidance=_unmeasured(
            "Era extraction has not been graded. Reasoning must stay off: the "
            "call caps output at 400 tokens, and OpenAI models count "
            "reasoning tokens against that cap.",
            related=("D-072",),
            verdicts=(
                ModelVerdict(
                    model="gpt-5.6-luna",
                    verdict="unacceptable",
                    reasoning=_REASONING_ON,
                    why=(
                        "With reasoning on, luna can spend the whole 400-token "
                        "cap thinking and return no era; the same trap "
                        "emptied a 24,000-token map budget in D-057."
                    ),
                    decision_id="D-072",
                ),
            ),
        ),
    ),
    # --- Code-mixed speech (R5 / S-1.16.2) ------------------------------
    "code_mixing_detect": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "Word-level language labelling of transcript snippets from "
            "speakers who mix Hindi/Urdu and English. Returns, per snippet, "
            "the Hindi runs VERBATIM and the matrix (grammar) language as "
            "strict JSON; code_mixing_service.spans_to_tags maps the runs "
            "back onto tokens. Covers romanised Hindi, which script "
            "profiling cannot see, and English written in Devanagari."
        ),
        typical_input_tokens=1_800,
        p95_input_tokens=3_000,
        typical_output_tokens=900,
        min_context_recommended=16_384,
        rationale=(
            "Volume tier with reasoning OFF: a labelling task over 25 short "
            "snippets per call with a structured output. Off is mandatory, "
            "not a preference — max_completion_tokens includes reasoning "
            "tokens on OpenAI models (the D-052 trap). Fail-soft: a failed "
            "batch leaves those snippets unlabelled and nothing downstream "
            "breaks, so it is deliberately NOT in "
            "llm_smoke.FEATURE_TO_USE_CASES."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-080",
            decided_on="2026-10-19",
            flagship_delta=(
                "Not run against a flagship model. Graded against 300 "
                "hand-labelled units: on held-out romanised Hindi, word-level "
                "precision 0.80 and recall 0.90; on Hindi captions written in "
                "Devanagari, F1 0.97. A free lexicon tagger was more precise on "
                "romanised text, so this call is the evaluation reference, not "
                "part of ingest."
            ),
            downgrade_risk=(
                "Keep reasoning off: the call caps output at 4,000 tokens and "
                "OpenAI models count reasoning tokens against that cap. Its "
                "spans drift in format between batches, which the span mapper "
                "absorbs; a model that paraphrases spans instead of copying "
                "them would lose recall."
            ),
            measured_cost="About 2.6 input and 1.3 output tokens per word of text.",
        ),
    ),
    "code_mixing_render_english": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "English rendering of a non-English transcript chunk, used ONLY "
            "as the text the chunk is embedded as (the stored text stays the "
            "original, which is what gets quoted). Six chunks per call, once "
            "per document at insert time (chroma_service.insert_chunks); "
            "stored as chunk metadata `text_en`."
        ),
        typical_input_tokens=3_500,
        p95_input_tokens=6_000,
        typical_output_tokens=1_800,
        min_context_recommended=16_384,
        rationale=(
            "Volume tier with reasoning OFF: a faithful translation with a "
            "structured output, run over every non-English chunk once. Off is "
            "mandatory — max_completion_tokens includes reasoning tokens on "
            "OpenAI models (the D-052 trap). Fail-soft: a failed batch embeds "
            "its chunks as written, which is how every chunk embedded before, "
            "so it is deliberately NOT in llm_smoke.FEATURE_TO_USE_CASES."
        ),
        guidance=UseCaseGuidance(
            status="measured",
            decision_id="D-084",
            decided_on="2026-10-19",
            flagship_delta=(
                "Not run against a flagship model. Graded by what it is for: "
                "with this model's renderings embedded, 55 English questions "
                "found their Hindi chunk at MRR 0.81 (recall@15 0.93), against "
                "0.57 for the Devanagari originals and 0.40 for the same text "
                "romanised."
            ),
            downgrade_risk=(
                "A rendering that summarises instead of translating loses "
                "recall for every passage it shortens. Keep reasoning off: the "
                "call caps output at 8,000 tokens and OpenAI models count "
                "reasoning tokens against that cap."
            ),
            measured_cost=(
                "About 1.5 input and 1.0 output tokens per word of transcript, "
                "plus ~300 prompt tokens per six-chunk call; once per document."
            ),
        ),
    ),
    # --- Social-media candidate classification (S-1.5.3) ---------------
    "social_classify_stance": UseCaseInfo(
        default_route="fast",
        default_config=UseCaseConfig("openai", "gpt-5.6-luna", "off"),
        summary=(
            "Per-candidate-Document (and per-comment) classification "
            "returning {stance, sentiment, framing, topic_relevance}. "
            "Used at fetch time during social-media ingest (Reddit, HN, "
            "Mastodon, Bluesky, paste-mode FB/IG/LI/X). See "
            "app/services/social_classify.py for the schema and the "
            "TOPIC_RELEVANCE_THRESHOLD = 0.50 surfacing cut."
        ),
        typical_input_tokens=600,
        p95_input_tokens=1_200,
        typical_output_tokens=80,
        min_context_recommended=2_048,
        rationale=(
            "Short post body in, structured 4-field JSON out. Volume is "
            "high (one call per Document + one per top comment, easily "
            "hundreds per topic search). Cheap-and-fast model with "
            "reasoning off is the right pick — the calibrated scoring "
            "discipline lives in the prompt exemplars (D-014 framing + "
            "D-021 topic-relevance), not in chain-of-thought. Safe to "
            "route to local for cost-sensitive operators (any "
            "instruction-tuned ≥7B model handles it cleanly)."
        ),
        guidance=_unmeasured(_VOLUME_TIER_NOTE, related=("D-057",)),
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

    1. Per-user override (E-1.13) — set for the current request/task via
       ``llm_service.byok_context`` loading ``user_llm_overrides`` rows
       into ``user_override_context``
    2. ``LLM_USE_CASE_CONFIG`` — inline per-use-case provider/model/reasoning
    3. ``LLM_ROUTE_OVERRIDES`` legacy — flips provider to ``local`` when
       route=fast, or keeps the default when route=primary
    4. Registry ``default_config``

    Raises ``KeyError`` for unknown use cases (programmer error).
    """
    if use_case not in USE_CASE_REGISTRY:
        raise KeyError(
            f"Unknown LLM use_case {use_case!r}. Add it to "
            f"app/services/llm_routing.USE_CASE_REGISTRY and to the "
            f"UseCase literal."
        )
    info = USE_CASE_REGISTRY[use_case]

    user_overrides = user_override_context.get()
    if user_overrides and use_case in user_overrides:
        return user_overrides[use_case]

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


def assess_choice(use_case: str, cfg: UseCaseConfig) -> list[dict]:
    """Measured warnings for running ``use_case`` on ``cfg`` (S-1.14.7).

    Advisory, like ``warn_if_not_vision_capable``: callers show these and
    nothing refuses the config. Each item is ``{kind, model, why,
    decision_id}``; ``kind`` is a ``ModelVerdict.verdict`` (``unacceptable``
    / ``weaker``) or ``not_vision_capable``. Model ids match exactly, like
    ``VISION_CAPABLE_MODELS`` — a prefix rule would let ``gpt-5.5`` match
    ``gpt-5.5-pro``. The settings page mirrors this rule client-side so a
    warning appears before the save round-trips; keep the two in step.
    """
    info = USE_CASE_REGISTRY.get(use_case)  # type: ignore[call-overload]
    if info is None:
        return []
    warnings = [
        {
            "kind": v.verdict,
            "model": v.model,
            "why": v.why,
            "decision_id": v.decision_id,
        }
        for v in info.guidance.model_verdicts
        if v.applies_to(cfg)
    ]
    if vision_choice_unverified(use_case, cfg):
        warnings.append(
            {
                "kind": "not_vision_capable",
                "model": cfg.model,
                "why": (
                    "This function sends images, and this model is not on the "
                    "list of models known to accept them. A text-only model "
                    "either rejects the request or describes the frame from "
                    "the surrounding transcript."
                ),
                "decision_id": None,
            }
        )
    return warnings


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
        g = info.guidance
        evidence = (
            f"measured ({g.decision_id}, {g.decided_on})"
            if g.status == "measured"
            else "unmeasured"
        )
        lines.append(
            f"  - {name} → {info.default_config.as_label()}{marker}\n"
            f"      summary: {info.summary}\n"
            f"      input  p50={info.typical_input_tokens:>6}  "
            f"p95={info.p95_input_tokens:>6}  "
            f"output p50={info.typical_output_tokens:>5}\n"
            f"      min local context: {info.min_context_recommended:>6} tokens\n"
            f"      guidance: {evidence}\n"
            f"      why: {info.rationale}"
        )
        for w in assess_choice(name, effective):
            lines.append(f"      WARNING ({w['kind']}): {w['why']}")
    return "\n".join(lines)

"""Per-use-case cost estimator — E-1.13.

Estimates what a benchmark workload costs under a given set of
(use_case -> model) assignments. The benchmark is the REAL reference
job 0d4db8c3 ("new AI enhancements..." — 200 videos, 947,239 transcript
words) plus assumed interactive usage, so numbers reflect this
install's actual corpus shape rather than synthetic averages.

Call-count/token formulas mirror the shipped pipeline mechanics
(E-1.12): map batches derive from the RESOLVED model's context window
(0.5 safety x 120K quality cap), tournament ranking rounds derive from
the pool size, QA figures come from measured production exchanges.
"""
from dataclasses import dataclass
from math import ceil

from app.services.llm_routing import (
    USE_CASE_REGISTRY,
    UseCaseConfig,
    context_window_for,
    resolve_config,
)
from app.services.model_pricing import PRICING_AS_OF, estimate_call_cost, pricing_for

# ---------------------------------------------------------------------------
# Benchmark constants — job 0d4db8c3 actuals (2026-07) + assumed usage.
# ---------------------------------------------------------------------------

BENCHMARK = {
    "label": "A job like your 200-video AI research run",
    "job_id": "0d4db8c3-5f3a-482e-aa00-784d94bb548c",
    "videos": 200,
    "transcript_words": 947_239,
    "corpus_tokens": 1_260_000,           # words x 1.33
    "formatted_map_tokens": 1_340_000,    # + per-chunk headers
    "chunks": 5_164,
    "rank_pool": 417,                      # candidates discovered pre-curation
    "questions_assumed": 20,               # job-scoped Q&A questions
    "library_questions_assumed": 10,
    "history_chats_assumed": 5,
    "knowledge_videos_assumed": 20,        # 10% of corpus
    "clarify_uses_assumed": 5,
    "pricing_as_of": PRICING_AS_OF,
}

_QUALITY_BATCH_CAP = 120_000
_RANK_BATCH = 400


@dataclass
class UseCaseEstimate:
    use_case: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    pricing_known: bool
    pricing_note: str = ""
    # S-1.14.7: the same workload on the registry default, so the settings
    # page can show what a choice costs relative to the measured default.
    default_model: str = ""
    default_cost_usd: float | None = None


def _map_budget(model: str) -> int:
    return min(int(context_window_for(model) * 0.5), _QUALITY_BATCH_CAP)


def _workload(use_case: str, model: str) -> tuple[int, int, int]:
    """(calls, total input tokens, total output tokens) for the benchmark."""
    b = BENCHMARK
    q = b["questions_assumed"]
    lq = b["library_questions_assumed"]
    hc = b["history_chats_assumed"]
    kv = b["knowledge_videos_assumed"]

    if use_case == "search_plan_queries":
        return 1, 1_000, 400
    if use_case == "search_rank_and_curate":
        pool_tokens = b["rank_pool"] * 110
        if b["rank_pool"] <= _RANK_BATCH:
            return 1, pool_tokens + 400, 2_600
        rounds = ceil(b["rank_pool"] / _RANK_BATCH)
        return rounds + 1, pool_tokens + rounds * 400 + 30_000, (rounds + 1) * 2_000
    if use_case == "report_map_chunks":
        # S-1.14.8: the completion budget is derived from the batch (20% of
        # its input), not a flat 2,000. Measured on the reference corpus:
        # ~15-21K output tokens per 120K batch.
        batches = ceil(b["formatted_map_tokens"] / _map_budget(model))
        per_batch_out = int(_map_budget(model) * 0.30)   # observed under the 0.40 ceiling
        return batches, b["formatted_map_tokens"] + batches * 250, batches * per_batch_out
    if use_case == "report_reduce_summaries":
        # Reduce is deterministic now (D-056) — no LLM call on topic jobs.
        return 0, 0, 0
    if use_case == "report_compose":
        # Sectioned composition (D-056): the consolidated extraction is split
        # across section calls, so input tracks the corpus and output is
        # roughly proportional to it rather than a single 16K completion.
        batches = ceil(b["formatted_map_tokens"] / _map_budget(model))
        consolidated = batches * int(_map_budget(model) * 0.30)
        calls = max(2, ceil(consolidated / 120_000) + 1)
        return calls, consolidated + calls * 600, int(consolidated * 0.5)
    if use_case == "qa_clarification" or use_case == "library_qa_clarification":
        n = b["clarify_uses_assumed"]
        return n, n * 500, n * 200
    if use_case == "qa_sub_query_expansion":
        return q + lq, (q + lq) * 400, (q + lq) * 150
    if use_case == "qa_refine_context":
        return q, q * 13_000, q * 1_500
    if use_case == "qa_formulate_answer":
        return q, q * 4_000, q * 1_600     # measured: 17.85K/3.2K per exchange across the pipeline
    if use_case == "qa_extract_references":
        n = max(1, q // 3)                  # fallback path only
        return n, n * 3_000, n * 300
    if use_case == "library_qa_refine_context":
        return lq, lq * 12_000, lq * 1_500
    if use_case == "library_qa_formulate_answer":
        return lq, lq * 3_500, lq * 1_600
    if use_case == "qa_history_refine_context":
        return hc, hc * 7_000, hc * 1_000
    if use_case == "qa_history_formulate_answer":
        return hc, hc * 3_000, hc * 2_000
    if use_case == "knowledge_extract_batch":
        avg_tokens = b["corpus_tokens"] // b["videos"]
        calls_per_video = max(1, ceil(avg_tokens / 8_000))
        n = kv * calls_per_video
        return n, kv * (avg_tokens + calls_per_video * 400), n * 2_000
    if use_case == "knowledge_synthesize_report":
        avg_tokens = b["corpus_tokens"] // b["videos"]
        return kv, kv * (min(avg_tokens, 20_000) + 3_500), kv * 6_000
    if use_case in ("report_channel", "report_compose_channel_section", "social_classify_stance"):
        return 0, 0, 0                      # not exercised by this (topic/video) benchmark
    if use_case in ("author_book_outline", "author_book_prose", "author_deck_outline", "author_newsletter_compose"):
        return 0, 0, 0                      # books are estimated per book (estimate_calls)
    return 0, 0, 0


def _cost(model: str, calls: int, in_tok: int, out_tok: int) -> float | None:
    """Benchmark cost of one use case's workload on ``model``; 0.0 when the
    benchmark does not exercise it, None when the model has no pricing."""
    if not calls:
        return 0.0
    return estimate_call_cost(model, in_tok, out_tok, in_tok // calls)


def call_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD for one call on ``model``; None when the model has no pricing."""
    return estimate_call_cost(model, input_tokens, output_tokens, input_tokens)


def estimate_calls(calls: list[tuple[str, int, int]]) -> dict:
    """S-6.1.3: what a planned set of calls costs on the configs they resolve
    to now. ``calls`` holds ``(use_case, input_tokens, output_tokens)``;
    output tokens include any reasoning the model is expected to bill."""
    rows: list[dict] = []
    total = 0.0
    priced = True
    for use_case, in_tok, out_tok in calls:
        cfg = resolve_config(use_case)  # type: ignore[arg-type]
        cost = call_cost(cfg.model, in_tok, out_tok)
        if cost is None:
            priced = False
        else:
            total += cost
        rows.append({
            "use_case": use_case,
            "provider": cfg.provider,
            "model": cfg.model,
            "reasoning": cfg.reasoning,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round(cost, 4) if cost is not None else None,
        })
    return {
        "calls": rows,
        "cost_usd": round(total, 4) if priced else None,
        "pricing_as_of": PRICING_AS_OF,
    }


def estimate(overrides: dict[str, UseCaseConfig] | None = None) -> dict:
    """Estimate benchmark cost per use case under ``overrides`` (missing
    entries use the currently-effective config)."""
    overrides = overrides or {}
    rows: list[UseCaseEstimate] = []
    total = 0.0
    unknown: set[str] = set()

    for use_case in USE_CASE_REGISTRY:
        cfg = overrides.get(use_case) or resolve_config(use_case)
        calls, in_tok, out_tok = _workload(use_case, cfg.model)
        cost = _cost(cfg.model, calls, in_tok, out_tok)
        default_model = USE_CASE_REGISTRY[use_case].default_config.model
        default_cost = (
            cost
            if default_model == cfg.model
            else _cost(default_model, *_workload(use_case, default_model))
        )
        p = pricing_for(cfg.model)
        known = p is not None
        if calls and not known:
            unknown.add(cfg.model)
        if cost is not None:
            total += cost
        rows.append(
            UseCaseEstimate(
                use_case=use_case,
                model=cfg.model,
                calls=calls,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=round(cost, 4) if cost is not None else None,
                pricing_known=known,
                pricing_note=p.note if p else "no published pricing",
                default_model=default_model,
                default_cost_usd=(
                    round(default_cost, 4) if default_cost is not None else None
                ),
            )
        )

    rows.sort(key=lambda r: (r.cost_usd or 0), reverse=True)
    return {
        "benchmark": BENCHMARK,
        "per_use_case": [r.__dict__ for r in rows],
        "totals": {
            "cost_usd": round(total, 2),
            "unknown_pricing_models": sorted(unknown),
        },
    }

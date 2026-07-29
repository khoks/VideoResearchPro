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
        batches = ceil(b["formatted_map_tokens"] / _map_budget(model))
        return batches, b["formatted_map_tokens"] + batches * 250, batches * 2_000
    if use_case == "report_reduce_summaries":
        batches = ceil(b["formatted_map_tokens"] / _map_budget(model))
        merged = int(batches * 2_000 * 1.3)
        return 1, merged, 4_000
    if use_case == "report_compose":
        return 1, 12_000, 16_000
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
    return 0, 0, 0


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
        per_call_input = in_tok // calls if calls else 0
        cost = (
            estimate_call_cost(cfg.model, in_tok, out_tok, per_call_input)
            if calls
            else 0.0
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

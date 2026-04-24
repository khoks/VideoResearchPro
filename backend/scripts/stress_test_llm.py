"""Stress test any LLM use case or provider via the production build path.

Measures, across a sweep of concurrency levels:

  * per-request latency (p50, p95, max)
  * per-request throughput (output tokens / s of a single request)
  * aggregate throughput (total output tokens / wall-clock)
  * success rate

Then optionally runs a sustained-load phase at a chosen concurrency to see
whether throughput degrades over time (thermal throttling, rate-limit
decay, KV-cache pressure).

Unlike the legacy fast-slot script, this one dispatches through the same
``app.services.llm_service`` builder used in production — so the numbers
reflect real-app behavior (langchain overhead, reasoning params, SDK
retries) against whichever provider the use case resolves to.

Two modes
---------

**Use-case mode**: resolves the config via the registry.

    python scripts/stress_test_llm.py --use-case qa_clarification

**Explicit mode**: build a one-off ``UseCaseConfig`` from CLI flags.

    python scripts/stress_test_llm.py --provider local \\
        --model qwen/qwen3.5-9b --base-url http://localhost:1234/v1

Payload profiles (``small`` / ``medium`` / ``large``) match the three
size classes the app actually generates, so the sweep reflects realistic
prompt sizes rather than synthetic microbenchmarks.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Allow running as a plain script: `python scripts/stress_test_llm.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from app.services.llm_routing import (  # noqa: E402
    USE_CASE_REGISTRY,
    UseCaseConfig,
    resolve_config,
)
from app.services.llm_service import (  # noqa: E402
    _build_from_config,
    get_llm_for,
    probe_config,
)

# --------------------------------------------------------------------------
# Prompt profiles — same three size classes as the legacy fast-slot script,
# tuned to match the small/medium/large LLM calls in the app.
# --------------------------------------------------------------------------
_FILLER_PARA = (
    "In a recent earnings call, the company's CFO described shifting capital "
    "allocation priorities toward share buybacks rather than M&A, citing an "
    "elevated cost of capital and a pipeline of strategic options that no "
    "longer cleared the internal hurdle rate. Analysts on the call pushed "
    "back, noting that peers continue to pursue tuck-in acquisitions at "
    "historically attractive multiples. The CFO responded that management "
    "would remain opportunistic but would not deploy cash at valuations "
    "above the long-run average for comparable assets. "
)


def _pad(base: str, target_words: int) -> str:
    words = base.split()
    while len(words) < target_words:
        words.extend(_FILLER_PARA.split())
    return " ".join(words[:target_words])


PROFILES: dict[str, dict] = {
    # Matches qa_clarification / qa_sub_query_expansion / search_plan_queries.
    "small": {
        "system": "You are a helpful assistant. Be concise.",
        "user": (
            "Rephrase this question in two different ways, returning only "
            "a JSON list of strings. Question: "
            "'What were the main drivers of Q4 earnings?'"
        ),
        "max_tokens": 120,
    },
    # Matches knowledge_extract_batch / report_map_chunks (medium batch).
    "medium": {
        "system": "You are a summarizer. Extract key facts as JSON.",
        "user": _pad(
            "Summarize the following transcript segment as JSON with keys "
            "topics, facts, speakers. Transcript: ",
            target_words=800,  # ~1000 input tokens
        ),
        "max_tokens": 400,
    },
    # Matches qa_refine_context / library_qa_refine_context / big map passes.
    "large": {
        "system": "You are a research assistant compacting transcript data.",
        "user": _pad(
            "Below are search results from multiple videos. Compact the text "
            "into focused bullet points preserving specific numbers and "
            "quotes. Content: ",
            target_words=3000,  # ~4000 input tokens
        ),
        "max_tokens": 500,
    },
}


# --------------------------------------------------------------------------
# Core call + batch primitives.
# --------------------------------------------------------------------------
@dataclass
class CallResult:
    ok: bool
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None


def _extract_usage(resp: object) -> tuple[int, int]:
    """Best-effort (prompt_tokens, completion_tokens) from a langchain response.

    Langchain surfaces token counts as ``usage_metadata`` on AIMessage for
    most modern providers. Providers that don't populate it return zeros,
    which simply suppresses tokens/sec in the summary.
    """
    usage = getattr(resp, "usage_metadata", None) or {}
    return (
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
    )


async def _one_call(llm, profile: dict) -> CallResult:
    messages = [
        SystemMessage(content=profile["system"]),
        HumanMessage(content=profile["user"]),
    ]
    t0 = time.perf_counter()
    try:
        resp = await llm.ainvoke(messages)
        elapsed = time.perf_counter() - t0
        prompt_toks, completion_toks = _extract_usage(resp)
        return CallResult(
            ok=True,
            latency_s=elapsed,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
        )
    except Exception as e:
        return CallResult(
            ok=False,
            latency_s=time.perf_counter() - t0,
            prompt_tokens=0,
            completion_tokens=0,
            error=f"{type(e).__name__}: {e!s}"[:200],
        )


async def _run_batch(
    llm,
    profile: dict,
    concurrency: int,
    total_calls: int,
) -> tuple[list[CallResult], float]:
    """Fire ``total_calls`` with at most ``concurrency`` in flight at once."""
    sem = asyncio.Semaphore(concurrency)

    async def bounded() -> CallResult:
        async with sem:
            return await _one_call(llm, profile)

    t0 = time.perf_counter()
    results = await asyncio.gather(*(bounded() for _ in range(total_calls)))
    wall = time.perf_counter() - t0
    return results, wall


# --------------------------------------------------------------------------
# Stats + rendering.
# --------------------------------------------------------------------------
def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs_sorted = sorted(xs)
    k = max(0, min(len(xs_sorted) - 1, int(q * len(xs_sorted))))
    return xs_sorted[k]


def _summarize(results: list[CallResult], wall_s: float) -> dict:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    total = len(results)
    out: dict = {
        "ok_count": len(ok),
        "failed_count": len(failed),
        "total": total,
        "success_rate": (len(ok) / total) if total else 0.0,
        "first_error": failed[0].error if failed else None,
        "wall_s": wall_s,
    }
    if not ok:
        return out
    latencies = [r.latency_s for r in ok]
    per_req_tps = [
        r.completion_tokens / r.latency_s if r.latency_s > 0 else 0.0
        for r in ok
    ]
    total_completion_tokens = sum(r.completion_tokens for r in ok)
    out.update(
        lat_p50_s=statistics.median(latencies),
        lat_p95_s=_percentile(latencies, 0.95),
        lat_max_s=max(latencies),
        per_req_tps_mean=statistics.mean(per_req_tps),
        per_req_tps_p50=statistics.median(per_req_tps),
        aggregate_tps=total_completion_tokens / wall_s if wall_s > 0 else 0.0,
        mean_completion_tokens=statistics.mean(
            r.completion_tokens for r in ok
        ),
    )
    return out


def _print_row(label: str, s: dict) -> None:
    if s["ok_count"] == 0:
        print(
            f"  {label:<10} FAILED ({s['failed_count']} errors)  "
            f"first: {s['first_error']}"
        )
        return
    # If tokens/sec is zero across the board the provider didn't report
    # usage — omit the tok/s columns to avoid showing misleading 0.0s.
    tps_part = (
        f"per-req={s['per_req_tps_mean']:>5.1f} tok/s  "
        f"aggregate={s['aggregate_tps']:>6.1f} tok/s  "
        if s["aggregate_tps"] > 0
        else "tok/s=n/a  "
    )
    print(
        f"  {label:<10} "
        f"ok={s['ok_count']:>3}/{s['total']:<3}  "
        f"succ={s['success_rate'] * 100:>5.1f}%  "
        f"lat p50={s['lat_p50_s']:>5.2f}s  p95={s['lat_p95_s']:>5.2f}s  "
        f"{tps_part}"
        f"wall={s['wall_s']:>5.1f}s"
    )


# --------------------------------------------------------------------------
# Config resolution (CLI → UseCaseConfig).
# --------------------------------------------------------------------------
def _resolve_cli_config(args: argparse.Namespace) -> tuple[UseCaseConfig, str]:
    """Return ``(config, label)``, where label is what to show in the banner.

    Use-case mode resolves via the registry so the stress run faithfully
    reflects what production would do for that call site. Explicit mode
    builds a ``UseCaseConfig`` directly from flags.
    """
    if args.use_case:
        cfg = resolve_config(args.use_case)
        return cfg, f"use_case={args.use_case} -> {cfg.as_label()}"
    if not args.provider or not args.model:
        raise SystemExit(
            "Either --use-case or (--provider and --model) must be set. "
            "Run with --help for details."
        )
    cfg = UseCaseConfig(
        provider=args.provider,
        model=args.model,
        reasoning=args.reasoning,
    )
    return cfg, f"explicit -> {cfg.as_label()}"


def _build_llm(cfg: UseCaseConfig, args: argparse.Namespace):
    """Build the chat client using the same path as production.

    Use-case mode goes through ``get_llm_for`` (which re-resolves the
    config; identical result). Explicit mode uses ``_build_from_config``
    so we can inject a CLI-provided base URL for local one-offs without
    touching env vars.
    """
    if args.use_case and not args.base_url:
        return get_llm_for(args.use_case, max_tokens=None)
    # Explicit path — if the caller overrode base_url for local testing,
    # we route through the lower-level builder so the override takes
    # effect without mutating settings. For non-local providers base_url
    # is ignored (langchain picks the SDK default endpoint).
    if args.base_url and cfg.provider == "local":
        # Temporarily patch settings for the duration of this process;
        # _build_from_config reads LLM_LOCAL_BASE_URL via settings.
        from app.config import settings
        settings.LLM_LOCAL_BASE_URL = args.base_url
    return _build_from_config(cfg, temperature=0.0, max_tokens=None)


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------
async def main_async(args: argparse.Namespace) -> int:
    cfg, banner = _resolve_cli_config(args)
    llm = _build_llm(cfg, args)

    print(f"Stress testing {banner}")
    print(f"  profiles: {args.profiles}")
    print(f"  concurrency sweep: {args.concurrency}")
    print()

    # Pre-flight probe so obvious misconfig (bad key, wrong URL) shows up
    # as one clean line instead of a flood of concurrent tracebacks.
    probe = probe_config(cfg, timeout_seconds=30.0)
    if not probe.ok:
        print(f"Pre-flight probe FAILED: {probe.error}")
        print("Aborting stress run.")
        return 1
    print(f"Pre-flight probe ok ({probe.latency_ms}ms)")
    print()

    # Warmup — one call per profile, serially, so we don't measure
    # first-token-after-cold-start latency below.
    print("Warmup:")
    for name in args.profiles:
        r = await _one_call(llm, PROFILES[name])
        if r.ok:
            tps = (
                f"tps={r.completion_tokens / r.latency_s:>5.1f}"
                if r.latency_s > 0 and r.completion_tokens
                else "tps=n/a"
            )
            print(
                f"  {name:<7} {r.latency_s:>5.1f}s  "
                f"in={r.prompt_tokens}  out={r.completion_tokens}  {tps}"
            )
        else:
            print(f"  {name:<7} FAILED: {r.error}")
    print()

    # Concurrency sweep per profile.
    for name in args.profiles:
        profile = PROFILES[name]
        print(
            f"== Profile: {name} "
            f"(approx in~{len(profile['user']) // 4} toks, "
            f"cap out={profile['max_tokens']}) =="
        )
        for concurrency in args.concurrency:
            total_calls = max(concurrency * args.calls_per_concurrency, 4)
            results, wall = await _run_batch(
                llm, profile,
                concurrency=concurrency,
                total_calls=total_calls,
            )
            s = _summarize(results, wall)
            _print_row(f"c={concurrency}", s)
        print()

    # Optional sustained-load phase. Breaks the run into ~15s buckets so
    # you see throughput drift over time.
    if args.sustained_duration > 0 and args.sustained_concurrency > 0:
        profile = PROFILES[args.sustained_profile]
        print(
            f"== Sustained: {args.sustained_duration}s @ "
            f"c={args.sustained_concurrency} profile={args.sustained_profile} =="
        )
        bucket_secs = args.sustained_bucket_secs
        end_at = time.perf_counter() + args.sustained_duration
        bucket_idx = 0
        while time.perf_counter() < end_at:
            bucket_idx += 1
            bucket_deadline = time.perf_counter() + bucket_secs
            bucket_results: list[CallResult] = []
            bucket_start = time.perf_counter()
            while time.perf_counter() < bucket_deadline:
                results, _ = await _run_batch(
                    llm, profile,
                    concurrency=args.sustained_concurrency,
                    total_calls=args.sustained_concurrency * 2,
                )
                bucket_results.extend(results)
            bucket_wall = time.perf_counter() - bucket_start
            s = _summarize(bucket_results, bucket_wall)
            _print_row(f"#{bucket_idx}", s)

    print()
    print("Done.")
    return 0


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stress test an LLM use case or provider through the "
            "production build path (langchain + provider SDK)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    target = parser.add_argument_group("target (choose one)")
    target.add_argument(
        "--use-case",
        default=None,
        choices=sorted(USE_CASE_REGISTRY.keys()),
        help=(
            "Named registry entry to resolve via LLM_USE_CASE_CONFIG + "
            "LLM_ROUTE_OVERRIDES + registry defaults. Mirrors what "
            "production would build for this call site."
        ),
    )
    target.add_argument(
        "--provider",
        default=None,
        choices=["openai", "anthropic", "google", "local"],
        help="Explicit provider (use instead of --use-case for one-offs).",
    )
    target.add_argument(
        "--model",
        default=None,
        help="Explicit model name (required when --provider is set).",
    )
    target.add_argument(
        "--reasoning",
        default="off",
        choices=["off", "minimal", "low", "medium", "high", "auto"],
        help="Reasoning/thinking level for explicit mode.",
    )
    target.add_argument(
        "--base-url",
        default=None,
        help=(
            "Override base URL for provider=local "
            "(e.g. http://localhost:1234/v1). Ignored for SaaS providers."
        ),
    )

    sweep = parser.add_argument_group("sweep")
    sweep.add_argument(
        "--profiles",
        nargs="+",
        default=["small", "medium", "large"],
        choices=list(PROFILES.keys()),
        help="Payload size classes to test.",
    )
    sweep.add_argument(
        "--concurrency",
        default="1,2,4,8,16",
        help=(
            "Concurrency levels to sweep. Comma- or space-separated "
            "(e.g. '1,2,4' or '1 2 4')."
        ),
    )
    sweep.add_argument(
        "--calls-per-concurrency",
        type=int,
        default=3,
        help="Total calls per level = concurrency * this (min 4).",
    )

    sustained = parser.add_argument_group("sustained-load phase")
    sustained.add_argument(
        "--sustained-duration",
        type=int,
        default=0,
        help="If >0, run a sustained-load phase for this many seconds.",
    )
    sustained.add_argument(
        "--sustained-concurrency",
        type=int,
        default=4,
        help="In-flight requests during the sustained phase.",
    )
    sustained.add_argument(
        "--sustained-profile",
        default="medium",
        choices=list(PROFILES.keys()),
        help="Payload profile to use during the sustained phase.",
    )
    sustained.add_argument(
        "--sustained-bucket-secs",
        type=int,
        default=15,
        help="Report-bucket length during the sustained phase.",
    )

    # Legacy flag aliases for back-compat with the fast-slot script.
    legacy = parser.add_argument_group("legacy aliases")
    legacy.add_argument(
        "--sustained-seconds",
        type=int,
        default=None,
        help="Back-compat alias for --sustained-duration.",
    )
    legacy.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Back-compat no-op: langchain uses the provider SDK's default "
            "timeout. Accepted but ignored for script-interface compatibility."
        ),
    )

    return parser


def _parse_concurrency(raw) -> list[int]:
    """Accept either a list of ints (legacy nargs='+') or a string.

    Returns a list of positive ints. Empty/invalid entries are dropped.
    """
    if isinstance(raw, list):
        tokens: list[str] = []
        for item in raw:
            tokens.extend(str(item).replace(",", " ").split())
    else:
        tokens = str(raw).replace(",", " ").split()
    out: list[int] = []
    for t in tokens:
        try:
            n = int(t)
        except ValueError:
            continue
        if n > 0:
            out.append(n)
    return out or [1]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Legacy alias: --sustained-seconds → --sustained-duration.
    if args.sustained_seconds is not None:
        args.sustained_duration = args.sustained_seconds

    args.concurrency = _parse_concurrency(args.concurrency)

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())

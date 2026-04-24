"""Stress test the local LLM fast-slot server (LM Studio / OpenAI-compatible).

Measures, across a sweep of concurrency levels:
  * per-request latency (p50, p95, max)
  * per-request throughput (tokens/sec of a single request)
  * aggregate throughput (total completion tokens / wall-clock)
Then optionally runs a sustained-load phase at a chosen concurrency to see
whether throughput degrades over time (thermal throttling, KV-cache pressure).

It bypasses LangChain and hits the raw OpenAI-compatible endpoint so the
numbers reflect pure server capacity without Python-side overhead.

Usage (from the backend/ directory)::

    ./venv/Scripts/python scripts/stress_test_local_llm.py
    ./venv/Scripts/python scripts/stress_test_local_llm.py --concurrency 1 2 4 8
    ./venv/Scripts/python scripts/stress_test_local_llm.py --sustained-seconds 120 --sustained-concurrency 4

Defaults to ``LLM_FAST_BASE_URL`` / ``LLM_FAST_MODEL`` from your .env.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Allow running as a plain script: `python scripts/stress_test_local_llm.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

# --------------------------------------------------------------------------
# Prompt profiles matching the three size classes of fast-slot registry calls.
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


async def _one_call(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    profile: dict,
    timeout_s: float,
) -> CallResult:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": profile["system"]},
            {"role": "user", "content": profile["user"]},
        ],
        "max_tokens": profile["max_tokens"],
        "temperature": 0.0,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.perf_counter()
    try:
        r = await client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        elapsed = time.perf_counter() - t0
        usage = data.get("usage") or {}
        return CallResult(
            ok=True,
            latency_s=elapsed,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
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
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    profile: dict,
    concurrency: int,
    total_calls: int,
    timeout_s: float,
) -> tuple[list[CallResult], float]:
    """Fire ``total_calls`` with at most ``concurrency`` in flight at once."""
    sem = asyncio.Semaphore(concurrency)

    async def bounded() -> CallResult:
        async with sem:
            return await _one_call(
                client, base_url, api_key, model, profile, timeout_s
            )

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
    out: dict = {
        "ok_count": len(ok),
        "failed_count": len(failed),
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
    print(
        f"  {label:<10} "
        f"ok={s['ok_count']:>3}/{s['ok_count'] + s['failed_count']:<3}  "
        f"lat p50={s['lat_p50_s']:>5.2f}s  p95={s['lat_p95_s']:>5.2f}s  "
        f"per-req={s['per_req_tps_mean']:>5.1f} tok/s  "
        f"aggregate={s['aggregate_tps']:>6.1f} tok/s  "
        f"wall={s['wall_s']:>5.1f}s"
    )


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------
async def main_async(args: argparse.Namespace) -> None:
    base_url = (
        args.base_url or settings.LLM_FAST_BASE_URL or "http://localhost:1234/v1"
    ).rstrip("/")
    model = args.model or settings.LLM_FAST_MODEL
    api_key = settings.LLM_FAST_API_KEY or "not-needed"
    timeout_s = args.timeout

    print(f"Stress testing {model}")
    print(f"  endpoint: {base_url}")
    print(f"  profiles: {args.profiles}")
    print(f"  concurrency sweep: {args.concurrency}")
    print()

    async with httpx.AsyncClient() as client:
        # ------------------------------------------------------------------
        # Warmup — one call per profile, serially, so we're not measuring
        # first-token-after-cold-start latency below.
        # ------------------------------------------------------------------
        print("Warmup (loads weights + KV cache for each profile):")
        for name in args.profiles:
            profile = PROFILES[name]
            r = await _one_call(
                client, base_url, api_key, model, profile, timeout_s
            )
            if r.ok:
                print(
                    f"  {name:<7} {r.latency_s:>5.1f}s  "
                    f"in={r.prompt_tokens}  out={r.completion_tokens}  "
                    f"tps={r.completion_tokens / r.latency_s:>5.1f}"
                )
            else:
                print(f"  {name:<7} FAILED: {r.error}")
        print()

        # ------------------------------------------------------------------
        # Concurrency sweep per profile.
        # ------------------------------------------------------------------
        for name in args.profiles:
            profile = PROFILES[name]
            print(
                f"== Profile: {name} "
                f"(approx in~{len(profile['user']) // 4} toks, "
                f"cap out={profile['max_tokens']}) =="
            )
            for concurrency in args.concurrency:
                total_calls = max(
                    concurrency * args.calls_per_concurrency, 4
                )
                results, wall = await _run_batch(
                    client, base_url, api_key, model, profile,
                    concurrency=concurrency,
                    total_calls=total_calls,
                    timeout_s=timeout_s,
                )
                s = _summarize(results, wall)
                _print_row(f"c={concurrency}", s)
            print()

        # ------------------------------------------------------------------
        # Optional sustained-load phase at a picked concurrency. Breaks the
        # run into ~15s buckets so you see if throughput drifts over time.
        # ------------------------------------------------------------------
        if args.sustained_seconds > 0 and args.sustained_concurrency > 0:
            profile = PROFILES[args.sustained_profile]
            print(
                f"== Sustained: {args.sustained_seconds}s @ "
                f"c={args.sustained_concurrency} profile={args.sustained_profile} =="
            )
            bucket_secs = args.sustained_bucket_secs
            end_at = time.perf_counter() + args.sustained_seconds
            bucket_idx = 0
            while time.perf_counter() < end_at:
                bucket_idx += 1
                bucket_deadline = time.perf_counter() + bucket_secs
                bucket_results: list[CallResult] = []
                bucket_start = time.perf_counter()
                while time.perf_counter() < bucket_deadline:
                    results, _ = await _run_batch(
                        client, base_url, api_key, model, profile,
                        concurrency=args.sustained_concurrency,
                        total_calls=args.sustained_concurrency * 2,
                        timeout_s=timeout_s,
                    )
                    bucket_results.extend(results)
                bucket_wall = time.perf_counter() - bucket_start
                s = _summarize(bucket_results, bucket_wall)
                _print_row(f"#{bucket_idx}", s)

    print()
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress test the local LLM fast-slot server."
    )
    parser.add_argument("--base-url", default=None,
                        help="Override LLM_FAST_BASE_URL")
    parser.add_argument("--model", default=None, help="Override LLM_FAST_MODEL")
    parser.add_argument(
        "--profiles", nargs="+", default=["small", "medium", "large"],
        choices=list(PROFILES.keys()),
    )
    parser.add_argument(
        "--concurrency", nargs="+", type=int, default=[1, 2, 4, 8, 16],
        help="Concurrency levels to sweep",
    )
    parser.add_argument(
        "--calls-per-concurrency", type=int, default=3,
        help="Total calls per level = concurrency * this (min 4)",
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0,
        help="Per-request timeout in seconds",
    )
    parser.add_argument(
        "--sustained-seconds", type=int, default=0,
        help="If >0, run a sustained-load phase for this many seconds",
    )
    parser.add_argument("--sustained-concurrency", type=int, default=4)
    parser.add_argument(
        "--sustained-profile", default="medium",
        choices=list(PROFILES.keys()),
    )
    parser.add_argument("--sustained-bucket-secs", type=int, default=15)
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

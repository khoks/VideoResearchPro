"""Startup-time LLM smoke checks + process-global availability state.

Philosophy: **fail-soft**. If the configured LLMs aren't reachable at
startup we don't crash — we record the failure in a process-global
``LLMStatus`` and let the UI degrade gracefully:

* Non-LLM features (watching videos, viewing past reports, downloading
  exports, browsing history) keep working.
* LLM-requiring features (Q&A, report generation, knowledge extraction)
  are surfaced to the UI via ``/api/v1/health`` and disabled there.

The ``run_startup_probes`` coroutine is called once from the FastAPI
lifespan. It:

1. Resolves the current ``UseCaseConfig`` for every registry entry.
2. Dedupes by ``(provider, model, base_url?)`` — no point probing the
   same (provider, model) pair 19 times.
3. Fires one trivial probe per unique config via ``probe_config`` (run
   in a worker thread because some provider SDKs are synchronous).
4. Stores results on the module-global ``_STATUS`` singleton.

The Celery worker does not share this lifespan. Tasks fail visibly on
the Jobs page when LLM calls raise, which is sufficient surface today.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Iterable

from app.services.llm_routing import (
    USE_CASE_REGISTRY,
    UseCase,
    UseCaseConfig,
    is_vision_use_case,
    resolve_config,
    warn_if_not_vision_capable,
)
from app.services.llm_service import ProbeResult, probe_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature → use case dependency map
# ---------------------------------------------------------------------------
# A feature is user-facing functionality (like the "Ask question" button).
# Each feature depends on one or more use cases being reachable. A
# feature is marked unavailable iff ANY of its use cases failed the probe.
#
# Feature names must match the strings the frontend's useFeatureAvailable
# hook passes in.
FEATURE_TO_USE_CASES: dict[str, list[UseCase]] = {
    "qa": [
        "qa_clarification",
        "qa_sub_query_expansion",
        "qa_refine_context",
        "qa_formulate_answer",
        "qa_extract_references",
    ],
    "library_qa": [
        "library_qa_clarification",
        "library_qa_refine_context",
        "library_qa_formulate_answer",
    ],
    "qa_history": [
        "qa_history_refine_context",
        "qa_history_formulate_answer",
    ],
    "knowledge_extraction": [
        "knowledge_extract_batch",
        "knowledge_synthesize_report",
    ],
    "topic_job": [
        "search_plan_queries",
        "search_rank_and_curate",
        "report_map_chunks",
        "report_reduce_summaries",
        "report_compose",
    ],
    "channel_report": [
        "report_map_chunks",
        "report_reduce_summaries",
        "report_channel",
        "report_compose_channel_section",
    ],
    # R1. Deliberately its own feature rather than folded into topic_job:
    # visual analysis is opt-in, so a vision outage must grey out the
    # visual toggle without making the whole job type look unavailable.
    "visual_analysis": [
        "visual_select_moments",
        "visual_describe_frame",
    ],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class UseCaseStatus:
    """Per-use-case probe outcome (after dedupe fan-out)."""

    use_case: str
    provider: str
    model: str
    reasoning: str
    ok: bool
    latency_ms: int
    error: str | None


# ---------------------------------------------------------------------------
# Process-global singleton
# ---------------------------------------------------------------------------
class LLMStatus:
    """Thread-safe container for the latest smoke-probe results.

    The ``/api/v1/health`` endpoint reads from this; ``run_startup_probes``
    writes to it on startup and can be re-invoked manually via
    ``/api/v1/health/llm/refresh`` (future). Single-writer model: tests
    and callers mutate through ``set_results`` only.
    """

    def __init__(self) -> None:
        # Reentrant: ``as_dict`` acquires the lock and calls ``summary``,
        # which acquires it again.
        self._lock = threading.RLock()
        self._results: dict[str, UseCaseStatus] = {}
        self._last_checked_at: float | None = None

    def set_results(self, results: Iterable[UseCaseStatus]) -> None:
        with self._lock:
            self._results = {r.use_case: r for r in results}
            self._last_checked_at = time.time()

    def reset(self) -> None:
        with self._lock:
            self._results = {}
            self._last_checked_at = None

    def is_use_case_available(self, use_case: str) -> bool:
        """Return True if we have a successful probe for ``use_case``.

        If no probe has run yet (empty state), we conservatively return
        True so the app is usable before the first probe completes.
        Failures only short-circuit features *after* we've confirmed
        they fail.
        """
        with self._lock:
            if not self._results:
                return True
            r = self._results.get(use_case)
            if r is None:
                return True  # unknown — don't block
            return r.ok

    def unavailable_features(self) -> list[str]:
        """Features where at least one required use case failed."""
        with self._lock:
            if not self._results:
                return []
            unavail: list[str] = []
            for feature, use_cases in FEATURE_TO_USE_CASES.items():
                for uc in use_cases:
                    r = self._results.get(uc)
                    if r is not None and not r.ok:
                        unavail.append(feature)
                        break
            return unavail

    def summary(self) -> dict:
        """Compact form for ``GET /api/v1/health``."""
        unavail = self.unavailable_features()
        with self._lock:
            if not self._results:
                status = "unknown"
            elif not unavail:
                status = "ok"
            elif len(unavail) == len(FEATURE_TO_USE_CASES):
                status = "down"
            else:
                status = "degraded"
            return {
                "status": status,
                "unavailable_features": unavail,
                "last_checked_at": self._last_checked_at,
            }

    def as_dict(self) -> dict:
        """Full form for ``GET /api/v1/health/llm``."""
        with self._lock:
            return {
                "summary": self.summary(),
                "use_cases": {
                    uc: {
                        "provider": r.provider,
                        "model": r.model,
                        "reasoning": r.reasoning,
                        "ok": r.ok,
                        "latency_ms": r.latency_ms,
                        "error": r.error,
                    }
                    for uc, r in sorted(self._results.items())
                },
            }


# The singleton. Imported by routers/health.py and tests.
_STATUS = LLMStatus()


# ---------------------------------------------------------------------------
# Probe orchestration
# ---------------------------------------------------------------------------
_ProbeKey = tuple[str, str, bool]


def _dedupe_key(cfg: UseCaseConfig, vision: bool) -> _ProbeKey:
    """Two configs with the same ``(provider, model)`` are treated as
    equivalent for probing purposes — reasoning differences don't change
    reachability.

    ``vision`` is part of the key, not a detail of it. A text-only probe
    against a text-only model succeeds; if a multimodal use case shared a
    probe with a text one on the same (provider, model), a model that
    cannot accept images would be reported healthy and fail on the first
    real frame. The two probes ask different questions, so they cannot
    share an answer.
    """
    return (cfg.provider, cfg.model, vision)


def _collect_probe_targets() -> dict[_ProbeKey, tuple[UseCaseConfig, list[str]]]:
    """Group registry entries by their resolved ``(provider, model, vision)``.

    Returns ``{key: (representative_config, [use_cases_using_it])}``. Probe
    the representative once; fan the result out to every use case in the
    list.
    """
    targets: dict[_ProbeKey, tuple[UseCaseConfig, list[str]]] = {}
    for use_case in USE_CASE_REGISTRY:
        try:
            cfg = resolve_config(use_case)
        except Exception:
            logger.exception(
                "Failed to resolve config for use case %r; skipping probe.",
                use_case,
            )
            continue
        vision = is_vision_use_case(use_case)
        if vision:
            warn_if_not_vision_capable(use_case, cfg)
        key = _dedupe_key(cfg, vision)
        if key not in targets:
            targets[key] = (cfg, [])
        targets[key][1].append(use_case)
    return targets


def _fan_out(
    cfg: UseCaseConfig, use_cases: list[str], result: ProbeResult
) -> list[UseCaseStatus]:
    """Copy one probe result into per-use-case status entries."""
    return [
        UseCaseStatus(
            use_case=uc,
            provider=cfg.provider,
            model=cfg.model,
            reasoning=cfg.reasoning,
            ok=result.ok,
            latency_ms=result.latency_ms,
            error=result.error,
        )
        for uc in use_cases
    ]


async def run_startup_probes(
    *, timeout_seconds_per_probe: float = 15.0
) -> None:
    """Probe every unique (provider, model) in the registry; update ``_STATUS``.

    Runs concurrently across unique configs (typically 2-4 of them) with
    each individual probe scheduled via ``asyncio.to_thread`` — provider
    SDKs are generally synchronous, so threading is the cleanest way to
    avoid blocking the event loop.

    Never raises. All per-probe exceptions are caught inside
    ``probe_config`` and surface as ``ProbeResult(ok=False, ...)``.
    """
    targets = _collect_probe_targets()
    if not targets:
        logger.warning("No LLM probe targets found — registry is empty?")
        _STATUS.set_results([])
        return

    logger.info(
        "LLM startup probes: %d unique configs for %d use cases",
        len(targets),
        sum(len(ucs) for _, ucs in targets.values()),
    )

    async def _probe_one(cfg: UseCaseConfig, vision: bool) -> ProbeResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    probe_config,
                    cfg,
                    timeout_seconds=timeout_seconds_per_probe,
                    vision=vision,
                ),
                timeout=timeout_seconds_per_probe + 5,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "LLM probe timed out for %s after %ss",
                cfg.as_label(),
                timeout_seconds_per_probe + 5,
            )
            return ProbeResult(
                config=cfg,
                ok=False,
                latency_ms=int((timeout_seconds_per_probe + 5) * 1000),
                error=f"timeout after {timeout_seconds_per_probe + 5:.0f}s",
            )
        except Exception as e:
            logger.exception("Unexpected probe failure for %s", cfg.as_label())
            return ProbeResult(
                config=cfg, ok=False, latency_ms=0, error=str(e)[:300]
            )

    keys = list(targets.keys())
    probe_results = await asyncio.gather(
        *(_probe_one(targets[k][0], k[2]) for k in keys),
        return_exceptions=False,
    )

    statuses: list[UseCaseStatus] = []
    for key, result in zip(keys, probe_results):
        cfg, use_cases = targets[key]
        statuses.extend(_fan_out(cfg, use_cases, result))
        if result.ok:
            logger.info(
                "LLM probe OK: %s (%dms) — used by %s",
                cfg.as_label(),
                result.latency_ms,
                ", ".join(use_cases),
            )
        else:
            logger.warning(
                "LLM probe FAILED: %s — %s — used by %s",
                cfg.as_label(),
                result.error,
                ", ".join(use_cases),
            )

    _STATUS.set_results(statuses)
    summary = _STATUS.summary()
    logger.info(
        "LLM status: %s — unavailable features: %s",
        summary["status"],
        summary["unavailable_features"] or "(none)",
    )

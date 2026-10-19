"""/health/llm must report each use case's own reasoning level.

Probes are deduped by (provider, model, vision), so several use cases share
one probe. Before 2026-10-19 the fan-out stamped the representative's
reasoning on all of them: visual_select_moments showed "medium" after it had
moved to "low" (D-073), because another gpt-5.5 use case was probed first.
"""
from __future__ import annotations

from app.services import llm_smoke
from app.services.llm_routing import USE_CASE_REGISTRY, resolve_config


def test_fan_out_keeps_each_use_cases_reasoning():
    cfg = llm_smoke.UseCaseConfig("openai", "gpt-5.5", "medium")
    result = llm_smoke.ProbeResult(config=cfg, ok=True, latency_ms=12.0, error=None)
    statuses = llm_smoke._fan_out(cfg, [("a_use_case", "medium"), ("b_use_case", "low"), "bare_use_case"], result)
    by_uc = {s.use_case: s.reasoning for s in statuses}
    assert by_uc == {"a_use_case": "medium", "b_use_case": "low", "bare_use_case": "medium"}
    assert all(s.model == "gpt-5.5" and s.ok for s in statuses)


def test_collected_targets_carry_the_registry_levels():
    targets = llm_smoke._collect_probe_targets()
    seen = {}
    for _key, (_cfg, entries) in targets.items():
        for uc, reasoning in entries:
            seen[uc] = reasoning
    for use_case in USE_CASE_REGISTRY:
        if use_case in seen:
            assert seen[use_case] == resolve_config(use_case).reasoning, use_case
    assert seen.get("visual_select_moments") == resolve_config("visual_select_moments").reasoning

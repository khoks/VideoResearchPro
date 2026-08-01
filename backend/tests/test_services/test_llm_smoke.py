"""Tests for app.services.llm_smoke -- startup probes + availability state.

Guards:
  * ``LLMStatus.is_use_case_available`` is optimistic on empty state and
    for unknown use cases (don't block features before the first probe).
  * ``LLMStatus.unavailable_features`` correctly flags a feature when any
    of its required use cases failed.
  * ``run_startup_probes`` dedupes by ``(provider, model)``: a single probe
    fans out to every use case sharing that config.
  * ``run_startup_probes`` fails soft: a probe raising doesn't crash the
    orchestrator, and the affected use cases are marked ``ok=False``.
"""
from __future__ import annotations

import pytest

from app.services import llm_smoke
from app.services.llm_routing import UseCaseConfig
from app.services.llm_service import ProbeResult


# ---------------------------------------------------------------------------
# LLMStatus -- logical correctness
# ---------------------------------------------------------------------------
def test_is_use_case_available_is_optimistic_on_empty_state() -> None:
    status = llm_smoke.LLMStatus()
    assert status.is_use_case_available("qa_clarification") is True


def test_is_use_case_available_is_optimistic_for_unknown_use_cases() -> None:
    status = llm_smoke.LLMStatus()
    status.set_results([
        llm_smoke.UseCaseStatus(
            use_case="qa_clarification",
            provider="openai",
            model="gpt-5.4-mini",
            reasoning="off",
            ok=True,
            latency_ms=42,
            error=None,
        ),
    ])
    # qa_clarification is known AND ok.
    assert status.is_use_case_available("qa_clarification") is True
    # Unknown use case: don't block -- return True.
    assert status.is_use_case_available("totally_unknown_use_case") is True


def test_is_use_case_available_returns_false_when_probe_failed() -> None:
    status = llm_smoke.LLMStatus()
    status.set_results([
        llm_smoke.UseCaseStatus(
            use_case="qa_clarification",
            provider="openai",
            model="gpt-5.4-mini",
            reasoning="off",
            ok=False,
            latency_ms=0,
            error="boom",
        ),
    ])
    assert status.is_use_case_available("qa_clarification") is False


def test_unavailable_features_flags_feature_whose_use_case_failed() -> None:
    status = llm_smoke.LLMStatus()
    # qa_formulate_answer is part of the "qa" feature. Fail it; mark
    # every other qa use case ok; the "qa" feature should be flagged.
    results = [
        llm_smoke.UseCaseStatus(
            use_case=uc, provider="openai", model="m", reasoning="off",
            ok=(uc != "qa_formulate_answer"),
            latency_ms=10,
            error=None if uc != "qa_formulate_answer" else "boom",
        )
        for uc in llm_smoke.FEATURE_TO_USE_CASES["qa"]
    ]
    status.set_results(results)

    unavail = status.unavailable_features()
    assert "qa" in unavail


def test_unavailable_features_empty_when_all_ok() -> None:
    status = llm_smoke.LLMStatus()
    # One ok entry covering every use case every feature depends on.
    all_use_cases = {
        uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs
    }
    results = [
        llm_smoke.UseCaseStatus(
            use_case=uc, provider="openai", model="m", reasoning="off",
            ok=True, latency_ms=10, error=None,
        )
        for uc in all_use_cases
    ]
    status.set_results(results)
    assert status.unavailable_features() == []


def test_unavailable_features_empty_on_empty_state() -> None:
    """No probes yet -> conservatively report no features unavailable."""
    status = llm_smoke.LLMStatus()
    assert status.unavailable_features() == []


def test_summary_status_transitions() -> None:
    status = llm_smoke.LLMStatus()

    # Empty -> unknown.
    assert status.summary()["status"] == "unknown"

    # All ok -> "ok".
    all_use_cases = {
        uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs
    }
    status.set_results([
        llm_smoke.UseCaseStatus(
            use_case=uc, provider="openai", model="m", reasoning="off",
            ok=True, latency_ms=10, error=None,
        )
        for uc in all_use_cases
    ])
    assert status.summary()["status"] == "ok"

    # Fail a single use case that belongs to one feature only -> "degraded".
    status.set_results([
        llm_smoke.UseCaseStatus(
            use_case=uc, provider="openai", model="m", reasoning="off",
            ok=(uc != "qa_formulate_answer"),
            latency_ms=10,
            error=None if uc != "qa_formulate_answer" else "boom",
        )
        for uc in all_use_cases
    ])
    assert status.summary()["status"] == "degraded"


# ---------------------------------------------------------------------------
# run_startup_probes -- dedupe + fan-out
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_startup_probes_dedupes_unique_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two unique configs across all registered use cases -> probe_config called twice."""
    registry_names = list(llm_smoke.USE_CASE_REGISTRY.keys())
    # Sanity: registry should be at least 20 (Q&A + library Q&A + Q&A history
    # + knowledge + topic search + reports + social_classify_stance). Bump
    # this when adding new use cases. The exact count isn't load-bearing for
    # the dedup logic the test exercises — it just guards against accidental
    # registry truncation.
    assert len(registry_names) >= 20

    cfg_a = UseCaseConfig("openai", "gpt-5.4", "medium")
    cfg_b = UseCaseConfig("openai", "gpt-5.4-mini", "off")

    # First half of the registry resolves to cfg_a, the rest to cfg_b.
    half = len(registry_names) // 2
    mapping = {uc: (cfg_a if i < half else cfg_b)
               for i, uc in enumerate(registry_names)}

    def fake_resolve(use_case: str) -> UseCaseConfig:
        return mapping[use_case]

    call_count = {"n": 0}

    def fake_probe(
        cfg: UseCaseConfig, *, timeout_seconds: float = 10.0, vision: bool = False
    ) -> ProbeResult:
        call_count["n"] += 1
        return ProbeResult(config=cfg, ok=True, latency_ms=5, error=None)

    monkeypatch.setattr(llm_smoke, "resolve_config", fake_resolve)
    monkeypatch.setattr(llm_smoke, "probe_config", fake_probe)
    # Isolate _STATUS so we don't leak into other tests.
    monkeypatch.setattr(llm_smoke, "_STATUS", llm_smoke.LLMStatus())

    await llm_smoke.run_startup_probes(timeout_seconds_per_probe=1.0)

    # Two configs, plus one probe per vision use case. A vision probe asks a
    # different question (does this model accept an image?) so it cannot
    # share an answer with a text probe on the same (provider, model) — see
    # test_vision_routing.py. Derived, not hardcoded, so adding a vision use
    # case does not fail this test spuriously.
    from app.services.llm_routing import VISION_USE_CASES

    vision_keys = {mapping[uc] for uc in VISION_USE_CASES if uc in mapping}
    expected = 2 + len(vision_keys)
    assert call_count["n"] == expected, (
        f"expected probe_config called once per unique (config, vision) pair; "
        f"got {call_count['n']}, expected {expected}"
    )

    # Every use case is fanned out with ok=True.
    results = llm_smoke._STATUS._results
    assert set(results.keys()) == set(registry_names)
    assert all(r.ok for r in results.values())


@pytest.mark.asyncio
async def test_run_startup_probes_catches_probe_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe raising -> affected use cases marked ok=False, others unaffected."""
    registry_names = list(llm_smoke.USE_CASE_REGISTRY.keys())

    good_cfg = UseCaseConfig("openai", "gpt-5.4-mini", "off")
    bad_cfg = UseCaseConfig("anthropic", "claude-explode", "off")

    # Route just the first registry entry through the bad config.
    bad_use_case = registry_names[0]

    def fake_resolve(use_case: str) -> UseCaseConfig:
        return bad_cfg if use_case == bad_use_case else good_cfg

    def fake_probe(
        cfg: UseCaseConfig, *, timeout_seconds: float = 10.0, vision: bool = False
    ) -> ProbeResult:
        if cfg == bad_cfg:
            raise RuntimeError("provider SDK exploded")
        return ProbeResult(config=cfg, ok=True, latency_ms=5, error=None)

    monkeypatch.setattr(llm_smoke, "resolve_config", fake_resolve)
    monkeypatch.setattr(llm_smoke, "probe_config", fake_probe)
    monkeypatch.setattr(llm_smoke, "_STATUS", llm_smoke.LLMStatus())

    await llm_smoke.run_startup_probes(timeout_seconds_per_probe=1.0)

    results = llm_smoke._STATUS._results
    assert results[bad_use_case].ok is False
    assert results[bad_use_case].error is not None
    # Every other use case (sharing good_cfg) is ok.
    for uc in registry_names[1:]:
        assert results[uc].ok is True, f"{uc}: expected ok=True"


@pytest.mark.asyncio
async def test_run_startup_probes_with_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty registry -> no-op, status is emptied (not left stale)."""
    monkeypatch.setattr(llm_smoke, "USE_CASE_REGISTRY", {})
    monkeypatch.setattr(llm_smoke, "_STATUS", llm_smoke.LLMStatus())

    await llm_smoke.run_startup_probes()

    assert llm_smoke._STATUS._results == {}

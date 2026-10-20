"""`temporal_scope_extract` is registered, economy-tier, reasoning OFF,
probed at startup, and gates no feature (R3 / S-1.17.2)."""
from app.services import llm_smoke
from app.services.llm_routing import USE_CASE_REGISTRY, resolve_config


def test_registered_with_reasoning_off():
    assert "temporal_scope_extract" in USE_CASE_REGISTRY
    cfg = resolve_config("temporal_scope_extract")
    # Strict JSON under a 400-token cap: a reasoning model would spend the
    # whole budget thinking and return nothing (D-052 trap).
    assert cfg.reasoning == "off"
    assert USE_CASE_REGISTRY["temporal_scope_extract"].typical_output_tokens < 400


def test_registry_count_matches_claude_md():
    """CLAUDE.md states the count; keep the two in step."""
    assert len(USE_CASE_REGISTRY) == 28


def test_probed_but_not_a_feature_gate():
    # Targets hold (use_case, reasoning) pairs since #240.
    probed = {
        uc
        for _cfg, use_cases in llm_smoke._collect_probe_targets().values()
        for uc, _reasoning in use_cases
    }
    assert "temporal_scope_extract" in probed
    gated = {uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs}
    assert "temporal_scope_extract" not in gated

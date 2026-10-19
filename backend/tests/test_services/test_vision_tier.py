"""The vision tiers are measured choices and must stay coherent.

`visual_describe_frame` runs on gpt-5.5 by the user's choice in D-081: it gave
the strongest report-level result, and the visual pass now costs about $0.20
per video, a ceiling the user approved over the $0.10 the R1 protocol first
set. `visual_select_moments` stays on gpt-5.5 at low reasoning (D-073). These
tests pin that the defaults are vision-capable, priced, and stay within the
approved ceiling at the measured token counts.
"""
from __future__ import annotations

from app.services.llm_routing import (
    USE_CASE_REGISTRY,
    VISION_CAPABLE_MODELS,
    VISION_USE_CASES,
)
from app.services.model_pricing import MODEL_PRICING

# Measured on job 419e691d (11 videos with transcripts, 120 frames),
# backend/data/r1_ab/retier/; per-video figures divide by the 11 videos
# that produced calls, not the 12 approved.
MEASURED_TOKENS_PER_VIDEO = {
    "visual_select_moments": (95_253 / 11, 8_714 / 11),       # gpt-5.5 low
    "visual_describe_frame": (161_762 / 11, 21_807 / 11),     # gpt-5.5 low
}

# Approved by the user in D-081 (2026-10-19). Raising it again is a decision,
# not a test edit.
APPROVED_CEILING_PER_VIDEO = 0.21


def test_describe_default_is_on_the_vision_allowlist():
    cfg = USE_CASE_REGISTRY["visual_describe_frame"].default_config
    assert "visual_describe_frame" in VISION_USE_CASES
    assert cfg.model in VISION_CAPABLE_MODELS
    assert (cfg.provider, cfg.model) == ("openai", "gpt-5.5")


def test_vision_defaults_are_priced():
    for use_case in ("visual_select_moments", "visual_describe_frame"):
        model = USE_CASE_REGISTRY[use_case].default_config.model
        assert model in MODEL_PRICING, f"{use_case} default {model} has no pricing entry"


def test_vision_pass_costs_within_the_approved_ceiling_per_video():
    total = 0.0
    for use_case, (tok_in, tok_out) in MEASURED_TOKENS_PER_VIDEO.items():
        model = USE_CASE_REGISTRY[use_case].default_config.model
        p = MODEL_PRICING[model]
        total += tok_in / 1e6 * p.input_per_m + tok_out / 1e6 * p.output_per_m
    assert total < APPROVED_CEILING_PER_VIDEO, f"visual pass costs ${total:.3f} per video at the measured token counts"

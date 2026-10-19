"""S-1.18.5 — the vision tiers are measured choices and must stay coherent.

`visual_describe_frame` moved to gemini-3.1-flash-lite on image-grounded
grading (D-073); `visual_select_moments` stayed on gpt-5.5 because every
cheaper selector agreed with it far less than it agrees with itself. These
tests pin that the defaults are vision-capable, priced, and sum to under the
protocol's $0.10-per-video ceiling at the measured token counts.
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
    "visual_describe_frame": (265_068 / 11, 14_410 / 11),     # gemini-3.1-flash-lite
}


def test_describe_default_is_on_the_vision_allowlist():
    cfg = USE_CASE_REGISTRY["visual_describe_frame"].default_config
    assert "visual_describe_frame" in VISION_USE_CASES
    assert cfg.model in VISION_CAPABLE_MODELS
    assert cfg.model == "gemini-3.1-flash-lite" and cfg.provider == "google"


def test_vision_defaults_are_priced():
    for use_case in ("visual_select_moments", "visual_describe_frame"):
        model = USE_CASE_REGISTRY[use_case].default_config.model
        assert model in MODEL_PRICING, f"{use_case} default {model} has no pricing entry"


def test_vision_pass_costs_under_the_protocol_ceiling_per_video():
    total = 0.0
    for use_case, (tok_in, tok_out) in MEASURED_TOKENS_PER_VIDEO.items():
        model = USE_CASE_REGISTRY[use_case].default_config.model
        p = MODEL_PRICING[model]
        total += tok_in / 1e6 * p.input_per_m + tok_out / 1e6 * p.output_per_m
    assert total < 0.10, f"visual pass costs ${total:.3f} per video at the measured token counts"

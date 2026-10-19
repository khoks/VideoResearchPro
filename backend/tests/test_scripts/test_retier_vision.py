"""retier_vision.py — the arithmetic behind a cost verdict must be right.

No provider is called. What is checked: usage is read from the shapes the
adapters produce (and never crashes on a provider that sends nothing), the
price lookup uses the pricing table's real field names, and the selection
overlap counts stored moments, not candidates.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import retier_vision as rv  # noqa: E402


def test_usage_prefers_usage_metadata():
    resp = SimpleNamespace(usage_metadata={"input_tokens": 1380, "output_tokens": 146}, response_metadata={"token_usage": {"prompt_tokens": 1}})
    assert rv.usage_of(resp) == {"input_tokens": 1380, "output_tokens": 146}


def test_usage_falls_back_to_response_metadata_and_to_zero():
    resp = SimpleNamespace(usage_metadata=None, response_metadata={"token_usage": {"prompt_tokens": 90, "completion_tokens": 7}})
    assert rv.usage_of(resp) == {"input_tokens": 90, "output_tokens": 7}
    assert rv.usage_of(SimpleNamespace()) == {"input_tokens": 0, "output_tokens": 0}


def test_price_lookup_uses_the_pricing_table_fields():
    table = {"m": SimpleNamespace(input_per_m=0.2, output_per_m=1.2)}
    assert rv.price_of("m", table) == (0.2, 1.2)
    assert rv.price_of("unknown", table) == (None, None)


def test_price_lookup_against_the_real_table_has_the_r1_models():
    for model in ("gpt-5.5", "gpt-5.6-luna", "gemini-3.1-flash-lite"):
        pin, pout = rv.price_of(model)
        assert pin and pout, model


def test_selection_overlap_counts_stored_moments_within_window():
    stored = [34.0, 130.0, 203.0, 380.0]
    candidate = [40.0, 300.0, 390.0]
    assert rv.selection_overlap(stored, candidate) == 2  # 34↔40 and 380↔390
    assert rv.selection_overlap(stored, []) == 0
    assert rv.selection_overlap([], candidate) == 0


def test_cli_requires_the_three_arguments():
    args = rv.parse_args(["--job-id", "j", "--model", "openai:x:off", "--out", "o.json", "--skip-select"])
    assert args.skip_select and not args.skip_describe and args.limit_frames == 0

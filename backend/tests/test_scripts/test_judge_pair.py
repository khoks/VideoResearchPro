"""judge_pair.py — the parts that decide what a verdict means.

The LLM call is not exercised here. What must never be wrong is the
unblinding: a coin flip that is applied on the way in and not on the way out
would silently invert every verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from judge_pair import html_to_text, parse_judge_json, summarise, unblind  # noqa: E402


def test_html_to_text_drops_script_and_style_keeps_order():
    html = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<h1>Title</h1><p>first   para</p><script>var x = 1;</script>"
        "<ul><li>one</li><li>two</li></ul></body></html>"
    )
    text = html_to_text(html)
    assert "color:red" not in text
    assert "var x" not in text
    assert text.index("Title") < text.index("first para") < text.index("one") < text.index("two")


def test_parse_judge_json_tolerates_prose_around_the_object():
    raw = 'Here is my verdict:\n```json\n{"substance_A": 7, "substance_B": 4, "preferred_on_substance": "A"}\n```\nDone.'
    parsed = parse_judge_json(raw)
    assert parsed == {"substance_A": 7, "substance_B": 4, "preferred_on_substance": "A"}


def test_parse_judge_json_rejects_output_without_an_object():
    with pytest.raises(ValueError):
        parse_judge_json("I cannot compare these.")


@pytest.mark.parametrize(
    "a_name,b_name,pref,expected",
    [
        ("on", "off", "A", "on"),
        ("on", "off", "B", "off"),
        ("off", "on", "A", "off"),  # flipped coin: A was really the OFF arm
        ("off", "on", "B", "on"),
        ("on", "off", "tie", "tie"),
        ("on", "off", "garbage", "tie"),
    ],
)
def test_unblind_maps_preference_through_the_coin_flip(a_name, b_name, pref, expected):
    parsed = {"preferred_on_substance": pref}
    assert unblind(parsed, a_name, b_name)["preferred_on_substance"] == expected


def test_unblind_keeps_scores_and_error_lists_with_their_real_arm():
    parsed = {
        "substance_A": 3,
        "substance_B": 8,
        "visual_use_A": 5,
        "visual_use_B": 9,
        "attribution_errors_A": ["A said X was spoken"],
        "attribution_errors_B": [],
        "fabrications_A": [],
        "fabrications_B": ["invented tool"],
        "preferred_on_substance": "B",
    }
    # Coin flip: label A is really "off", label B is really "on".
    out = unblind(parsed, "off", "on")
    assert out["substance"] == {"off": 3, "on": 8}
    assert out["visual_use"] == {"off": 5, "on": 9}
    assert out["attribution_errors"] == {"off": ["A said X was spoken"], "on": []}
    assert out["fabrications"] == {"off": [], "on": ["invented tool"]}
    assert out["preferred_on_substance"] == "on"


def test_book_rubric_unblinds_its_own_fields_through_the_coin_flip():
    # S-6.1.3: label A is really "none", label B is really "full".
    parsed = {
        "cohesion_A": 4, "cohesion_B": 8,
        "orientation_A": 3, "orientation_B": 9,
        "accuracy_of_framing_A": 10, "accuracy_of_framing_B": 7,
        "unsupported_claims_A": [], "unsupported_claims_B": ["invented link"],
        "misframings_A": [], "misframings_B": [],
        "preferred_overall": "B",
    }
    out = unblind(parsed, "none", "full", "book")
    assert out["cohesion"] == {"none": 4, "full": 8}
    assert out["accuracy_of_framing"] == {"none": 10, "full": 7}
    assert out["unsupported_claims"] == {"none": [], "full": ["invented link"]}
    assert out["preferred_overall"] == "full"
    assert "substance" not in out


def test_summarise_counts_preferences_lists_and_means_per_real_arm():
    results = [
        {"unblinded": {"cohesion": {"full": 8, "none": 4}, "orientation": {"full": 9, "none": 3},
                       "accuracy_of_framing": {"full": 7, "none": 10},
                       "unsupported_claims": {"full": ["x"], "none": []}, "misframings": {"full": [], "none": []},
                       "preferred_overall": "full"}},
        {"unblinded": {"cohesion": {"full": 6, "none": 5}, "orientation": {"full": 7, "none": 5},
                       "accuracy_of_framing": {"full": 9, "none": 10},
                       "unsupported_claims": {"full": [], "none": []}, "misframings": {"full": ["y", "z"], "none": []},
                       "preferred_overall": "tie"}},
        {"error": "timeout"},
    ]
    s = summarise(results, "full", "none", "book")
    assert s["judges_ok"] == 2 and s["judges_total"] == 3
    assert s["preferred_overall"] == {"full": 1, "none": 0, "tie": 1}
    assert s["totals"] == {"unsupported_claims": {"full": 1, "none": 0}, "misframings": {"full": 2, "none": 0}}
    assert s["means"]["cohesion"] == {"full": 7.0, "none": 4.5}


def test_report_summary_keeps_the_keys_earlier_runs_read():
    results = [{"unblinded": {"substance": {"on": 7, "off": 5}, "visual_use": {"on": 6, "off": 5},
                              "attribution_errors": {"on": [], "off": ["a"]}, "fabrications": {"on": [], "off": []},
                              "preferred_on_substance": "on"}}]
    s = summarise(results, "on", "off")
    assert s["preferred_on_substance"] == {"on": 1, "off": 0, "tie": 0}
    assert s["attribution_errors_total"] == {"on": 0, "off": 1}
    assert s["fabrications_total"] == {"on": 0, "off": 0}
    assert s["mean_substance"] == {"on": 7.0, "off": 5.0}

"""S-1.14.7 — measured guidance on every registry entry.

Guards:
  * Every use case is either ``measured`` with a decision id and date, or
    explicitly ``unmeasured`` — no third state, no silent gaps.
  * Every decision a guidance entry cites exists in docs/decisions.md, so a
    renumbered or mistyped id fails here instead of reaching the UI.
  * Verdict models are real model ids (a typo would never match a choice and
    the warning would silently never fire), and no verdict condemns the
    shipped default.
  * ``assess_choice`` reproduces the measured verdicts: D-073's luna-on-frames
    rejection, D-057's luna-with-reasoning failure, and the vision allowlist.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from app.services import llm_routing
from app.services.llm_routing import (
    USE_CASE_REGISTRY,
    UseCaseConfig,
    assess_choice,
)
from app.services.model_pricing import MODEL_PRICING

_DECISIONS_MD = Path(__file__).resolve().parents[3] / "docs" / "decisions.md"
_DECISION_ID = re.compile(r"^D-\d{3}$")


def _decision_headings() -> set[str]:
    text = _DECISIONS_MD.read_text(encoding="utf-8")
    return set(re.findall(r"^## (D-\d{3}) ", text, flags=re.MULTILINE))


def test_every_use_case_is_measured_with_a_decision_or_marked_unmeasured() -> None:
    for name, info in USE_CASE_REGISTRY.items():
        g = info.guidance
        assert g.status in ("measured", "unmeasured"), name
        if g.status == "measured":
            assert g.decision_id and _DECISION_ID.match(g.decision_id), name
            assert g.decided_on, name
            date.fromisoformat(g.decided_on)  # raises on a malformed date
            assert g.flagship_delta.strip(), f"{name}: measured without a delta"
            assert g.downgrade_risk.strip(), f"{name}: measured without a downgrade risk"
        else:
            # An unmeasured entry must not look measured in the UI.
            assert g.decision_id is None, name
            assert g.decided_on is None, name
            assert g.note.strip(), f"{name}: unmeasured without saying why"


def test_measured_set_matches_the_decision_log() -> None:
    """Pin which use cases carry a measurement, so promoting one to
    ``measured`` is a deliberate edit with a decision behind it."""
    measured = {
        name: info.guidance.decision_id
        for name, info in USE_CASE_REGISTRY.items()
        if info.guidance.status == "measured"
    }
    assert measured == {
        "qa_formulate_answer": "D-056",
        "knowledge_synthesize_report": "D-055",
        "search_plan_queries": "D-055",
        "report_map_chunks": "D-057",
        "report_reduce_summaries": "D-056",
        "report_compose": "D-062",
        "visual_select_moments": "D-073",
        "visual_describe_frame": "D-073",
    }


def test_every_cited_decision_exists() -> None:
    headings = _decision_headings()
    assert headings, f"no decision headings parsed from {_DECISIONS_MD}"
    for name, info in USE_CASE_REGISTRY.items():
        g = info.guidance
        cited = set(g.related_decisions) | {v.decision_id for v in g.model_verdicts}
        if g.decision_id:
            cited.add(g.decision_id)
        for d in cited:
            assert _DECISION_ID.match(d), f"{name}: malformed decision id {d!r}"
            assert d in headings, f"{name}: cites {d}, which decisions.md lacks"


def test_verdicts_name_real_models_and_valid_levels() -> None:
    known = set(llm_routing.MODEL_CONTEXT_WINDOWS) | set(MODEL_PRICING)
    for name, info in USE_CASE_REGISTRY.items():
        for v in info.guidance.model_verdicts:
            assert v.model in known, f"{name}: verdict on unknown model {v.model!r}"
            assert v.verdict in ("unacceptable", "weaker"), name
            assert v.why.strip(), name
            for level in v.reasoning:
                assert level in llm_routing._VALID_REASONING, (name, level)


def test_no_default_triggers_a_warning() -> None:
    """A verdict that condemns the shipped default is a contradiction."""
    for name, info in USE_CASE_REGISTRY.items():
        assert assess_choice(name, info.default_config) == [], name


def test_luna_is_unacceptable_for_frame_description() -> None:
    """D-073: 22 of 66 gradings unusable."""
    warnings = assess_choice(
        "visual_describe_frame", UseCaseConfig("openai", "gpt-5.6-luna", "off")
    )
    assert [(w["kind"], w["decision_id"]) for w in warnings] == [
        ("unacceptable", "D-073")
    ]


def test_text_only_model_on_a_vision_use_case_warns() -> None:
    warnings = assess_choice(
        "visual_describe_frame", UseCaseConfig("openai", "gpt-5.4-nano", "off")
    )
    assert [w["kind"] for w in warnings] == ["not_vision_capable"]


def test_local_vision_choice_is_not_flagged() -> None:
    """Same exemption as ``warn_if_not_vision_capable``: we cannot know what
    an operator has loaded locally."""
    assert assess_choice(
        "visual_describe_frame", UseCaseConfig("local", "qwen/qwen3-vl", "off")
    ) == []


def test_vision_check_skips_text_use_cases() -> None:
    assert assess_choice(
        "qa_clarification", UseCaseConfig("openai", "gpt-5.4-nano", "off")
    ) == []


@pytest.mark.parametrize(
    "reasoning, expected",
    [("off", []), ("low", ["unacceptable"]), ("high", ["unacceptable"])],
)
def test_luna_map_verdict_is_scoped_to_reasoning(reasoning, expected) -> None:
    """D-057: luna at high reasoning emitted nothing; at off it is the default."""
    warnings = assess_choice(
        "report_map_chunks", UseCaseConfig("openai", "gpt-5.6-luna", reasoning)
    )
    assert [w["kind"] for w in warnings] == expected


def test_verdict_matches_model_exactly() -> None:
    """``gpt-5.5`` must not catch ``gpt-5.5-pro`` — no prefix matching."""
    v = llm_routing.ModelVerdict(
        model="gpt-5.5", verdict="weaker", why="x", decision_id="D-000"
    )
    assert v.applies_to(UseCaseConfig("openai", "gpt-5.5", "off"))
    assert not v.applies_to(UseCaseConfig("openai", "gpt-5.5-pro", "off"))


def test_sonnet_is_weaker_for_report_compose() -> None:
    """D-062: synthesis 6-7 vs 9 — a warning, not a refusal."""
    warnings = assess_choice(
        "report_compose", UseCaseConfig("anthropic", "claude-sonnet-5", "medium")
    )
    assert [(w["kind"], w["decision_id"]) for w in warnings] == [("weaker", "D-062")]


def test_guidance_serializes_to_plain_json_types() -> None:
    import json

    for name, info in USE_CASE_REGISTRY.items():
        d = info.guidance.as_dict()
        json.dumps(d)  # tuples became lists, nothing exotic
        assert set(d) == {
            "status", "decision_id", "decided_on", "flagship_delta",
            "downgrade_risk", "measured_cost", "model_verdicts",
            "related_decisions", "note",
        }, name

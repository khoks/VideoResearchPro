"""S-1.15.3: a length preference for knowledge reports, at the production caller.

``POST /videos/{id}/extract-knowledge?output_length=brief|standard|deep``
applies D-064's multiplier to S-1.14.8's size-based synthesis budget and
gives the writer that depth's brief. The real agent runs here, through the
router; only the model client (`knowledge_agent.get_llm_for`) is faked, so
what the synthesis call was built with is the assertion.

Unset (or 'auto') must be today's call exactly: the same budget, and a prompt
that differs from a brief one only by the brief's paragraph.

Most tests pin a config with reasoning off, so the multiplier is all that moves
the budget. Thinking is counted inside `max_tokens`, so with reasoning on brief
keeps room for it (the `reasoning` tests below). A synthesis that yields no
report must not reach the shared artifact (the `failed` tests).

Mutation checks. `test_the_router_hands_the_preference_to_the_agent` fails for
a router that drops the preference, and
`test_mutation_a_router_that_drops_the_preference_is_rejected` shows the budget
assertion rejects that mutant. Run by hand on 2026-11-04:
- the router calling the agent without the preference fails
  `test_a_preference_scales_the_synthesis_budget` (brief and deep), the
  hand-off test and the large-extraction test;
- the agent ignoring the multiplier fails the same tests for brief and deep;
- the brief never reaching the prompt fails all three preference cases;
- bracketing one document (`resolve_scale(None, pref)`) fails
  `test_unset_is_the_call_s_1_14_8_shipped`: 1.25x, not 1.0;
- dropping the thinking reserve, or the cap at the unset budget, fails the
  `reasoning` tests;
- dropping the router's empty-report guard fails the `failed` tests;
- T-1.15.3.8: the agent dropping the finish reason, or the router not storing
  it, fails `test_a_cut_off_report_says_so_on_both_endpoints`; carrying the old
  flag over a Regenerate fails `test_a_regenerate_that_fits_clears_the_note`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents import knowledge_agent
from app.config import settings
from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import llm_service, output_length, visibility_service
from app.services.llm_routing import UseCaseConfig

_FLOOR = 8_000  # S-1.14.8's minimum synthesis budget
_BRIEF = int(_FLOOR * 0.45)
_PLAIN = UseCaseConfig("anthropic", "claude-sonnet-5", "off")  # thinking spends nothing
_DEFAULT = UseCaseConfig("anthropic", "claude-sonnet-5", "medium")  # the registry default


@pytest.fixture
def video(db, test_user):
    now = datetime.now(timezone.utc)
    doc = Document(
        video_id="lenVid12345",
        title="Tidal energy storage",
        channel_id=None,
        url="https://www.youtube.com/watch?v=lenVid12345",
        duration_seconds=600,
        published_at=now,
        transcript_status="fetched",
        created_at=now,
    )
    db.add(doc)
    db.add(TranscriptCache(
        video_id=doc.video_id,
        segments_json=json.dumps([
            {"text": "Tidal lagoons store energy behind a wall.", "start": 0.0, "duration": 4.0},
            {"text": "Pumped storage needs a hill.", "start": 4.0, "duration": 3.0},
        ]),
        language="en",
        fetched_at=now,
    ))
    db.commit()
    db.refresh(doc)
    visibility_service.grant(db, [doc.document_id], test_user.id)
    return doc


_SMALL = {"topics": ["tidal storage"], "concepts": ["lagoon"], "events": [], "facts": ["Lagoons hold water."]}
_REPORT = "# Tidal storage\n\n## Overview\n\nText."
_BIG = {
    "topics": [f"topic {i} on tidal storage economics" for i in range(400)],
    "concepts": [],
    "events": [],
    "facts": [f"Fact {i}: lagoon {i} stores {i * 3} megawatt hours at night." for i in range(1200)],
}


class _Models:
    """Stands in for `get_llm_for`: records each call's kwargs and prompt.

    `report` is what synthesis returns, or the exception it raises.
    """

    def __init__(self, extraction: dict, report: str | Exception, stop_reason: str):
        self.extraction = extraction
        self.report = report
        self.stop_reason = stop_reason
        self.calls: list[tuple[str, dict, str]] = []

    def __call__(self, use_case: str, **kwargs):
        llm = MagicMock()

        def invoke(messages):
            self.calls.append((use_case, kwargs, messages[0].content))
            if use_case == "knowledge_extract_batch":
                return MagicMock(content=json.dumps(self.extraction))
            if isinstance(self.report, Exception):
                raise self.report
            return MagicMock(content=self.report, response_metadata={"stop_reason": self.stop_reason})

        llm.invoke.side_effect = invoke
        return llm

    def synthesis(self) -> tuple[dict, str]:
        (call,) = [(kw, prompt) for use_case, kw, prompt in self.calls if use_case == "knowledge_synthesize_report"]
        return call


def _extract(
    client,
    video,
    query: str = "",
    extraction: dict | None = None,
    config: UseCaseConfig = _PLAIN,
    report: str | Exception = _REPORT,
    stop_reason: str = "end_turn",
):
    models = _Models(extraction or _SMALL, report, stop_reason)
    with (
        patch.object(knowledge_agent, "get_llm_for", side_effect=models),
        patch.object(knowledge_agent, "resolve_config", return_value=config),
    ):
        resp = client.post(f"/api/v1/videos/{video.video_id}/extract-knowledge{query}")
    return resp, models


def _merged_tokens(extraction: dict) -> int:
    """What S-1.14.8 sizes the budget from: the merged extraction's JSON."""
    merged = {k: extraction.get(k, []) for k in ("topics", "concepts", "events", "facts")}
    return knowledge_agent._count_tokens(json.dumps(merged, ensure_ascii=False, indent=2))


def _assert_depth_reached_synthesis(models: _Models, pref: str, budget: int) -> None:
    """The preference changed the budget and the brief is in the prompt, in
    its own paragraph before the closing instruction."""
    kwargs, prompt = models.synthesis()
    assert kwargs["max_tokens"] == budget
    assert f"cites.\n\n{output_length.override_guidance(pref)}\n\nReturn ONLY" in prompt


def _artifact(db, video) -> tuple:
    db.expire_all()
    row = db.get(Document, video.document_id)
    return row.extracted_knowledge_json, row.knowledge_report_md, row.knowledge_extracted_at


def _lengthen(db, video, tokens: int) -> None:
    """A transcript with a marker just past ``tokens``."""
    row = db.query(TranscriptCache).filter_by(video_id=video.video_id).one()
    row.segments_json = json.dumps([
        {"text": "OPENING_MARKER " + ("word " * (tokens + 1_000)) + "TAIL_MARKER", "start": 0.0, "duration": 4.0},
    ])
    db.commit()


def test_the_setting_defaults_to_what_the_code_always_spent():
    """T-4.11.2.6: 20,000 is what `min(60000, 20000)` came to, so making the
    setting real moves nobody's spend."""
    assert type(settings).model_fields["KNOWLEDGE_MAX_TRANSCRIPT_TOKENS"].default == 20_000


@pytest.mark.parametrize("setting, tail_reaches_the_prompt", [(20_000, False), (30_000, True)])
def test_the_setting_sizes_the_excerpt_the_writer_sees(
    client, video, db, monkeypatch, setting, tail_reaches_the_prompt
):
    """T-4.11.2.6, through the route. Above 20,000 the setting did nothing until
    now, so the second case fails if the literal comes back."""
    monkeypatch.setattr(settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", setting)
    _lengthen(db, video, 20_000)
    resp, models = _extract(client, video)
    assert resp.status_code == 200, resp.text
    _, prompt = models.synthesis()
    assert "OPENING_MARKER" in prompt
    assert ("TAIL_MARKER" in prompt) is tail_reaches_the_prompt


def test_unset_is_the_call_s_1_14_8_shipped(client, video):
    resp, models = _extract(client, video)
    assert resp.status_code == 200, resp.text
    kwargs, prompt = models.synthesis()
    assert kwargs["max_tokens"] == _FLOOR
    assert "LENGTH:" not in prompt
    assert "cites.\n\nReturn ONLY the Markdown document body." in prompt
    assert resp.json()["output_length"] is None


def test_auto_is_the_same_as_unset(client, video, db):
    _, unset = _extract(client, video)
    resp, auto = _extract(client, video, "?force=true&output_length=auto")
    assert resp.status_code == 200, resp.text
    assert auto.synthesis() == unset.synthesis()
    assert resp.json()["output_length"] is None
    db.expire_all()
    assert "_output_length" not in json.loads(db.get(Document, video.document_id).extracted_knowledge_json)


@pytest.mark.parametrize(
    ("pref", "budget"),
    [("brief", _BRIEF), ("standard", _FLOOR), ("deep", int(_FLOOR * 1.6))],
)
def test_a_preference_scales_the_synthesis_budget(client, video, db, pref, budget):
    resp, models = _extract(client, video, f"?output_length={pref}")
    assert resp.status_code == 200, resp.text
    _assert_depth_reached_synthesis(models, pref, budget)
    # Extraction is not a preference (D-064): its budget never moves.
    (extract_kwargs,) = [kw for use_case, kw, _ in models.calls if use_case == "knowledge_extract_batch"]
    assert extract_kwargs["max_tokens"] == knowledge_agent.EXTRACT_BATCH_MAX_COMPLETION_TOKENS
    # The depth is recorded with the artifact and returned by both endpoints.
    assert resp.json()["output_length"] == pref
    db.expire_all()
    stored = json.loads(db.get(Document, video.document_id).extracted_knowledge_json)
    assert stored["_output_length"] == pref
    assert stored["facts"] == _SMALL["facts"]
    assert client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()["output_length"] == pref


def test_the_brief_is_the_only_difference_in_the_prompt(client, video):
    _, unset = _extract(client, video)
    _, brief = _extract(client, video, "?force=true&output_length=brief")
    guidance = output_length.override_guidance("brief")
    assert brief.synthesis()[1].replace(f"\n{guidance}\n", "") == unset.synthesis()[1]


def test_the_multiplier_applies_on_top_of_the_size_based_budget(client, video):
    """A large extraction already lifts the budget past the floor (S-1.14.8);
    the preference multiplies that figure, it does not replace it."""
    base = _merged_tokens(_BIG)
    assert _FLOOR < base < knowledge_agent.SYNTHESIS_EXTRACTION_JSON_MAX_TOKENS

    _, unset = _extract(client, video, extraction=_BIG)
    _, deep = _extract(client, video, "?force=true&output_length=deep", extraction=_BIG)
    _, brief = _extract(client, video, "?force=true&output_length=brief", extraction=_BIG)
    assert unset.synthesis()[0]["max_tokens"] == base
    assert deep.synthesis()[0]["max_tokens"] == int(base * 1.6)
    assert brief.synthesis()[0]["max_tokens"] == int(base * 0.45)


def test_regenerating_without_a_preference_clears_the_recorded_depth(client, video):
    first, _ = _extract(client, video, "?output_length=deep")
    assert first.json()["output_length"] == "deep"
    again, models = _extract(client, video, "?force=true")
    assert again.json()["output_length"] is None
    assert models.synthesis()[0]["max_tokens"] == _FLOOR


def test_an_unknown_value_is_refused_before_any_model_runs(client, video):
    resp, models = _extract(client, video, "?output_length=enormous")
    assert resp.status_code == 422
    assert models.calls == []


def test_the_router_hands_the_preference_to_the_agent(client, video):
    real = knowledge_agent.run_knowledge_extract_agent
    with patch.object(knowledge_agent, "run_knowledge_extract_agent", wraps=real) as agent:
        resp, _ = _extract(client, video, "?output_length=deep")
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["output_length"] == "deep"


def test_mutation_a_router_that_drops_the_preference_is_rejected(client, video, monkeypatch):
    """The mutant: the agent runs without the preference, as it did before
    S-1.15.3. The assertion the preference tests rely on must refuse it."""
    real = knowledge_agent.run_knowledge_extract_agent
    monkeypatch.setattr(
        knowledge_agent, "run_knowledge_extract_agent", lambda doc, text, **_kw: real(doc, text)
    )
    resp, models = _extract(client, video, "?output_length=deep")
    assert resp.status_code == 200
    with pytest.raises(AssertionError):
        _assert_depth_reached_synthesis(models, "deep", int(_FLOOR * 1.6))


# --- Thinking is counted inside `max_tokens` -------------------------------


@pytest.mark.parametrize("reasoning", ["minimal", "low", "medium", "auto"])
def test_reasoning_brief_clears_the_thinking_budget_on_legacy_claude(client, video, reasoning):
    """Claude models on the enabled+budget_tokens shape refuse a `max_tokens`
    at or below the budget. Brief at the bare 3,600 sat under medium's 4,096."""
    config = UseCaseConfig("anthropic", "claude-haiku-4-5", reasoning)
    thinking = llm_service._anthropic_reasoning_kwargs(reasoning, config.model)["thinking"]["budget_tokens"]
    resp, models = _extract(client, video, "?output_length=brief", config=config)
    assert resp.status_code == 200, resp.text
    max_tokens = models.synthesis()[0]["max_tokens"]
    # Room for the report on top of the thinking, and still below unset.
    assert thinking + _BRIEF <= max_tokens < _FLOOR


def test_reasoning_brief_keeps_room_on_the_default_config(client, video):
    """sonnet-5 thinks adaptively, inside the same `max_tokens`: on a short
    source the brief does the shortening (D-062), the ceiling barely moves."""
    _, unset = _extract(client, video, config=_DEFAULT)
    _, brief = _extract(client, video, "?force=true&output_length=brief", config=_DEFAULT)
    assert unset.synthesis()[0]["max_tokens"] == _FLOOR
    assert _BRIEF + 4_096 <= brief.synthesis()[0]["max_tokens"] < _FLOOR
    assert output_length.override_guidance("brief") in brief.synthesis()[1]


def test_reasoning_brief_never_asks_for_more_than_unset(client, video):
    """`high` thinks past the floor on its own: brief stops at what an unset
    request gets, it does not raise the budget above it."""
    config = UseCaseConfig("anthropic", "claude-haiku-4-5", "high")
    _, unset = _extract(client, video, config=config)
    _, brief = _extract(client, video, "?force=true&output_length=brief", config=config)
    assert brief.synthesis()[0]["max_tokens"] == unset.synthesis()[0]["max_tokens"] == _FLOOR


def test_reasoning_the_multiplier_stands_where_it_already_leaves_room(client, video):
    scaled = int(_merged_tokens(_BIG) * 0.45)
    assert scaled > _BRIEF + 4_096
    _, brief = _extract(client, video, "?output_length=brief", extraction=_BIG, config=_DEFAULT)
    assert brief.synthesis()[0]["max_tokens"] == scaled


@pytest.mark.parametrize("pref", ["standard", "deep"])
def test_reasoning_only_brief_is_lifted(client, video, pref):
    plain = int(_FLOOR * output_length.override_scale(pref))
    _, models = _extract(client, video, f"?output_length={pref}", config=_DEFAULT)
    assert models.synthesis()[0]["max_tokens"] == plain


# --- A synthesis that yields no report --------------------------------------


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("400: max_tokens must be greater than thinking.budget_tokens"), "", "   \n"],
    ids=["refused", "empty", "blank"],
)
def test_a_failed_regenerate_keeps_the_stored_report(client, video, db, failure):
    """The artifact is shared by every tenant (D-063): a Regenerate that
    writes nothing must not blank it, or spend the caller's quota."""
    first, _ = _extract(client, video, "?output_length=deep")
    assert first.status_code == 200, first.text
    before = _artifact(db, video)
    assert before[1] == _REPORT

    with patch("app.services.quota_metering_service.record_usage") as usage:
        resp, _ = _extract(client, video, "?force=true&output_length=brief", report=failure)

    assert resp.status_code == 502
    usage.assert_not_called()
    assert _artifact(db, video) == before
    stored = client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()
    assert stored["knowledge_report_md"] == _REPORT
    assert stored["output_length"] == "deep"


def test_a_failed_first_report_leaves_nothing_behind(client, video, db):
    with patch("app.services.quota_metering_service.record_usage") as usage:
        resp, _ = _extract(client, video, "?output_length=brief", report=RuntimeError("boom"))
    assert resp.status_code == 502
    usage.assert_not_called()
    assert _artifact(db, video) == (None, None, None)
    assert client.get(f"/api/v1/videos/{video.video_id}/knowledge").status_code == 404


def test_a_written_report_is_metered(client, video):
    """The control for the two above: the spy does see a successful run."""
    with patch("app.services.quota_metering_service.record_usage") as usage:
        resp, _ = _extract(client, video, "?output_length=brief")
    assert resp.status_code == 200, resp.text
    usage.assert_called_once()


@pytest.mark.parametrize(("stop_reason", "warned"), [("max_tokens", True), ("end_turn", False)])
def test_a_report_cut_off_at_its_budget_is_logged(client, video, stop_reason, warned):
    """A truncated report is still a report, so it is stored; before this it
    was also silent, because the finish reason was never read."""
    with patch.object(knowledge_agent, "logger") as log:
        resp, _ = _extract(client, video, "?output_length=brief", stop_reason=stop_reason)
    assert resp.status_code == 200, resp.text
    cut_off = [call for call in log.warning.call_args_list if "cut off" in call.args[0]]
    assert bool(cut_off) is warned


# --- T-1.15.3.8: a report cut off at its budget tells the reader -------------


@pytest.mark.parametrize("stop_reason", ["max_tokens", "length", "MAX_TOKENS"])
def test_a_cut_off_report_says_so_on_both_endpoints(client, video, db, stop_reason):
    resp, _ = _extract(client, video, "?output_length=brief", stop_reason=stop_reason)
    assert resp.status_code == 200, resp.text
    assert resp.json()["report_cut_off"] is True
    assert resp.json()["knowledge_report_md"] == _REPORT, "a truncated report is still a report"
    assert client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()["report_cut_off"] is True
    db.expire_all()
    stored = json.loads(db.get(Document, video.document_id).extracted_knowledge_json)
    assert stored["_report_cut_off"] is True
    assert stored["_output_length"] == "brief"
    assert stored["facts"] == _SMALL["facts"]


def test_a_report_that_fits_records_nothing(client, video, db):
    resp, _ = _extract(client, video, "?output_length=brief")
    assert resp.status_code == 200, resp.text
    assert resp.json()["report_cut_off"] is False
    assert client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()["report_cut_off"] is False
    db.expire_all()
    assert "_report_cut_off" not in json.loads(db.get(Document, video.document_id).extracted_knowledge_json)


def test_a_regenerate_that_fits_clears_the_note(client, video):
    first, _ = _extract(client, video, stop_reason="max_tokens")
    assert first.json()["report_cut_off"] is True
    again, _ = _extract(client, video, "?force=true&output_length=deep")
    assert again.json()["report_cut_off"] is False
    assert client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()["report_cut_off"] is False


def test_a_failed_regenerate_keeps_the_note_on_the_report_that_stands(client, video):
    first, _ = _extract(client, video, stop_reason="max_tokens")
    assert first.json()["report_cut_off"] is True
    resp, _ = _extract(client, video, "?force=true&output_length=deep", report="")
    assert resp.status_code == 502
    assert client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()["report_cut_off"] is True


@pytest.mark.parametrize(
    "stored",
    [
        json.dumps({"topics": ["t"], "concepts": [], "events": [], "facts": []}),  # before this was recorded
        json.dumps({"topics": [], "_report_cut_off": "yes"}),
        "not json",
    ],
    ids=["older", "not-a-bool", "corrupt"],
)
def test_a_report_with_no_flag_shows_nothing(client, video, db, stored):
    row = db.get(Document, video.document_id)
    row.extracted_knowledge_json = stored
    row.knowledge_report_md = _REPORT
    row.knowledge_extracted_at = datetime.now(timezone.utc)
    db.commit()
    body = client.get(f"/api/v1/videos/{video.video_id}/knowledge").json()
    assert body["report_cut_off"] is False
    assert body["knowledge_report_md"] == _REPORT

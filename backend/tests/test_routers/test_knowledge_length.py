"""S-1.15.3: a length preference for knowledge reports, at the production caller.

``POST /videos/{id}/extract-knowledge?output_length=brief|standard|deep``
applies D-064's multiplier to S-1.14.8's size-based synthesis budget and
gives the writer that depth's brief. The real agent runs here, through the
router; only the model client (`knowledge_agent.get_llm_for`) is faked, so
what the synthesis call was built with is the assertion.

Unset (or 'auto') must be today's call exactly: the same budget, and a prompt
that differs from a brief one only by the brief's paragraph.

Mutation checks, run by hand on 2026-11-04 (the first is also pinned by the
last test):
- the router calling the agent without the preference fails
  `test_a_preference_scales_the_synthesis_budget` (all three) and the
  large-extraction test;
- the agent ignoring the multiplier fails the same tests for brief and deep;
- the brief never reaching the prompt fails all three preference cases;
- bracketing one document (`resolve_scale(None, pref)`) fails
  `test_unset_is_the_call_s_1_14_8_shipped`: 1.25x, not 1.0.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents import knowledge_agent
from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import output_length, visibility_service

_FLOOR = 8_000  # S-1.14.8's minimum synthesis budget


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


class _Models:
    """Stands in for `get_llm_for`: records each call's kwargs and prompt."""

    def __init__(self, extraction: dict):
        self.extraction = extraction
        self.calls: list[tuple[str, dict, str]] = []

    def __call__(self, use_case: str, **kwargs):
        llm = MagicMock()

        def invoke(messages):
            self.calls.append((use_case, kwargs, messages[0].content))
            if use_case == "knowledge_extract_batch":
                return MagicMock(content=json.dumps(self.extraction))
            return MagicMock(content="# Tidal storage\n\n## Overview\n\nText.")

        llm.invoke.side_effect = invoke
        return llm

    def synthesis(self) -> tuple[dict, str]:
        (call,) = [(kw, prompt) for use_case, kw, prompt in self.calls if use_case == "knowledge_synthesize_report"]
        return call


def _extract(client, video, query: str = "", extraction: dict | None = None):
    models = _Models(extraction or _SMALL)
    with patch.object(knowledge_agent, "get_llm_for", side_effect=models):
        resp = client.post(f"/api/v1/videos/{video.video_id}/extract-knowledge{query}")
    return resp, models


def _merged_tokens(extraction: dict) -> int:
    """What S-1.14.8 sizes the budget from: the merged extraction's JSON."""
    merged = {k: extraction.get(k, []) for k in ("topics", "concepts", "events", "facts")}
    return knowledge_agent._count_tokens(json.dumps(merged, ensure_ascii=False, indent=2))


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
    [("brief", int(_FLOOR * 0.45)), ("standard", _FLOOR), ("deep", int(_FLOOR * 1.6))],
)
def test_a_preference_scales_the_synthesis_budget(client, video, db, pref, budget):
    resp, models = _extract(client, video, f"?output_length={pref}")
    assert resp.status_code == 200, resp.text
    kwargs, prompt = models.synthesis()
    assert kwargs["max_tokens"] == budget
    # The brief sits in its own paragraph before the closing instruction.
    assert f"cites.\n\n{output_length.override_guidance(pref)}\n\nReturn ONLY" in prompt
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
    big = {
        "topics": [f"topic {i} on tidal storage economics" for i in range(400)],
        "concepts": [],
        "events": [],
        "facts": [f"Fact {i}: lagoon {i} stores {i * 3} megawatt hours at night." for i in range(1200)],
    }
    base = _merged_tokens(big)
    assert _FLOOR < base < knowledge_agent.SYNTHESIS_EXTRACTION_JSON_MAX_TOKENS

    _, unset = _extract(client, video, extraction=big)
    _, deep = _extract(client, video, "?force=true&output_length=deep", extraction=big)
    _, brief = _extract(client, video, "?force=true&output_length=brief", extraction=big)
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


def test_mutation_a_router_that_drops_the_preference_is_caught(client, video, monkeypatch):
    """The wiring the tests above pin: when the router calls the agent
    without the preference (the code before S-1.15.3), a deep request gets
    the default budget and no brief, which
    `test_a_preference_scales_the_synthesis_budget` rejects."""
    real = knowledge_agent.run_knowledge_extract_agent
    monkeypatch.setattr(
        knowledge_agent, "run_knowledge_extract_agent", lambda doc, text, **_kw: real(doc, text)
    )
    resp, models = _extract(client, video, "?output_length=deep")
    assert resp.status_code == 200
    kwargs, prompt = models.synthesis()
    assert kwargs["max_tokens"] == _FLOOR != int(_FLOOR * 1.6)
    assert "LENGTH:" not in prompt

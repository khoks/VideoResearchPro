"""T-1.15.4.4: a brief answer keeps room for the model's thinking.

Every provider counts thinking inside `max_tokens`, and brief alone is
4,500 x 0.45 = 2,025. That is under the 4,096 a Claude model on legacy
thinking is budgeted at medium, which the API refuses, and on the default
`claude-sonnet-5:medium` nothing refuses it, so thinking spends the answer's
tokens. `_answer_policy` now applies D-125's rule: a budget the multiplier
shrinks keeps the thinking reserve on top of its scaled share, up to the
unscaled figure.

These run at the production callers: the job, library and shelf routes, the
real agents, and only retrieval and the model client (`qa_agent.get_llm_for`)
faked, so what the answer call was built with is the assertion.

Mutation checks, run by hand on 2026-11-04:
- dropping the reserve from `_answer_budget` fails the `brief` cases and
  `test_mutation_no_reserve_is_the_budget_legacy_claude_refuses`;
- dropping the cap at the unscaled figure fails
  `test_brief_never_asks_for_more_than_the_unscaled_figure`;
- applying the reserve to every depth fails `test_unset_is_byte_identical`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import llm_service, output_length, shelf_service, visibility_service
from app.services.llm_routing import UseCaseConfig
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

_BASE = 4_500
_BRIEF = int(_BASE * 0.45)
_SMALL_UNSET = int(_BASE * 1.25)  # one document is a `small` corpus
_DEFAULT = UseCaseConfig("anthropic", "claude-sonnet-5", "medium")  # the registry default
_PLAIN = UseCaseConfig("anthropic", "claude-sonnet-5", "off")
_TITLE = "Tidal energy storage"
_ANSWER = f'Lagoons store energy. [Source: "{_TITLE}" by Someone at 0:00]'

_ROUTES = ["job", "library", "shelf"]


@pytest.fixture
def corpus(db, test_user):
    doc = Document(
        video_id="budgetVid01",
        title=_TITLE,
        url="https://www.youtube.com/watch?v=budgetVid01",
        duration_seconds=60,
        transcript_status="fetched",
        transcript_word_count=500,
        created_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], test_user.id)
    job = Job(job_type="channel", topic="t", status="completed", num_videos=1, tenant_id=test_user.id)
    db.add(job)
    db.commit()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
    db.commit()
    shelf = shelf_service.create_shelf(db, test_user.id, "Storage")
    shelf_service.add_job(db, shelf, job)
    return {"doc": doc, "job": job, "shelf": shelf}


def _chunks(doc):
    """What retrieval returns for ``doc``, built the way ingest builds it."""
    meta = job_tasks._build_video_metadata(doc, "en")
    chunks = chunk_transcript(
        [{"text": "Tidal lagoons store energy behind a wall.", "start": 0.0, "duration": 5.0}],
        video_metadata=meta,
    )
    return [
        {"text": c["text"], "metadata": {k: v for k, v in c["metadata"].items() if v is not None}, "distance": 0.1}
        for c in chunks
    ]


class _Models:
    """Stands in for `get_llm_for`, recording how the answer call was built."""

    def __init__(self):
        self.answer_kwargs: dict | None = None
        self.answer_prompt = ""

    def __call__(self, use_case: str, **kwargs):
        is_answer = use_case.endswith("qa_formulate_answer")
        if is_answer:
            self.answer_kwargs = kwargs

        def invoke(messages):
            response = MagicMock()
            response.response_metadata = {}
            if is_answer:
                self.answer_prompt = messages[-1].content
                response.content = _ANSWER
            elif use_case == "qa_sub_query_expansion":
                response.content = ""
            elif use_case.endswith("refine_context"):
                response.content = "Tidal lagoons store energy."
            else:
                response.content = "[]"
            return response

        llm = MagicMock()
        llm.invoke.side_effect = invoke
        return llm


def _ask(client, corpus, route: str, config: UseCaseConfig = _DEFAULT, depth: str | None = None) -> _Models:
    path = {
        "job": f"/api/v1/jobs/{corpus['job'].id}/qa",
        "library": "/api/v1/library/qa",
        "shelf": f"/api/v1/shelves/{corpus['shelf'].id}/qa",
    }[route]
    body: dict = {"question": "How do lagoons store energy?"}
    if depth:
        body["output_length"] = depth
    models = _Models()
    with (
        patch.object(qa_agent.chroma_service, "query_collection", return_value=_chunks(corpus["doc"])),
        patch.object(qa_agent, "get_llm_for", side_effect=models),
        patch.object(qa_agent, "resolve_config", return_value=config),
        patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(path, json=body)
    assert resp.status_code == 200, resp.text
    assert models.answer_kwargs is not None, "the answer call never ran"
    return models


@pytest.mark.parametrize("route", _ROUTES)
def test_brief_keeps_the_thinking_reserve_on_the_default_model(client, corpus, route):
    """The reported defect: 2,025 with thinking counted inside it."""
    models = _ask(client, corpus, route, depth="brief")
    assert models.answer_kwargs["max_tokens"] == _BASE
    # The brief does the shortening (D-062), not the ceiling.
    assert output_length.guidance({}, "brief") in models.answer_prompt


@pytest.mark.parametrize("route", _ROUTES)
def test_brief_with_reasoning_off_is_the_multiplier_alone(client, corpus, route):
    models = _ask(client, corpus, route, config=_PLAIN, depth="brief")
    assert models.answer_kwargs["max_tokens"] == _BRIEF


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("reasoning", ["minimal", "low", "medium", "auto"])
def test_brief_clears_the_thinking_budget_on_legacy_claude(client, corpus, route, reasoning):
    """Claude models on the enabled+budget_tokens shape refuse a `max_tokens`
    at or below the budget, which is what 2,025 was at medium and above."""
    config = UseCaseConfig("anthropic", "claude-haiku-4-5", reasoning)
    thinking = llm_service._anthropic_reasoning_kwargs(reasoning, config.model)["thinking"]["budget_tokens"]
    models = _ask(client, corpus, route, config=config, depth="brief")
    assert models.answer_kwargs["max_tokens"] > thinking


@pytest.mark.parametrize("route", _ROUTES)
def test_brief_never_asks_for_more_than_the_unscaled_figure(client, corpus, route):
    """`high` thinks past 4,500 on its own: brief stops at the figure standard
    gets, it does not climb above it."""
    config = UseCaseConfig("anthropic", "claude-haiku-4-5", "high")
    models = _ask(client, corpus, route, config=config, depth="brief")
    assert models.answer_kwargs["max_tokens"] == _BASE


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("depth", [None, "auto"])
def test_unset_is_byte_identical(client, corpus, route, depth):
    """Unset keeps the bracket's figure, with reasoning on or off, and the
    prompt is the same one."""
    with_thinking = _ask(client, corpus, route, config=_DEFAULT, depth=depth)
    without = _ask(client, corpus, route, config=_PLAIN, depth=depth)
    assert with_thinking.answer_kwargs["max_tokens"] == without.answer_kwargs["max_tokens"] == _SMALL_UNSET
    assert with_thinking.answer_prompt == without.answer_prompt


@pytest.mark.parametrize(("depth", "budget"), [("standard", _BASE), ("deep", int(_BASE * 1.6))])
def test_only_brief_is_lifted(client, corpus, depth, budget):
    assert _ask(client, corpus, "library", depth=depth).answer_kwargs["max_tokens"] == budget


def test_unset_stays_at_the_figure_each_bracket_gave_it():
    for statistics, scale in (
        ({"video_count": 3}, 1.25),
        ({"video_count": 12}, 1.1),
        ({"video_count": 50}, 1.0),
        ({"video_count": 200}, 1.0),
    ):
        with patch.object(qa_agent, "resolve_config", return_value=_DEFAULT):
            max_tokens, _, _ = qa_agent._answer_policy(statistics, None, "qa_formulate_answer")
        assert max_tokens == int(_BASE * scale)


def test_mutation_no_reserve_is_the_budget_legacy_claude_refuses(monkeypatch):
    """The mutant: the budget as it was, the multiplier alone. The figure the
    legacy-Claude assertion above rules out comes back."""
    monkeypatch.setattr(qa_agent, "thinking_reserve_tokens", lambda _cfg: 0)
    with patch.object(qa_agent, "resolve_config", return_value=_DEFAULT):
        max_tokens, _, _ = qa_agent._answer_policy({}, "brief", "qa_formulate_answer")
    assert max_tokens == _BRIEF
    thinking = llm_service._anthropic_reasoning_kwargs("medium", "claude-haiku-4-5")["thinking"]["budget_tokens"]
    assert max_tokens < thinking

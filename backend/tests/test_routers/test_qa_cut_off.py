"""T-1.15.4.5, T-1.15.4.8, T-1.15.4.9: a cut answer is noticed and stays noted,
at the production callers.

`formulate_answer` and the library path did not read the finish reason, so an
answer that stopped at its token budget was stored silently. Now it is logged
(use case and model, never the text) and the fresh response says so, on job,
stream, library and shelf answers. The budget itself is untouched: that is
OQ-29, the owner's.

The real routes and agents run. Only retrieval and the model client are faked,
and the fake reports each provider's stop in the shape its SDK really uses
(`test_llm_service_length_stops.py` pins those shapes against the SDKs).

`answer_cut_off` is stored on each exchange table, NULL on a row from before the
column. The history routes carry it only when it is true, so a finished answer's
history JSON is what it was and a stored row never reads as "not cut".

Mutation checks, run by hand on 2026-11-05 (T-1.15.4.8, T-1.15.4.9):
- any of the three writers not storing the flag fails
  `test_a_cut_answer_still_says_so_on_a_fresh_load_of_the_history` or
  `test_a_cut_history_answer_is_stored_and_says_so_on_a_fresh_load`;
- any history route not passing the stored value fails the same tests;
- dropping `exclude_if` fails `test_a_finished_answers_history_is_what_it_was`
  and `test_a_row_from_before_the_column_claims_nothing`;
- `QAAnswerResponse` keeping the base field fails `test_a_finished_answer_does_not`;
- `_formulate_answer` in the history agent not reading the response fails
  `test_a_cut_history_answer_is_stored_and_says_so_on_a_fresh_load`.

Mutation checks, run by hand on 2026-11-04:
- `answer_cut_off` returning False without reading the response fails
  `test_a_cut_answer_says_so_for_every_provider` and the logging test;
- removing the `logger.warning` fails `test_a_cut_answer_is_logged_without_its_text`;
- logging the answer in the warning fails the same test;
- the job route dropping `usage_out["answer_cut_off"]` fails the job and stream
  cases, and `library_qa_service.ask` dropping the flag fails library and shelf;
- `stopped_for_length` no longer reading `incomplete_details` fails the
  `openai-responses` cases.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent, qa_history_agent
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.models.saved_search_run import SavedSearchRun
from app.services import saved_search_service, shelf_service, visibility_service
from app.services.llm_routing import UseCaseConfig
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

_CONFIG = UseCaseConfig("anthropic", "claude-sonnet-5", "medium")
_TITLE = "Tidal energy storage"
_ANSWER = f'Lagoons store energy, and SECRET-SENTENCE [Source: "{_TITLE}" by Someone at 0:00]'

_ROUTES = ["job", "stream", "library", "shelf"]

# A stop at the budget, in each provider's own words.
_CUT = {
    "anthropic": {"stop_reason": "max_tokens"},
    "openai": {"finish_reason": "length"},
    "google": {"finish_reason": "MAX_TOKENS"},
    "local": {"finish_reason": "length"},
    "openai-responses": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
}
# A finished answer, likewise.
_DONE = {
    "anthropic": {"stop_reason": "end_turn"},
    "openai": {"finish_reason": "stop"},
    "google": {"finish_reason": "STOP"},
    "openai-responses": {"status": "completed"},
}


@pytest.fixture
def corpus(db, test_user):
    doc = Document(
        video_id="cutOffVid01",
        title=_TITLE,
        url="https://www.youtube.com/watch?v=cutOffVid01",
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


def _models(stop: dict):
    """Stands in for `get_llm_for`. Only the answer call reports `stop`."""

    def build(use_case: str, **_kwargs):
        def invoke(_messages):
            response = MagicMock()
            response.response_metadata = {}
            if use_case.endswith("qa_formulate_answer"):
                response.content = _ANSWER
                response.response_metadata = dict(stop)
            elif use_case.endswith("refine_context"):
                response.content = "Tidal lagoons store energy."
            elif use_case == "qa_sub_query_expansion":
                response.content = ""
            else:
                response.content = "[]"
            return response

        llm = MagicMock()
        llm.invoke.side_effect = invoke
        return llm

    return build


def _ask(client, corpus, route: str, stop: dict) -> tuple[dict, MagicMock]:
    path = {
        "job": f"/api/v1/jobs/{corpus['job'].id}/qa",
        "stream": f"/api/v1/jobs/{corpus['job'].id}/qa/stream",
        "library": "/api/v1/library/qa",
        "shelf": f"/api/v1/shelves/{corpus['shelf'].id}/qa",
    }[route]
    with (
        patch.object(qa_agent.chroma_service, "query_collection", return_value=_chunks(corpus["doc"])),
        patch.object(qa_agent, "get_llm_for", side_effect=_models(stop)),
        patch.object(qa_agent, "resolve_config", return_value=_CONFIG),
        patch.object(qa_agent, "logger") as log,
        patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(path, json={"question": "How do lagoons store energy?"})
    assert resp.status_code == 200, resp.text
    if route != "stream":
        return resp.json(), log
    frames = [
        json.loads(line[len("data:"):])
        for line in resp.text.splitlines()
        if line.startswith("data:") and "[DONE]" not in line
    ]
    (complete,) = [f for f in frames if f.get("type") == "complete"]
    return complete["exchange"], log


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("provider", list(_CUT))
def test_a_cut_answer_says_so_for_every_provider(client, corpus, route, provider):
    body, _ = _ask(client, corpus, route, _CUT[provider])
    assert body["answer_cut_off"] is True


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("provider", list(_DONE))
def test_a_finished_answer_does_not(client, corpus, route, provider):
    body, log = _ask(client, corpus, route, _DONE[provider])
    assert body["answer_cut_off"] is False
    log.warning.assert_not_called()


@pytest.mark.parametrize("route", _ROUTES)
def test_no_metadata_at_all_reads_as_finished(client, corpus, route):
    """A local server may report nothing. No finish reason is no claim."""
    body, log = _ask(client, corpus, route, {})
    assert body["answer_cut_off"] is False
    log.warning.assert_not_called()


@pytest.mark.parametrize(
    "route, use_case",
    [
        ("job", "qa_formulate_answer"),
        ("stream", "qa_formulate_answer"),
        ("library", "library_qa_formulate_answer"),
        ("shelf", "library_qa_formulate_answer"),
    ],
)
def test_a_cut_answer_is_logged_without_its_text(client, corpus, route, use_case):
    _, log = _ask(client, corpus, route, _CUT["anthropic"])
    log.warning.assert_called_once()
    args = log.warning.call_args.args
    rendered = args[0] % args[1:]
    assert use_case in rendered
    assert _CONFIG.model in rendered
    assert "SECRET-SENTENCE" not in rendered
    assert "lagoons" not in rendered.lower()


@pytest.mark.parametrize("route", _ROUTES)
def test_a_cut_answer_is_still_stored_and_returned(client, corpus, route, db):
    """Reporting a cut must not lose what was written."""
    body, _ = _ask(client, corpus, route, _CUT["openai"])
    assert "SECRET-SENTENCE" in body["answer"]
    db.expire_all()
    model = QAExchange if route in ("job", "stream") else LibraryQAExchange
    assert "SECRET-SENTENCE" in db.get(model, body["id"]).answer


def _history(client, corpus, route: str) -> list[dict]:
    """A fresh load of the history that route's answers land in."""
    path = {
        "job": f"/api/v1/jobs/{corpus['job'].id}/qa",
        "stream": f"/api/v1/jobs/{corpus['job'].id}/qa",
        "library": "/api/v1/library/qa",
        "shelf": f"/api/v1/shelves/{corpus['shelf'].id}/qa",
    }[route]
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("provider", list(_CUT))
def test_a_cut_answer_still_says_so_on_a_fresh_load_of_the_history(client, corpus, route, provider, db):
    """T-1.15.4.8: the round trip. The ask is over, and only the row is left."""
    asked, _ = _ask(client, corpus, route, _CUT[provider])
    db.expire_all()
    (row,) = _history(client, corpus, route)
    assert row["id"] == asked["id"]
    assert row["answer_cut_off"] is True


def test_a_shelf_answer_says_so_on_the_library_history_too(client, corpus):
    """A shelf's exchange joins the library history, and is read from the same row."""
    _ask(client, corpus, "shelf", _CUT["anthropic"])
    (row,) = _history(client, corpus, "library")
    assert row["answer_cut_off"] is True


@pytest.mark.parametrize("route", _ROUTES)
def test_a_finished_answers_history_is_what_it_was(client, corpus, route, db):
    """D-145: an uncut answer's response stays byte-identical, on both routes."""
    asked, _ = _ask(client, corpus, route, _DONE["anthropic"])
    assert asked.pop("answer_cut_off") is False, "the fresh reply keeps saying false, as #419 shipped"
    (row,) = _history(client, corpus, route)
    assert row == asked, "the history row is the fresh reply without the flag"
    expected = {"id", "question", "answer", "references", "created_at"}
    if route in ("library", "shelf"):
        expected |= {"answer_language", "scope"}
    assert set(row) == expected

    db.expire_all()
    model = QAExchange if route in ("job", "stream") else LibraryQAExchange
    assert db.get(model, row["id"]).answer_cut_off is False, "the check ran, and that is stored"


@pytest.mark.parametrize("route", _ROUTES)
def test_a_provider_that_reports_nothing_is_not_a_cut(client, corpus, route):
    asked, _ = _ask(client, corpus, route, {})
    (row,) = _history(client, corpus, route)
    assert row["id"] == asked["id"]
    assert "answer_cut_off" not in row


def test_a_row_from_before_the_column_claims_nothing(client, corpus, db, test_user):
    """No backfill: NULL is unknown, so it reads as neither cut nor not cut."""
    job = corpus["job"]
    db.add_all(
        [
            QAExchange(job_id=job.id, question="q", answer="a", tenant_id=test_user.id),
            LibraryQAExchange(question="q", answer="a", tenant_id=test_user.id),
            QAHistoryExchange(question="q", answer="a", tenant_id=test_user.id),
        ]
    )
    db.commit()
    assert db.query(QAExchange).one().answer_cut_off is None

    (job_row,) = client.get(f"/api/v1/jobs/{job.id}/qa").json()
    (library_row,) = client.get("/api/v1/library/qa").json()
    (history_row,) = client.get("/api/v1/qa-history/exchanges").json()
    for row in (job_row, library_row, history_row):
        assert "answer_cut_off" not in row


def _past_exchange() -> dict:
    return {
        "text": "Q: How do lagoons store energy?\n\nA: Behind a wall.",
        "metadata": {"source": "job", "exchange_id": "ex-1", "job_id": "job-1", "created_at_iso": "2026-04-01"},
        "distance": 0.1,
    }


def _history_models(stop: dict):
    """Stands in for `get_llm_for` in the history agent."""

    def build(use_case: str, **_kwargs):
        response = MagicMock()
        response.response_metadata = {}
        if use_case == "qa_history_formulate_answer":
            response.content = "You asked about lagoons, and SECRET-SENTENCE"
            response.response_metadata = dict(stop)
        else:
            response.content = "You asked about lagoons."
        llm = MagicMock()
        llm.invoke.return_value = response
        return llm

    return build


def _ask_history(client, stop: dict, *, retrieved: list[dict]) -> tuple[dict, MagicMock]:
    with (
        patch.object(qa_history_agent.chroma_service, "query_qa_collection", return_value=retrieved),
        patch.object(qa_history_agent, "get_llm_for", side_effect=_history_models(stop)),
        patch.object(qa_agent, "resolve_config", return_value=_CONFIG),
        patch.object(qa_agent, "logger") as log,
        patch("app.routers.qa_history.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post("/api/v1/qa-history/chat", json={"question": "What did I ask about lagoons?"})
    assert resp.status_code == 200, resp.text
    return resp.json(), log


@pytest.mark.parametrize("retrieved", [[_past_exchange()], []], ids=["past-exchanges", "nothing-retrieved"])
@pytest.mark.parametrize("provider", list(_CUT))
def test_a_cut_history_answer_is_stored_and_says_so_on_a_fresh_load(client, db, provider, retrieved):
    """T-1.15.4.9: Q&A-history answers are checked the same way."""
    body, _ = _ask_history(client, _CUT[provider], retrieved=retrieved)
    assert body["answer_cut_off"] is True
    assert "SECRET-SENTENCE" in body["answer"]

    db.expire_all()
    assert db.get(QAHistoryExchange, body["id"]).answer_cut_off is True
    (row,) = client.get("/api/v1/qa-history/exchanges").json()
    assert row["id"] == body["id"]
    assert row["answer_cut_off"] is True


def test_a_cut_history_answer_is_logged_without_its_text(client):
    _, log = _ask_history(client, _CUT["anthropic"], retrieved=[_past_exchange()])
    log.warning.assert_called_once()
    args = log.warning.call_args.args
    rendered = args[0] % args[1:]
    assert "qa_history_formulate_answer" in rendered
    assert _CONFIG.model in rendered
    assert "SECRET-SENTENCE" not in rendered


@pytest.mark.parametrize("stop", [_DONE["anthropic"], {}], ids=["finished", "no-metadata"])
def test_a_finished_history_answers_response_is_what_it_was(client, db, stop):
    """No key at all, on the reply and on the list, as before the check existed."""
    body, log = _ask_history(client, stop, retrieved=[_past_exchange()])
    log.warning.assert_not_called()
    expected = {"id", "question", "answer", "references", "answer_language", "created_at"}
    assert set(body) == expected
    (row,) = client.get("/api/v1/qa-history/exchanges").json()
    assert row == body

    db.expire_all()
    assert db.get(QAHistoryExchange, body["id"]).answer_cut_off is False


def test_a_real_cut_reaches_a_saved_searchs_run(client, corpus, db, test_user):
    """T-1.15.4.9: the real library agent, through the real run, to the history."""
    test_user.tier = "pro"
    db.commit()
    ss = saved_search_service.create(
        db,
        test_user,
        question="How do lagoons store energy?",
        cadence={"cadence": "weekly", "hour": 9, "weekday": 0, "timezone": "UTC"},
    )
    with (
        patch.object(qa_agent.chroma_service, "query_collection", return_value=_chunks(corpus["doc"])),
        patch.object(qa_agent, "get_llm_for", side_effect=_models(_CUT["anthropic"])),
        patch.object(qa_agent, "resolve_config", return_value=_CONFIG),
        patch("app.services.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        outcome = saved_search_service.execute(db, ss.id, trigger="manual")
    assert outcome["status"] == "ok"

    (run,) = db.query(SavedSearchRun).filter_by(saved_search_id=ss.id).all()
    assert run.decided_by == "cut_off"
    assert db.get(LibraryQAExchange, run.exchange_id).answer_cut_off is True
    (row,) = _history(client, corpus, "library")
    assert row["answer_cut_off"] is True
    (listed,) = client.get(f"/api/v1/saved-searches/{ss.id}/runs").json()
    assert listed["decided_by"] == "cut_off"
    assert listed["changed"] is None


@pytest.mark.parametrize("route", ["library", "shelf"])
def test_a_library_answer_keeps_every_field_it_had(client, corpus, route):
    """The fresh response is the stored one plus the flag."""
    body, _ = _ask(client, corpus, route, _DONE["anthropic"])
    assert body["answer_language"] == "en"
    assert body["references"], "the citation was lost on the way out"
    assert body["references"][0]["video_title"] == _TITLE
    expected_scope = {"shelf_id": corpus["shelf"].id} if route == "shelf" else None
    scope = body["scope"]
    assert ({k: v for k, v in scope.items() if v} if scope else None) == expected_scope

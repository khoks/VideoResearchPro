"""Tests for the Q&A history chat agent (Unit 2 — Personal Wiki).

Mocks out ``chroma_service.query_qa_collection`` (added by Unit 1) and
``get_llm_for`` so we can verify:
  * the agent calls the Q&A collection API (not the transcript-chunk API),
  * it returns a shaped answer + reference list,
  * reference fields match the planned shape
    ``{source_type, exchange_id, question_preview, job_id, original_created_at}``,
  * the zero-retrieval branch still returns a well-formed response.

``run_qa_history_chat_agent`` is ``async`` so we drive it with ``asyncio.run``
rather than adding a project-wide dependency on ``pytest-asyncio``'s auto mode.
"""

import asyncio
from unittest.mock import MagicMock, patch

from app.agents import qa_history_agent


def _fake_llm(payload: str) -> MagicMock:
    response = MagicMock()
    response.content = payload
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


def _qa_chunk(
    exchange_id: str,
    question: str,
    answer: str,
    source: str = "job",
    job_id: str | None = "job-abc",
    created_at: str = "2026-04-01T00:00:00+00:00",
    distance: float = 0.1,
) -> dict:
    """Build a raw chunk the way Unit 1 will return it from the Q&A collection."""
    return {
        "text": f"Q: {question}\n\nA: {answer}",
        "metadata": {
            "source": source,
            "exchange_id": exchange_id,
            "job_id": job_id,
            "created_at_iso": created_at,
        },
        "distance": distance,
    }


def _run(question: str, answer_language: str = "en") -> dict:
    return asyncio.run(
        qa_history_agent.run_qa_history_chat_agent(
            question=question, answer_language=answer_language
        )
    )


def test_qa_history_agent_returns_answer_and_shaped_references():
    """Happy path: retrieve two past exchanges, refine, synthesize, cite both."""
    chunks = [
        _qa_chunk(
            exchange_id="ex-1",
            question="What are the health risks of tariffs?",
            answer="Tariffs can raise prices on medical imports.",
            source="job",
            job_id="job-abc",
        ),
        _qa_chunk(
            exchange_id="ex-2",
            question="Have I looked into WTO rulings?",
            answer="Yes, there were two WTO disputes in 2024.",
            source="library",
            job_id=None,
            distance=0.2,
        ),
    ]

    # get_llm_for is called twice: refine_context, formulate_answer.
    fake_llms = [
        _fake_llm("refined excerpt mentioning ex-1 and ex-2"),
        _fake_llm(
            "You have asked about tariffs [Source: exchange ex-1 | "
            "\"What are the health risks of tariffs?\"] and WTO rulings "
            "[Source: exchange ex-2 | \"Have I looked into WTO rulings?\"]."
        ),
    ]

    with patch.object(
        qa_history_agent.chroma_service,
        "query_qa_collection",
        create=True,
        return_value=chunks,
    ) as mock_q, patch.object(
        qa_history_agent, "get_llm_for", side_effect=fake_llms
    ):
        result = _run("what have I learned about tariffs")

    # Chroma was queried via the Q&A collection API, not the transcript API.
    assert mock_q.called
    first_call = mock_q.call_args_list[0]
    assert first_call.args[0] == "what have I learned about tariffs"
    # The agent must pass the retrieval count using the real service kwarg.
    # Using ``n_results`` would be silently swallowed by the try/except in
    # _retrieve_past_exchanges and return [].
    assert "top_k" in first_call.kwargs

    answer = result["answer"]
    refs = result["references"]

    assert "tariffs" in answer.lower()
    assert len(refs) == 2

    # Shape assertions: every reference must have the planned fields.
    for r in refs:
        assert set(r.keys()) >= {
            "source_type",
            "exchange_id",
            "question_preview",
            "job_id",
            "original_created_at",
        }

    by_id = {r["exchange_id"]: r for r in refs}
    assert by_id["ex-1"]["source_type"] == "job"
    assert by_id["ex-1"]["job_id"] == "job-abc"
    assert "tariffs" in by_id["ex-1"]["question_preview"].lower()
    assert by_id["ex-2"]["source_type"] == "library"
    assert by_id["ex-2"]["job_id"] is None


def test_qa_history_agent_handles_empty_retrieval():
    """No past exchanges retrieved -> still return a well-formed response with empty refs."""
    with patch.object(
        qa_history_agent.chroma_service,
        "query_qa_collection",
        create=True,
        return_value=[],
    ), patch.object(
        qa_history_agent,
        "get_llm_for",
        side_effect=[_fake_llm("I could not find anything in your Q&A history about this.")],
    ):
        result = _run("what have I asked about bicycles")

    assert result["references"] == []
    assert isinstance(result["answer"], str)
    assert result["answer"]


def test_qa_history_agent_survives_missing_chroma_api():
    """If Unit 1 isn't landed yet (no ``query_qa_collection``), the agent
    must not crash — just return empty references."""
    def _raise_attribute_error(*_a, **_kw):
        raise AttributeError("query_qa_collection")

    with patch.object(
        qa_history_agent.chroma_service,
        "query_qa_collection",
        create=True,
        side_effect=_raise_attribute_error,
    ), patch.object(
        qa_history_agent,
        "get_llm_for",
        side_effect=[_fake_llm("nothing to cite")],
    ):
        result = _run("meta question")

    assert result["references"] == []
    assert isinstance(result["answer"], str)


def test_qa_history_agent_respects_answer_language():
    """The answer_language parameter threads through to the LLM prompts."""
    chunks = [_qa_chunk("ex-xyz", "q?", "a.", source="history", job_id=None)]

    fake_llms = [
        _fake_llm("refined"),
        _fake_llm("Spanish answer"),
    ]
    with patch.object(
        qa_history_agent.chroma_service,
        "query_qa_collection",
        create=True,
        return_value=chunks,
    ), patch.object(
        qa_history_agent, "get_llm_for", side_effect=fake_llms
    ) as mock_get_llm_for:
        _run("que he aprendido", answer_language="es")

    assert mock_get_llm_for.call_count == 2
    # The formulate_answer LLM was given messages mentioning the iso code.
    invocations = fake_llms[1].invoke.call_args_list
    assert invocations, "formulate_answer must call llm.invoke"
    messages = invocations[0].args[0]
    joined = " ".join(getattr(m, "content", "") for m in messages)
    assert "es" in joined

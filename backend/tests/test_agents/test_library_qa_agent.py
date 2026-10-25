"""Tests for the library-wide Q&A agent (Unit 6).

The library Q&A agent searches the global ChromaDB collection (no video_ids
filter) and returns a grounded answer with citations. It is distinct from
the per-job Q&A agent, which restricts retrieval to a single job's videos.
"""
from unittest.mock import MagicMock, patch

import pytest

# Unit 6: `run_library_qa_agent` lives alongside `run_qa_agent` in qa_agent.py.
qa_agent_module = pytest.importorskip("app.agents.qa_agent")
if not hasattr(qa_agent_module, "run_library_qa_agent"):
    pytest.skip(
        "run_library_qa_agent not yet merged (pending Unit 6)",
        allow_module_level=True,
    )

from app.agents import qa_agent  # noqa: E402


def _fake_llm(payload: str) -> MagicMock:
    response = MagicMock()
    response.content = payload
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


def _rag_chunk(video_id: str, title: str, channel: str, ts: float = 0.0) -> dict:
    return {
        "text": f"DNS resolves domain names to IP addresses. {title} explains this.",
        "metadata": {
            "video_id": video_id,
            "video_title": title,
            "channel_name": channel,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "timestamp_start": ts,
        },
        "distance": 0.1,
    }


def test_library_qa_runs_end_to_end_with_citations():
    """run_library_qa_agent called without a scope passes document_ids=None
    (unrestricted; internal use only) and returns an answer plus structured
    references."""
    rag = [
        _rag_chunk("vDNS", "How DNS Works", "NetTeach", ts=30.0),
        _rag_chunk("vNet", "Intro to Networking", "NetTeach", ts=60.0),
    ]

    # get_llm_for is invoked in this order inside the agent:
    #   sub-query expansion -> refine_context -> formulate_answer
    # extract_references uses deterministic matching when the answer contains
    # video_ids/titles, so typically no extra LLM call is needed.
    fake_llms = [
        _fake_llm(""),  # sub-queries: none
        _fake_llm("DNS maps names to IPs."),  # refine_context
        _fake_llm(
            'Based on "How DNS Works" by NetTeach: '
            'DNS resolves names to IPs. [Source: "How DNS Works" by NetTeach at 0:30]'
        ),  # formulate_answer
    ]
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=rag) as mock_q, \
         patch.object(qa_agent, "get_llm_for", side_effect=fake_llms):
        result = qa_agent.run_library_qa_agent(question="What is DNS?")

    answer = result["answer"]
    references = result["references"]

    # Assert query_collection was called with document_ids=None (global search).
    assert mock_q.call_count >= 1
    first_call = mock_q.call_args_list[0]
    assert "document_ids" in first_call.kwargs, (
        "run_library_qa_agent must pass document_ids as a keyword arg to "
        f"query_collection; got args={first_call.args} kwargs={first_call.kwargs}"
    )
    assert first_call.kwargs["document_ids"] is None

    # Answer preserved; reference extracted for the cited video.
    assert "DNS" in answer
    assert len(references) >= 1
    vid_refs = {r["video_url"].rsplit("=", 1)[-1] for r in references}
    assert "vDNS" in vid_refs


def _prompt_text(llm: MagicMock) -> str:
    messages = llm.invoke.call_args.args[0]
    return "\n".join(m.content for m in messages)


def test_library_qa_clarify_answers_reach_every_prompt():
    """S-8.13.1 / T-8.13.1.3: a question carrying the reader's clarify answers,
    as ``answer_library_question`` builds it, reaches sub-query expansion,
    the refine prompt and the answer prompt."""
    from app.agents.prompts.qa_prompts import with_clarification

    question = with_clarification(
        "What is DNS?",
        "My interpretation: A DNS primer.\n\nWhich record types?\nMX and CNAME",
    )
    fake_llms = [
        _fake_llm(""),  # sub-queries
        _fake_llm("DNS maps names to IPs."),  # refine_context
        _fake_llm(
            'DNS resolves names to IPs. [Source: "How DNS Works" by NetTeach at 0:30]'
        ),  # formulate_answer
    ]
    with patch.object(
        qa_agent.chroma_service,
        "query_collection",
        return_value=[_rag_chunk("vDNS", "How DNS Works", "NetTeach", ts=30.0)],
    ), patch.object(qa_agent, "get_llm_for", side_effect=fake_llms):
        qa_agent.run_library_qa_agent(question=question, visible_document_ids=["d-dns"])

    sub_queries, refine, answer = (_prompt_text(llm) for llm in fake_llms)
    for stage, prompt in (("sub-query", sub_queries), ("refine", refine), ("answer", answer)):
        assert "MX and CNAME" in prompt, f"the {stage} prompt lost the reader's clarify answer"
        assert "My interpretation: A DNS primer." in prompt, stage


def test_with_clarification_leaves_a_bare_question_alone():
    from app.agents.prompts.qa_prompts import with_clarification

    assert with_clarification("What is DNS?", None) == "What is DNS?"
    assert with_clarification("What is DNS?", "") == "What is DNS?"
    assert with_clarification("What is DNS?", " \n\t") == "What is DNS?"
    assert with_clarification("What is DNS?", "  MX  \n") == (
        "What is DNS?\n\nAdditional context from user:\nMX"
    )


def test_library_qa_returns_empty_references_when_rag_empty():
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]), \
         patch.object(qa_agent, "get_llm_for", side_effect=[
             _fake_llm(""),                   # sub-queries
             _fake_llm("nothing relevant"),   # refine_context
             _fake_llm("I don't know."),      # formulate_answer
         ]):
        result = qa_agent.run_library_qa_agent(question="What is DNS?")

    assert result["references"] == []
    assert isinstance(result["answer"], str)

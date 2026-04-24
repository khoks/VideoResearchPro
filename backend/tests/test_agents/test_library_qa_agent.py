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
    """run_library_qa_agent should call query_collection with video_ids=None
    and return an answer plus structured references."""
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

    # Assert query_collection was called with video_ids=None (global search).
    assert mock_q.call_count >= 1
    first_call = mock_q.call_args_list[0]
    assert "video_ids" in first_call.kwargs, (
        "run_library_qa_agent must pass video_ids as a keyword arg to "
        f"query_collection; got args={first_call.args} kwargs={first_call.kwargs}"
    )
    assert first_call.kwargs["video_ids"] is None

    # Answer preserved; reference extracted for the cited video.
    assert "DNS" in answer
    assert len(references) >= 1
    vid_refs = {r["video_url"].rsplit("=", 1)[-1] for r in references}
    assert "vDNS" in vid_refs


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

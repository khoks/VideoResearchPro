"""Token accounting + progress callback tests for run_qa_agent.

Verifies usage accumulation across the pipeline's LLM calls
(sub-query expansion -> refine_context -> formulate_answer), the
honestly-NULL semantics when no provider reports usage, the
response_metadata["token_usage"] fallback, and the stage callback order.
"""
from unittest.mock import MagicMock, patch

from app.agents import qa_agent


class _FakeResponse:
    def __init__(self, content, usage=None, response_metadata=None):
        self.content = content
        self.usage_metadata = usage
        self.response_metadata = response_metadata or {}


def _fake_llm(content, usage=None, response_metadata=None):
    llm = MagicMock()
    llm.invoke.return_value = _FakeResponse(
        content, usage=usage, response_metadata=response_metadata
    )
    return llm


def _rag_result():
    return {
        "text": "some transcript text",
        "metadata": {
            "video_id": "v1",
            "video_title": "Video A",
            "channel_name": "ChA",
            "video_url": "https://www.youtube.com/watch?v=v1",
            "timestamp_start": 42.0,
        },
        "distance": 0.1,
    }


def _run(fake_llms, progress_callback=None, usage_out=None):
    with patch.object(
        qa_agent.chroma_service, "query_collection", return_value=[_rag_result()]
    ), patch.object(qa_agent, "get_llm_for", side_effect=fake_llms):
        return qa_agent.run_qa_agent(
            job_id="job-1",
            job_type="topic",
            question="tell me",
            video_ids=["v1"],
            report_html=None,
            progress_callback=progress_callback,
            usage_out=usage_out,
        )


def test_usage_accumulates_across_all_llm_calls():
    fake_llms = [
        _fake_llm("", usage={"input_tokens": 10, "output_tokens": 5}),
        _fake_llm("compacted", usage={"input_tokens": 100, "output_tokens": 20}),
        _fake_llm(
            "Answer referencing v1 / Video A",
            usage={"input_tokens": 200, "output_tokens": 50},
        ),
    ]
    usage: dict = {}
    answer, references = _run(fake_llms, usage_out=usage)

    assert answer == "Answer referencing v1 / Video A"
    assert len(references) == 1
    assert usage == {"prompt_tokens": 310, "completion_tokens": 75}


def test_usage_stays_none_when_no_call_reports_metadata():
    fake_llms = [
        _fake_llm(""),
        _fake_llm("compacted"),
        _fake_llm("Answer referencing v1 / Video A"),
    ]
    usage: dict = {}
    _run(fake_llms, usage_out=usage)

    assert usage == {"prompt_tokens": None, "completion_tokens": None}


def test_partial_usage_treats_missing_calls_as_zero():
    fake_llms = [
        _fake_llm(""),  # no usage (e.g. local model)
        _fake_llm("compacted", usage={"input_tokens": 100, "output_tokens": 20}),
        _fake_llm("Answer referencing v1 / Video A"),
    ]
    usage: dict = {}
    _run(fake_llms, usage_out=usage)

    assert usage == {"prompt_tokens": 100, "completion_tokens": 20}


def test_response_metadata_token_usage_fallback():
    fake_llms = [
        _fake_llm(""),
        _fake_llm(
            "compacted",
            response_metadata={
                "token_usage": {"prompt_tokens": 40, "completion_tokens": 8}
            },
        ),
        _fake_llm(
            "Answer referencing v1 / Video A",
            response_metadata={
                "token_usage": {"prompt_tokens": 60, "completion_tokens": 12}
            },
        ),
    ]
    usage: dict = {}
    _run(fake_llms, usage_out=usage)

    assert usage == {"prompt_tokens": 100, "completion_tokens": 20}


def test_progress_callback_receives_stages_in_order():
    fake_llms = [
        _fake_llm(""),
        _fake_llm("compacted"),
        _fake_llm("Answer referencing v1 / Video A"),
    ]
    stages: list[str] = []
    _run(fake_llms, progress_callback=stages.append)

    assert stages == ["retrieving", "refining", "formulating", "extracting_references"]


def test_progress_callback_errors_do_not_break_the_agent():
    fake_llms = [
        _fake_llm(""),
        _fake_llm("compacted"),
        _fake_llm("Answer referencing v1 / Video A"),
    ]

    def exploding_callback(stage: str) -> None:
        raise RuntimeError("boom")

    answer, references = _run(fake_llms, progress_callback=exploding_callback)

    assert answer == "Answer referencing v1 / Video A"
    assert len(references) == 1

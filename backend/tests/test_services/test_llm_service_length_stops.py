"""`stopped_for_length` against what each SDK really produces (T-1.15.4.5).

The first three are the shapes `report_agent` and `knowledge_agent` already
relied on. The fourth was missed: langchain sends its responses-only models
(`gpt-5-pro`, `gpt-5.2-pro`, `gpt-5.4-pro`, anything with `codex`) through
OpenAI's Responses API, which has no `finish_reason`, and `_LENGTH_STOPS` named
its `max_output_tokens` without anything reading it.

These build each SDK's own response object and run the langchain wrapper's own
conversion, offline, so an SDK that renames a field fails here rather than
silently ending the warning.

Mutation check, run by hand on 2026-11-04: dropping the `incomplete_details`
read from `stopped_for_length` fails `test_openai_responses_api`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm_service import stopped_for_length


def _as_invoke_returns(result):
    """`BaseChatModel` folds `llm_output` and `generation_info` into the
    message's metadata before `invoke` returns it."""
    generation = result.generations[0]
    message = generation.message
    message.response_metadata = {
        **(result.llm_output or {}),
        **(generation.generation_info or {}),
        **message.response_metadata,
    }
    return message


def _anthropic(stop_reason: str):
    # An optional install (`_build_anthropic`), not in requirements.txt, so CI
    # skips this one. `test_qa_cut_off.py` keeps the shape covered there.
    pytest.importorskip("anthropic")
    pytest.importorskip("langchain_anthropic")
    from anthropic.types import Message, TextBlock, Usage
    from langchain_anthropic import ChatAnthropic

    message = Message(
        id="m",
        content=[TextBlock(text="cut", type="text", citations=None)],
        model="claude-sonnet-5",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    client = ChatAnthropic(model="claude-sonnet-5", api_key="not-a-key", max_tokens=10)
    return _as_invoke_returns(client._format_output(message))


def _openai_chat(finish_reason: str):
    from langchain_openai import ChatOpenAI
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.completion_usage import CompletionUsage

    completion = ChatCompletion(
        id="c",
        choices=[
            Choice(
                finish_reason=finish_reason,
                index=0,
                message=ChatCompletionMessage(content="cut", role="assistant"),
            )
        ],
        created=0,
        model="gpt-5.5",
        object="chat.completion",
        usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
    )
    client = ChatOpenAI(model="gpt-5.5", api_key="not-a-key", max_tokens=10)
    return _as_invoke_returns(client._create_chat_result(completion))


def _openai_responses(status: str, reason: str | None):
    from langchain_openai.chat_models.base import _construct_lc_result_from_responses_api
    from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText
    from openai.types.responses.response import IncompleteDetails

    response = Response(
        id="r",
        created_at=0,
        model="gpt-5.4-pro",
        object="response",
        output=[
            ResponseOutputMessage(
                id="o",
                content=[ResponseOutputText(annotations=[], text="cut", type="output_text")],
                role="assistant",
                status="incomplete",
                type="message",
            )
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        status=status,
        incomplete_details=IncompleteDetails(reason=reason) if reason else None,
    )
    return _as_invoke_returns(_construct_lc_result_from_responses_api(response))


def _google(finish_reason: str):
    from google.genai import types
    from langchain_google_genai.chat_models import _response_to_result

    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text="cut")]),
                finish_reason=types.FinishReason[finish_reason],
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1, candidates_token_count=1, total_token_count=2
        ),
        model_version="gemini-3.5-flash",
    )
    return _as_invoke_returns(_response_to_result(response))


def test_anthropic():
    assert stopped_for_length(_anthropic("max_tokens"))
    assert not stopped_for_length(_anthropic("end_turn"))


def test_openai_chat_completions_and_local_servers():
    assert stopped_for_length(_openai_chat("length"))
    assert not stopped_for_length(_openai_chat("stop"))


def test_google():
    assert stopped_for_length(_google("MAX_TOKENS"))
    assert not stopped_for_length(_google("STOP"))


def test_openai_responses_api():
    assert stopped_for_length(_openai_responses("incomplete", "max_output_tokens"))
    assert not stopped_for_length(_openai_responses("completed", None))


def test_a_responses_api_stop_for_another_reason_is_not_a_length_stop():
    assert not stopped_for_length(_openai_responses("incomplete", "content_filter"))


@pytest.mark.parametrize(
    "response",
    [
        object(),
        SimpleNamespace(response_metadata=None),
        SimpleNamespace(response_metadata={}),
        SimpleNamespace(response_metadata={"incomplete_details": None}),
        SimpleNamespace(response_metadata={"incomplete_details": "max_output_tokens"}),
        SimpleNamespace(response_metadata={"finish_reason": None, "stop_reason": None}),
    ],
)
def test_no_usable_reason_is_no_claim(response):
    assert not stopped_for_length(response)

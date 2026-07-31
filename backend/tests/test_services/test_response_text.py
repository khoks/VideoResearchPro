"""``response_text`` — reasoning models return content BLOCKS, not a string.

Live catch (2026-07-30): claude-sonnet-5 with reasoning enabled returns
``[{"type":"thinking",...},{"type":"text","text":...}]`` once the model
actually thinks. Trivial prompts still return a plain string, so the shape
flips per request — every call site doing ``response.content`` got a list
exactly when the prompt was substantial. Report composition would have
written a stringified Python list into the HTML report.
"""
from types import SimpleNamespace

from app.services.llm_service import response_text


def test_plain_string_content_passes_through() -> None:
    assert response_text(SimpleNamespace(content="<p>hello</p>")) == "<p>hello</p>"


def test_thinking_blocks_are_stripped_and_text_kept() -> None:
    resp = SimpleNamespace(content=[
        {"type": "thinking", "thinking": "let me reason about this at length..."},
        {"type": "text", "text": "<h2>Key Facts</h2>"},
    ])
    assert response_text(resp) == "<h2>Key Facts</h2>"


def test_multiple_text_blocks_are_concatenated() -> None:
    resp = SimpleNamespace(content=[
        {"type": "text", "text": "part one "},
        {"type": "thinking", "thinking": "..."},
        {"type": "text", "text": "part two"},
    ])
    assert response_text(resp) == "part one part two"


def test_redacted_thinking_is_dropped() -> None:
    resp = SimpleNamespace(content=[
        {"type": "redacted_thinking", "data": "encrypted"},
        {"type": "text", "text": "answer"},
    ])
    assert response_text(resp) == "answer"


def test_json_parsing_call_sites_get_valid_json_not_a_list_repr() -> None:
    """The JSON call sites (map, search rank, knowledge extract) must receive
    parseable text, never ``str(list_of_blocks)``."""
    import json

    resp = SimpleNamespace(content=[
        {"type": "thinking", "thinking": "planning the JSON"},
        {"type": "text", "text": '{"facts": [{"content": "a"}]}'},
    ])
    assert json.loads(response_text(resp)) == {"facts": [{"content": "a"}]}


def test_empty_and_none_content_are_safe() -> None:
    assert response_text(SimpleNamespace(content=None)) == ""
    assert response_text(SimpleNamespace(content=[])) == ""
    # Thinking-only response (model produced no visible text).
    assert response_text(SimpleNamespace(content=[{"type": "thinking", "thinking": "x"}])) == ""


def test_bare_string_blocks_are_tolerated() -> None:
    assert response_text(SimpleNamespace(content=["a", "b"])) == "ab"

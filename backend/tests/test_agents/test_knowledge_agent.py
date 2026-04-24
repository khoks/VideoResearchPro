"""Tests for the Knowledge extraction agent (backend/app/agents/knowledge_agent.py).

The agent graph is pure at the splitter + merger layer; LLM-driven nodes are
exercised via mocks returning structured JSON / Markdown.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents import knowledge_agent


def _fake_llm_returning(*payloads: str) -> MagicMock:
    """Build a MagicMock LLM whose `.invoke()` yields each payload in order."""
    responses = [MagicMock(content=p) for p in payloads]
    llm = MagicMock()
    llm.invoke.side_effect = responses
    return llm


def _fake_llm_constant(payload: str) -> MagicMock:
    response = MagicMock(content=payload)
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


# ---------- split_transcript ----------

def test_split_transcript_empty_returns_no_batches():
    result = knowledge_agent.split_transcript({"full_transcript_text": ""})
    assert result == {"transcript_batches": []}


def test_split_transcript_small_text_single_batch():
    text = "Paragraph one.\n\nParagraph two."
    result = knowledge_agent.split_transcript({"full_transcript_text": text})
    assert len(result["transcript_batches"]) == 1
    assert "Paragraph one." in result["transcript_batches"][0]
    assert "Paragraph two." in result["transcript_batches"][0]


def test_split_transcript_large_text_multiple_batches(monkeypatch):
    """Force a small batch budget (at / above the 500-token floor) so the
    transcript packs into multiple batches."""
    monkeypatch.setattr(knowledge_agent.settings, "KNOWLEDGE_EXTRACT_BATCH_TOKENS", 500)
    monkeypatch.setattr(knowledge_agent.settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", 10000)

    # Build paragraphs each > 500 tokens so packing forces a boundary each time.
    para = "word " * 600
    text = "\n\n".join(para for _ in range(4))
    result = knowledge_agent.split_transcript({"full_transcript_text": text})
    assert len(result["transcript_batches"]) >= 2


def test_split_transcript_respects_max_transcript_cap(monkeypatch):
    """Transcript is truncated to KNOWLEDGE_MAX_TRANSCRIPT_TOKENS before batching."""
    monkeypatch.setattr(knowledge_agent.settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", 20)
    monkeypatch.setattr(knowledge_agent.settings, "KNOWLEDGE_EXTRACT_BATCH_TOKENS", 1000)
    text = " ".join(["word"] * 5000)
    result = knowledge_agent.split_transcript({"full_transcript_text": text})
    # Combined batch size should be bounded roughly by the cap (allow slop).
    combined_tokens = knowledge_agent._count_tokens(
        " ".join(result["transcript_batches"])
    )
    assert combined_tokens <= 40


# ---------- extract_per_batch ----------

def test_extract_per_batch_no_batches_returns_empty():
    result = knowledge_agent.extract_per_batch({"transcript_batches": []})
    assert result == {"per_batch_extractions": []}


def test_extract_per_batch_parses_json_response():
    payload = json.dumps({
        "topics": ["climate change"],
        "concepts": ["greenhouse effect"],
        "events": ["Paris Agreement 2015"],
        "facts": ["CO2 reached 420 ppm in 2023"],
    })
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_constant(payload)
        result = knowledge_agent.extract_per_batch({
            "transcript_batches": ["some transcript batch text"],
            "video_title": "Vid",
            "channel_name": "Ch",
        })

    assert len(result["per_batch_extractions"]) == 1
    ext = result["per_batch_extractions"][0]
    assert ext["topics"] == ["climate change"]
    assert ext["facts"] == ["CO2 reached 420 ppm in 2023"]


def test_extract_per_batch_tolerates_code_fences():
    fenced = "```json\n" + json.dumps({
        "topics": ["a"], "concepts": [], "events": [], "facts": [],
    }) + "\n```"
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_constant(fenced)
        result = knowledge_agent.extract_per_batch({
            "transcript_batches": ["b"],
            "video_title": "V", "channel_name": "C",
        })
    assert result["per_batch_extractions"][0]["topics"] == ["a"]


def test_extract_per_batch_non_json_falls_back_to_empty_lists():
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_constant("not json at all")
        result = knowledge_agent.extract_per_batch({
            "transcript_batches": ["b"],
            "video_title": "V", "channel_name": "C",
        })
    assert result["per_batch_extractions"][0] == {
        "topics": [], "concepts": [], "events": [], "facts": [],
    }


def test_extract_per_batch_continues_when_llm_raises():
    llm = MagicMock()
    llm.invoke.side_effect = [
        RuntimeError("boom"),
        MagicMock(content=json.dumps({
            "topics": ["recovered"], "concepts": [], "events": [], "facts": [],
        })),
    ]
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        result = knowledge_agent.extract_per_batch({
            "transcript_batches": ["b1", "b2"],
            "video_title": "V", "channel_name": "C",
        })
    assert len(result["per_batch_extractions"]) == 2
    # First failed → all empty; second recovered.
    assert result["per_batch_extractions"][0]["topics"] == []
    assert result["per_batch_extractions"][1]["topics"] == ["recovered"]


# ---------- merge_extractions ----------

def test_merge_extractions_empty_input():
    result = knowledge_agent.merge_extractions({"per_batch_extractions": []})
    assert result["merged_extraction"] == {
        "topics": [], "concepts": [], "events": [], "facts": [],
    }


def test_merge_extractions_case_insensitive_dedupe():
    batches = [
        {"topics": ["AI", "ethics"], "concepts": ["LLM"], "events": [], "facts": []},
        {"topics": ["ai", "Policy"], "concepts": ["llm", "RAG"], "events": [], "facts": []},
    ]
    result = knowledge_agent.merge_extractions({"per_batch_extractions": batches})
    merged = result["merged_extraction"]
    # First-seen casing preserved; case-insensitive dupes dropped.
    assert merged["topics"] == ["AI", "ethics", "Policy"]
    assert merged["concepts"] == ["LLM", "RAG"]
    assert merged["events"] == []
    assert merged["facts"] == []


def test_merge_extractions_ignores_malformed_entries():
    batches = [
        {"topics": ["a"], "concepts": [], "events": [], "facts": []},
        "not-a-dict",
        {"topics": "also-not-a-list", "concepts": ["b"], "events": [], "facts": []},
    ]
    result = knowledge_agent.merge_extractions({"per_batch_extractions": batches})
    merged = result["merged_extraction"]
    assert merged["topics"] == ["a"]
    assert merged["concepts"] == ["b"]


# ---------- synthesize_report ----------

def test_synthesize_report_empty_merged_and_transcript_returns_empty():
    state = {
        "merged_extraction": {"topics": [], "concepts": [], "events": [], "facts": []},
        "full_transcript_text": "",
    }
    result = knowledge_agent.synthesize_report(state)
    assert result == {"knowledge_report_md": ""}


def test_synthesize_report_invokes_llm_and_strips_code_fence():
    md_with_fence = "```markdown\n# Title\n\nParagraph.\n```"
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_constant(md_with_fence)
        result = knowledge_agent.synthesize_report({
            "merged_extraction": {
                "topics": ["a"], "concepts": [], "events": [], "facts": [],
            },
            "full_transcript_text": "transcript text",
            "video_title": "V", "channel_name": "C",
        })
    assert result["knowledge_report_md"].startswith("# Title")
    assert "Paragraph." in result["knowledge_report_md"]
    assert "```" not in result["knowledge_report_md"]


def test_synthesize_report_returns_empty_on_llm_error():
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("boom")
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        result = knowledge_agent.synthesize_report({
            "merged_extraction": {
                "topics": ["a"], "concepts": [], "events": [], "facts": [],
            },
            "full_transcript_text": "x",
            "video_title": "V", "channel_name": "C",
        })
    assert result == {"knowledge_report_md": ""}


# ---------- run_knowledge_extract_agent (full graph) ----------

def test_run_knowledge_extract_agent_full_graph():
    """Full graph invocation: mocks LLM to return one extraction + one markdown doc."""
    extraction_payload = json.dumps({
        "topics": ["databases"],
        "concepts": ["ACID"],
        "events": [],
        "facts": ["PostgreSQL is open source"],
    })
    report_md = "# Databases\n\n## Overview\n\nAn overview paragraph."

    video = SimpleNamespace(
        video_id="vid123",
        title="Databases 101",
        channel_name="DBA Channel",
    )

    with patch.object(
        knowledge_agent, "get_llm_for",
        side_effect=[_fake_llm_constant(extraction_payload), _fake_llm_constant(report_md)],
    ):
        result = knowledge_agent.run_knowledge_extract_agent(
            video=video,
            full_transcript_text="A single paragraph about PostgreSQL and ACID.",
        )

    assert result["topics"] == ["databases"]
    assert result["concepts"] == ["ACID"]
    assert result["facts"] == ["PostgreSQL is open source"]
    assert result["knowledge_report_md"].startswith("# Databases")


def test_run_knowledge_extract_agent_empty_transcript():
    """Empty transcript short-circuits: no batches, no LLM calls, empty result."""
    video = SimpleNamespace(video_id="v", title="t", channel_name="c")
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        result = knowledge_agent.run_knowledge_extract_agent(
            video=video, full_transcript_text=""
        )
    # merge_extractions always runs → returns empty-list skeleton; synthesize
    # short-circuits on empty merged + transcript → empty string.
    assert result["topics"] == []
    assert result["knowledge_report_md"] == ""
    # LLM never invoked when there are no batches and the synth short-circuits.
    mock_get_llm.assert_not_called()

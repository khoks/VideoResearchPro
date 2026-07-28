"""Tests for the Knowledge extraction agent (backend/app/agents/knowledge_agent.py).

The agent graph is pure at the splitter + merger layer; LLM-driven nodes are
exercised via mocks returning structured JSON / Markdown.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


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


def _long_paragraph_text(num_paragraphs: int, words_per_paragraph: int = 400) -> str:
    """Build a transcript of `num_paragraphs` ~400-token paragraphs. Paragraph
    structure keeps `split_transcript` on the fast per-paragraph path."""
    para = "word " * words_per_paragraph
    return "\n\n".join(para.strip() for _ in range(num_paragraphs))


def test_split_transcript_does_not_truncate_over_60k(monkeypatch):
    """S-1.12.8: the old KNOWLEDGE_MAX_TRANSCRIPT_TOKENS truncation is gone —
    a >60K-token transcript is batched in full, nothing dropped."""
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", 60000
    )
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_EXTRACT_BATCH_TOKENS", 8000
    )
    text = _long_paragraph_text(160)  # ~64K tokens
    input_tokens = knowledge_agent._count_tokens(text)
    assert input_tokens > 60000

    result = knowledge_agent.split_transcript({"full_transcript_text": text})
    batches = result["transcript_batches"]
    assert len(batches) >= 8  # ~64K / 8K budget
    combined_tokens = knowledge_agent._count_tokens("\n\n".join(batches))
    # Nothing dropped: rejoined batches carry (approximately) every token.
    assert combined_tokens >= input_tokens * 0.99


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


def test_synthesize_prompt_excludes_transcript_tail(monkeypatch):
    """S-1.12.8: the synthesis prompt carries only an OPENING excerpt of the
    transcript (min(KNOWLEDGE_MAX_TRANSCRIPT_TOKENS, 20K) tokens). A marker
    planted beyond that budget must NOT reach the LLM; the merged extraction
    JSON must."""
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", 60000
    )
    # Excerpt budget = min(60000, 20000) = 20000 tokens; marker sits at ~21K.
    text = "OPENING_ANCHOR_TOKEN " + ("word " * 21000) + " DEEP_TAIL_MARKER_XYZZY"
    llm = _fake_llm_constant("# Doc")
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        result = knowledge_agent.synthesize_report({
            "merged_extraction": {
                "topics": ["quantum databases"], "concepts": [],
                "events": [], "facts": ["PostgreSQL is open source"],
            },
            "full_transcript_text": text,
            "video_title": "V", "channel_name": "C",
        })

    assert result["knowledge_report_md"] == "# Doc"
    prompt = llm.invoke.call_args.args[0][0].content
    assert "DEEP_TAIL_MARKER_XYZZY" not in prompt
    assert "OPENING_ANCHOR_TOKEN" in prompt
    # The coverage input (merged extraction JSON) is present.
    assert "PostgreSQL is open source" in prompt
    assert "quantum databases" in prompt


def test_synthesize_excerpt_bounded_by_setting_when_below_20k(monkeypatch):
    """The excerpt budget is min(setting, 20K) — a setting below 20K wins."""
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", 100
    )
    text = ("word " * 300) + " TAIL_MARKER_ABC"
    llm = _fake_llm_constant("# Doc")
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        knowledge_agent.synthesize_report({
            "merged_extraction": {
                "topics": ["a"], "concepts": [], "events": [], "facts": [],
            },
            "full_transcript_text": text,
            "video_title": "V", "channel_name": "C",
        })
    prompt = llm.invoke.call_args.args[0][0].content
    assert "TAIL_MARKER_ABC" not in prompt


def test_synthesize_caps_merged_extraction_json(monkeypatch):
    """Degenerate case: a merged extraction JSON over 30K tokens is truncated
    (head survives, tail dropped) instead of blowing the synthesis context."""
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_MAX_TRANSCRIPT_TOKENS", 60000
    )
    facts = [f"fact-{i} " + ("detail " * 20) for i in range(2500)]  # >> 30K tokens
    llm = _fake_llm_constant("# Doc")
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        knowledge_agent.synthesize_report({
            "merged_extraction": {
                "topics": [], "concepts": [], "events": [], "facts": facts,
            },
            "full_transcript_text": "short transcript",
            "video_title": "V", "channel_name": "C",
        })
    prompt = llm.invoke.call_args.args[0][0].content
    assert "fact-0 " in prompt
    assert "fact-2499" not in prompt


def test_synthesize_passes_max_tokens_to_llm():
    """S-1.12.7: knowledge_synthesize_report keeps its 8000-token cap."""
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_constant("# Doc")
        knowledge_agent.synthesize_report({
            "merged_extraction": {
                "topics": ["a"], "concepts": [], "events": [], "facts": [],
            },
            "full_transcript_text": "x",
            "video_title": "V", "channel_name": "C",
        })
    args, kwargs = mock_get_llm.call_args
    assert args[0] == "knowledge_synthesize_report"
    assert kwargs["max_tokens"] == 8000


def test_extract_per_batch_passes_max_tokens_to_llm():
    """S-1.12.7: knowledge_extract_batch gets max_tokens=3000 (registry
    typ_out 2000 with 1.5x headroom)."""
    with patch.object(knowledge_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_constant("{}")
        knowledge_agent.extract_per_batch({
            "transcript_batches": ["b"],
            "video_title": "V", "channel_name": "C",
        })
    args, kwargs = mock_get_llm.call_args
    assert args[0] == "knowledge_extract_batch"
    assert kwargs["max_tokens"] == 3000


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


# ---------- S-1.12.8: windowed extraction / sanity ceiling ----------

_EXTRACTION_PAYLOAD = json.dumps({
    "topics": ["t"], "concepts": [], "events": [], "facts": [],
})


def test_run_agent_over_60k_fully_batched_no_processing_flag(monkeypatch):
    """(a) A >60K-token transcript is fully batched — every batch hits the
    map LLM, no truncation, and no `_processing` key on the artifact."""
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_EXTRACT_BATCH_TOKENS", 8000
    )
    text = _long_paragraph_text(160)  # ~64K tokens
    assert knowledge_agent._count_tokens(text) > 60000

    extract_llm = _fake_llm_constant(_EXTRACTION_PAYLOAD)
    synth_llm = _fake_llm_constant("# Report")
    video = SimpleNamespace(video_id="v-long", title="Long", channel_name="C")

    with patch.object(
        knowledge_agent, "get_llm_for", side_effect=[extract_llm, synth_llm]
    ):
        result = knowledge_agent.run_knowledge_extract_agent(
            video=video, full_transcript_text=text
        )

    assert "_processing" not in result
    # The whole transcript reached the map phase: ~64K / 8K → >= 8 batches.
    assert extract_llm.invoke.call_count >= 8
    assert result["topics"] == ["t"]


def test_run_agent_sanity_ceiling_truncates_over_500k(monkeypatch):
    """(b) A >500K-token transcript trips the sanity ceiling: truncated at
    500K with `_processing` recording both token counts."""
    monkeypatch.setattr(
        knowledge_agent.settings, "KNOWLEDGE_EXTRACT_BATCH_TOKENS", 8000
    )
    text = _long_paragraph_text(1300)  # ~522K tokens
    extract_llm = _fake_llm_constant(_EXTRACTION_PAYLOAD)
    synth_llm = _fake_llm_constant("# Report")
    video = SimpleNamespace(video_id="v-huge", title="Huge", channel_name="C")

    with patch.object(
        knowledge_agent, "get_llm_for", side_effect=[extract_llm, synth_llm]
    ):
        result = knowledge_agent.run_knowledge_extract_agent(
            video=video, full_transcript_text=text
        )

    proc = result["_processing"]
    assert proc["truncated"] is True
    assert proc["processed_tokens"] == knowledge_agent.TRANSCRIPT_SANITY_CEILING_TOKENS
    assert proc["total_tokens"] > 500_000
    assert proc["total_tokens"] > proc["processed_tokens"]
    # Extraction still covered the retained ~500K tokens (~62 batches at 8K).
    assert extract_llm.invoke.call_count >= 55

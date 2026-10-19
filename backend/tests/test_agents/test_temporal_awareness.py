"""R3 temporal awareness + the Q&A half of R4, at the agent layer.

Covers: the answer-length policy (job + library), dates and eras in the
Q&A allowed-sources list and raw-context headers, the corpus facts every
report section receives, the summary reading section text instead of item
counts, era in the map headers, the knowledge agent's anchoring note, and
the search ranker's temporal profile, era line and English preference —
each a preference, never a filter.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents import knowledge_agent, qa_agent, report_agent, search_agent
from app.services.llm_routing import max_output_for, resolve_config

# Captured before the autouse fixture below replaces it for the search tests.
_ORIGINAL_LOOKUP = search_agent._lookup_known_eras

XLARGE = {
    "video_count": 200, "total_words": 1_057_331,
    "earliest_published": "2024-01-05", "latest_published": "2026-07-20",
    "median_published": "2026-02-11", "videos_by_year": {"2026": 120, "2025": 60, "2024": 20},
    "dated_video_count": 200,
    "era_known_count": 180, "discussed_era_start": 2016, "discussed_era_end": 2026,
    "retrospective_count": 12,
}


def _fake_llm(payload: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=payload)
    return llm


def _chunk(vid="v1", title="Real Video", channel="ChA", published="2025-03-12T10:00:00Z",
           era=True, text="chunk text"):
    meta = {
        "video_id": vid, "video_title": title, "channel_name": channel,
        "video_url": f"https://www.youtube.com/watch?v={vid}", "timestamp_start": 42.0,
        "timestamp_end": 60.0, "word_count": 2, "published_at": published,
    }
    if era:
        meta.update({"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True})
    return {"text": text, "metadata": meta, "distance": 0.1, "timestamp_display": "0:42"}


# ---------- answer policy (job + library) -----------------------------------

def test_answer_policy_xlarge_is_not_the_small_brief():
    max_tokens, note, guidance = qa_agent._answer_policy(XLARGE, None, "qa_formulate_answer")
    assert max_tokens == min(4_500, max_output_for(resolve_config("qa_formulate_answer").model))
    assert guidance == "", "xlarge on auto gets no small-corpus brief"
    assert "200 source(s) published between 2024-01-05 and 2026-07-20" in note
    assert "2016–2026" in note and "12 of them retrospective" in note
    assert "disagree along a time axis" in note


def test_answer_policy_empty_statistics_is_the_defect_shape():
    """Documents the pre-fix behaviour so the wiring tests mean something."""
    max_tokens, note, guidance = qa_agent._answer_policy({}, None, "qa_formulate_answer")
    assert max_tokens == int(4_500 * 1.25)
    assert "corpus is small" in guidance
    assert note == ""


def test_answer_policy_user_override_scales():
    brief, _, g1 = qa_agent._answer_policy(XLARGE, "brief", "qa_formulate_answer")
    deep, _, g2 = qa_agent._answer_policy(XLARGE, "deep", "qa_formulate_answer")
    assert brief == int(4_500 * 0.45) and "tight" in g1
    assert deep == int(4_500 * 1.6) and "depth" in g2


def test_formulate_answer_prompt_carries_corpus_note_and_dated_sources():
    with patch.object(qa_agent, "get_llm_for") as get_llm:
        get_llm.return_value = _fake_llm("answer")
        qa_agent.formulate_answer({
            "question": "q", "refined_context": "ctx", "rag_results": [_chunk()],
            "report_context": None, "corpus_statistics": XLARGE, "output_length": None,
        })
    human = get_llm.return_value.invoke.call_args.args[0][1].content
    assert '- "Real Video" by ChA | published 2025-03-12 | discusses 2019–2021 (retrospective)' in human
    assert "CORPUS: this answer draws on 200 source(s)" in human
    assert get_llm.call_args.kwargs["max_tokens"] == 4_500


def test_allowed_sources_without_dates_stay_bare():
    line = qa_agent._build_allowed_sources([_chunk(published="", era=False)], include_report=False)
    assert line == '- "Real Video" by ChA'


def test_refine_context_headers_carry_date_and_era():
    with patch.object(qa_agent, "get_llm_for") as get_llm:
        get_llm.return_value = _fake_llm("refined")
        qa_agent.refine_context({"question": "q", "rag_results": [_chunk()], "report_context": None})
    prompt = get_llm.return_value.invoke.call_args.args[0][0].content
    assert '[Chunk 1 | Video: "Real Video" by ChA at 0:42 | published 2025-03-12 | discusses 2019–2021 (retrospective)]' in prompt


def test_library_qa_applies_the_policy_and_dates_sources():
    rag = [_chunk(vid="vDNS", title="How DNS Works", channel="NetTeach")]
    llms = [_fake_llm(""), _fake_llm("ctx"), _fake_llm('[Source: "How DNS Works" by NetTeach at 0:42]')]
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=rag), \
         patch.object(qa_agent, "get_llm_for", side_effect=llms) as get_llm:
        qa_agent.run_library_qa_agent(
            question="What is DNS?", visible_document_ids=["vDNS"],
            corpus_statistics=XLARGE, output_length="brief",
        )
    answer_call = get_llm.call_args_list[2]
    assert answer_call.args[0] == "library_qa_formulate_answer"
    assert answer_call.kwargs["max_tokens"] == int(4_500 * 0.45)
    human = llms[2].invoke.call_args.args[0][1].content
    assert 'vDNS | "How DNS Works" by NetTeach | published 2025-03-12 | discusses 2019–2021' in human
    assert "CORPUS: this answer draws on 200 source(s)" in human
    assert "LENGTH: aim for a tight" in human
    system = llms[2].invoke.call_args.args[0][0].content
    assert "SUPERSESSION" in system and "NOT spoken words" in system


def test_library_qa_without_statistics_still_runs_as_small():
    """Back-compat for callers that pass nothing: the old 4,500 becomes the small bracket."""
    llms = [_fake_llm(""), _fake_llm("ctx"), _fake_llm("I don't know.")]
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]), \
         patch.object(qa_agent, "get_llm_for", side_effect=llms) as get_llm:
        qa_agent.run_library_qa_agent(question="q")
    assert get_llm.call_args_list[2].kwargs["max_tokens"] == int(4_500 * 1.25)


def test_citation_sanitizer_survives_dated_source_lines():
    """The date suffix must not make a genuine citation look fabricated."""
    answer = 'Claim. [Source: "Real Video" by ChA at 0:42]'
    sanitized, removed = qa_agent._sanitize_citations(answer, [_chunk()])
    assert removed == 0 and sanitized == answer


# ---------- report: statistics, map headers, corpus facts, summary ------------

def test_compute_statistics_summarises_eras_and_language():
    chunks = [
        _chunk("v1", era=True, text="plain english"),
        _chunk("v2", era=False, text="आज हम बात करेंगे इस विषय पर"),
    ]
    stats = report_agent.compute_statistics({"transcript_chunks": chunks})["statistics"]
    assert stats["era_known_count"] == 1
    assert (stats["discussed_era_start"], stats["discussed_era_end"]) == (2019, 2021)
    assert stats["retrospective_count"] == 1
    assert "Devanagari" in stats["language_profile"]["scripts"]
    assert "switch_points" not in stats["language_profile"]


def test_map_header_carries_era_and_language_note():
    with patch.object(report_agent, "get_llm_for") as get_llm:
        get_llm.return_value = _fake_llm(json.dumps({"facts": []}))
        report_agent.map_chunks({
            "job_type": "topic", "topic": "t",
            "transcript_chunks": [_chunk(text="आज हम बात करेंगे इस विषय पर और यह बहुत महत्वपूर्ण है")],
        })
    prompt = get_llm.return_value.invoke.call_args.args[0][0].content
    assert "| published 2025-03-12 | discusses 2019–2021 (retrospective) |" in prompt
    assert "SOURCE LANGUAGE: this transcript is not primarily English" in prompt


def test_corpus_facts_block_quotes_the_verified_figures():
    facts = report_agent._corpus_facts({**XLARGE, "channel_breakdown": [{}] * 92, "total_minutes": 9_876})
    assert "Videos: 200 (exact count" in facts and "channels: 92" in facts
    assert "Transcript words: 1,057,331; total minutes: 9,876" in facts
    assert "Published between 2024-01-05 and 2026-07-20 (median 2026-02-11)" in facts
    assert "by year: 2026: 120, 2025: 60, 2024: 20" in facts
    assert "Discussed era: The subject matter spans 2016–2026" in facts


def test_corpus_facts_says_so_when_undated():
    facts = report_agent._corpus_facts({"video_count": 3})
    assert "Publication dates: not available" in facts
    assert "Discussed era: not available" in facts


def test_every_section_and_the_summary_receive_the_same_corpus_facts():
    prompts: list[tuple[str, str]] = []

    def capture(use_case, prompt, *, max_tokens, temperature, label=""):
        prompts.append((label, prompt))
        return "<h2>Written</h2><p>Report body about tariffs.</p>"

    with patch.object(report_agent, "_invoke_with_retry", side_effect=capture):
        report_agent.compose_report({
            "job_type": "topic", "topic": "t",
            "chunk_summaries": [{"facts": [{"content": "f"}], "conclusions": [{"content": "c"}]}],
            "statistics": {**XLARGE, "channel_breakdown": [{}] * 92},
        })

    labels = [label for label, _ in prompts]
    assert any("Key Facts" in lab for lab in labels) and any("Conclusions" in lab for lab in labels)
    assert any("executive summary" in lab for lab in labels)
    for label, prompt in prompts:
        assert "Videos: 200 (exact count" in prompt, label
        assert "Published between 2024-01-05 and 2026-07-20" in prompt, label

    summary = next(p for lab, p in prompts if "executive summary" in lab)
    # T-1.14.15.2: the summary reads the written text, not pipeline counts.
    assert "Report body about tariffs." in summary
    assert "=== Written ===" in summary
    assert "items" not in summary.split("VERIFIED CORPUS FACTS")[1].split("The report's body")[0]
    assert "1 items" not in summary
    assert "Never mention item counts" in summary


def test_section_text_digest_abridges_each_part():
    parts = ["<h2>A</h2><p>" + "word " * 3000 + "</p>", "<h2>B</h2><p>short</p>"]
    digest = report_agent._section_text_digest(parts, budget_tokens=1_000)
    assert digest.startswith("=== A ===")
    assert "=== B ===\nshort" in digest
    assert len(digest.split()) < 1_200


# ---------- knowledge agent: anchoring note ----------------------------------

def test_knowledge_extract_prompt_anchors_relative_time():
    with patch.object(knowledge_agent, "get_llm_for") as get_llm:
        get_llm.return_value = _fake_llm(json.dumps({"topics": [], "concepts": [], "events": [], "facts": []}))
        knowledge_agent.extract_per_batch({
            "transcript_batches": ["batch"], "video_title": "T", "channel_name": "C",
            "published_at": "2025-03-12", "discussed_era": "discusses 2019–2021 (retrospective)",
        })
    prompt = get_llm.return_value.invoke.call_args.args[0][0].content
    assert "Published: 2025-03-12 — anchor relative time expressions to this date." in prompt
    assert "This source discusses 2019–2021 (retrospective)" in prompt
    assert "anchor relative time expressions" in prompt


def test_knowledge_extract_prompt_without_date_keeps_relative_phrases():
    with patch.object(knowledge_agent, "get_llm_for") as get_llm:
        get_llm.return_value = _fake_llm(json.dumps({"topics": [], "concepts": [], "events": [], "facts": []}))
        knowledge_agent.extract_per_batch({"transcript_batches": ["batch"], "video_title": "T", "channel_name": "C"})
    prompt = get_llm.return_value.invoke.call_args.args[0][0].content
    assert "Published: unknown — keep relative time expressions verbatim" in prompt


def test_run_knowledge_agent_threads_date_and_era_from_the_document():
    video = SimpleNamespace(
        video_id="vid", title="T", channel_name="C",
        published_at=datetime(2025, 3, 12),
        discussed_era_json=json.dumps({"era_start": 2019, "era_end": 2021, "era_confidence": 0.9, "is_retrospective": True}),
    )
    extract = _fake_llm(json.dumps({"topics": ["x"], "concepts": [], "events": [], "facts": []}))
    synth = _fake_llm("# Report\n\nAs of 2025-03-12 ...")
    with patch.object(knowledge_agent, "get_llm_for", side_effect=[extract, synth]):
        knowledge_agent.run_knowledge_extract_agent(video, "A paragraph.")
    for llm in (extract, synth):
        prompt = llm.invoke.call_args.args[0][0].content
        assert "Published: 2025-03-12" in prompt
        assert "discusses 2019–2021 (retrospective)" in prompt


# ---------- search: temporal profile, era line, English preference -----------

@pytest.fixture(autouse=True)
def _no_db_lookup():
    with patch.object(search_agent, "_lookup_known_eras", return_value={}) as m:
        yield m


def test_plan_searches_parses_temporal_profile():
    payload = json.dumps({
        "broad_queries": ["q"], "channel_keywords": ["k"],
        "temporal_profile": {"recency_weight": "Dominant", "target_era": None, "rationale": "moves fast"},
    })
    with patch.object(search_agent, "get_llm_for", return_value=_fake_llm(payload)):
        out = search_agent.plan_searches({"topic": "t", "preferred_channel_ids": []})
    assert out["temporal_profile"] == {"recency_weight": "dominant", "target_era": None, "rationale": "moves fast"}


def test_plan_searches_defaults_profile_when_missing_or_invalid():
    payload = json.dumps({"broad_queries": ["q"], "channel_keywords": [], "temporal_profile": {"recency_weight": "huge"}})
    with patch.object(search_agent, "get_llm_for", return_value=_fake_llm(payload)):
        out = search_agent.plan_searches({"topic": "t", "preferred_channel_ids": []})
    assert out["temporal_profile"]["recency_weight"] == "secondary"
    with patch.object(search_agent, "get_llm_for", return_value=_fake_llm("not json")):
        out = search_agent.plan_searches({"topic": "t", "preferred_channel_ids": []})
    assert out["temporal_profile"]["recency_weight"] == "secondary"


def test_temporal_guidance_states_the_decision_and_the_never_a_filter_rule():
    text = search_agent._temporal_guidance({"recency_weight": "dominant", "target_era": "the 2008 crisis", "rationale": "r"})
    assert "RECENCY IS DOMINANT" in text
    assert "TARGET ERA: the topic concerns the 2008 crisis" in text
    assert "never filters" in text and "never excluded" in text
    assert "RECENCY IS SECONDARY" in search_agent._temporal_guidance(None)
    assert "RECENCY IS MINIMAL" in search_agent._temporal_guidance({"recency_weight": "minimal"})


def test_rank_prompt_carries_profile_era_script_and_language_preference(_no_db_lookup):
    _no_db_lookup.return_value = {
        "old": {"era_start": 2008, "era_end": 2009, "era_confidence": 0.9, "is_retrospective": True}
    }
    pool = [
        {"video_id": "old", "title": "The 2008 crash explained", "channel_name": "A",
         "duration_seconds": 600, "published_at": "2015-01-01T00:00:00Z"},
        {"video_id": "new", "title": "Markets today", "channel_name": "B",
         "duration_seconds": 600, "published_at": "2026-01-01T00:00:00Z"},
        {"video_id": "hi", "title": "बाज़ार की कहानी", "channel_name": "C",
         "duration_seconds": 600, "published_at": "2025-01-01T00:00:00Z"},
    ]
    llm = _fake_llm(json.dumps(["old", "hi"]))
    with patch.object(search_agent, "get_llm_for", return_value=llm):
        result = search_agent.rank_and_curate({
            "topic": "2008 financial crisis", "discovered_videos": pool, "num_videos": 2,
            "search_instructions": "",
            "temporal_profile": {"recency_weight": "minimal", "target_era": "2008", "rationale": ""},
        })
    prompt = llm.invoke.call_args.args[0][0].content
    assert "RECENCY IS MINIMAL" in prompt and "TARGET ERA: the topic concerns 2008" in prompt
    assert "| Era: discusses 2008–2009 (retrospective) |" in prompt
    assert "| Script: Devanagari |" in prompt
    assert "LANGUAGE (a preference, never a filter)" in prompt
    # Never a filter: the ten-year-old, non-English picks survive untouched.
    assert [v["video_id"] for v in result["curated_videos"]] == ["old", "hi"]


def test_rank_prompt_without_profile_still_formats():
    pool = [{"video_id": f"v{i}", "title": f"T{i}", "channel_name": "A", "duration_seconds": 600} for i in range(3)]
    llm = _fake_llm(json.dumps(["v1", "v2"]))
    with patch.object(search_agent, "get_llm_for", return_value=llm):
        search_agent.rank_and_curate({"topic": "t", "discovered_videos": pool, "num_videos": 2, "search_instructions": ""})
    prompt = llm.invoke.call_args.args[0][0].content
    assert "TEMPORAL PROFILE" in prompt and "Era:" not in prompt.split("Videos found:")[1].split("TEMPORAL PROFILE")[0]


def test_lookup_known_eras_is_fail_soft():
    """No database (a unit test, a schema behind head) means no eras, never a failed job."""
    with patch("app.database.SessionLocal", side_effect=RuntimeError("no db")):
        assert _ORIGINAL_LOOKUP(["v"]) == {}
    assert _ORIGINAL_LOOKUP([]) == {}

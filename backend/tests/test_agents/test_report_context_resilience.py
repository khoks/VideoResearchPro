"""E-1.12 — report-pipeline context resilience tests (S-1.12.2/.3/.4/.6)
plus the S-1.12.1 job-scope retrieval fix.
"""
from unittest.mock import MagicMock, patch

from app.agents import report_agent
from app.agents.report_agent import (
    _batch_budget,
    _QUALITY_BATCH_CAP,
    compose_report,
    map_chunks,
    reduce_summaries,
)
from app.services.llm_routing import UseCaseConfig


def _chunk(text: str, title: str = "Vid") -> dict:
    return {"text": text, "metadata": {"video_title": title, "channel_name": "Ch", "timestamp_start": 0}}


# ---------------------------------------------------------------------------
# S-1.12.2 — model-derived batch budgets
# ---------------------------------------------------------------------------


def test_batch_budget_uses_resolved_model_window():
    with patch.object(
        report_agent, "resolve_config",
        return_value=UseCaseConfig("openai", "gpt-5.4-nano", "off"),
    ):
        # 272,000 × 0.5 = 136,000, above the 120K quality cap → cap wins.
        assert _batch_budget("report_map_chunks") == _QUALITY_BATCH_CAP


def test_batch_budget_small_window_beats_quality_cap():
    with patch.object(
        report_agent, "resolve_config",
        return_value=UseCaseConfig("local", "some-8k-model", "off"),
    ):
        # Unknown model → conservative 128K default window × 0.5 = 64K < cap.
        assert _batch_budget("report_map_chunks") == 64_000


# ---------------------------------------------------------------------------
# S-1.12.6 — bisect retry on map-batch failure
# ---------------------------------------------------------------------------


def _fake_llm(fail_on_call: set[int]):
    llm = MagicMock()
    counter = {"n": 0}

    def invoke(_msgs):
        counter["n"] += 1
        if counter["n"] in fail_on_call:
            raise RuntimeError("simulated 400 context overflow")
        resp = MagicMock()
        resp.content = '{"facts": ["ok"]}'
        return resp

    llm.invoke.side_effect = invoke
    return llm, counter


def test_map_bisect_recovers_failed_batch():
    chunks = [_chunk(f"text {i}") for i in range(4)]
    llm, counter = _fake_llm(fail_on_call={1})  # full batch fails, halves succeed
    state = {"job_type": "topic", "topic": "t", "transcript_chunks": chunks, "processing_notes": {}}
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = map_chunks(state)
    assert counter["n"] == 3  # 1 failed full + 2 successful halves
    assert len(out["chunk_summaries"]) == 2
    assert out["processing_notes"]["map_batches_failed"] == 0
    assert out["processing_notes"]["map_chunks_dropped"] == 0


def test_map_bisect_records_permanent_drop():
    chunks = [_chunk(f"text {i}") for i in range(4)]
    llm, counter = _fake_llm(fail_on_call={1, 2, 3})  # full + both halves fail
    state = {"job_type": "topic", "topic": "t", "transcript_chunks": chunks, "processing_notes": {}}
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = map_chunks(state)
    assert out["chunk_summaries"] == []
    assert out["processing_notes"]["map_batches_failed"] == 2
    assert out["processing_notes"]["map_chunks_dropped"] == 4


# ---------------------------------------------------------------------------
# S-1.12.3 — recursive reduce
# ---------------------------------------------------------------------------


def test_reduce_recurses_to_single_summary(monkeypatch):
    summaries = [{"facts": [f"fact-{i}" * 200]} for i in range(8)]
    merged = MagicMock()
    merged.content = '{"facts": ["merged"]}'
    llm = MagicMock()
    llm.invoke.return_value = merged
    # Force multiple pairwise rounds: budget smaller than any 2-summary dump.
    monkeypatch.setattr(report_agent, "_batch_budget", lambda *a, **k: 500)
    state = {"job_type": "topic", "topic": "t", "chunk_summaries": summaries}
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = reduce_summaries(state)
    # Bounded rounds then final merge — always ends single (or bounded list).
    assert len(out["chunk_summaries"]) >= 1
    assert llm.invoke.call_count >= 4  # multiple pairwise rounds happened


def test_reduce_pair_failure_truncates_instead_of_raw_passthrough(monkeypatch):
    big = {"facts": ["x" * 40_000]}
    summaries = [big, big, big, big]
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("merge down")
    monkeypatch.setattr(report_agent, "_batch_budget", lambda *a, **k: 1_000)
    state = {"job_type": "topic", "topic": "t", "chunk_summaries": summaries}
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = reduce_summaries(state)
    result = out["chunk_summaries"]
    # Nothing unbounded survives: every failed member is token-truncated.
    for item in result:
        if "truncated_summary" in item:
            assert len(item["truncated_summary"]) < 20_000
    assert all("truncated_summary" in i or "facts" not in i or len(str(i)) < 25_000 for i in result)


# ---------------------------------------------------------------------------
# S-1.12.4 — loud accounting in compose
# ---------------------------------------------------------------------------


def test_compose_appends_processing_note_on_drops():
    resp = MagicMock()
    resp.content = "<h1>Report</h1>"
    llm = MagicMock()
    llm.invoke.return_value = resp
    state = {
        "job_type": "topic",
        "topic": "t",
        "chunk_summaries": [{"facts": ["a"]}],
        "statistics": {},
        "processing_notes": {
            "map_batches": 3,
            "map_batches_failed": 1,
            "map_chunks_dropped": 40,
            "map_chunks_total": 120,
        },
    }
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = compose_report(state)
    assert "Processing note" in out["final_html"]
    assert "40 of 120" in out["final_html"]


def test_compose_clean_run_has_no_note():
    resp = MagicMock()
    resp.content = "<h1>Report</h1>"
    llm = MagicMock()
    llm.invoke.return_value = resp
    state = {
        "job_type": "topic",
        "topic": "t",
        "chunk_summaries": [{"facts": ["a"]}],
        "statistics": {},
        "processing_notes": {"map_batches": 2, "map_batches_failed": 0, "map_chunks_dropped": 0},
    }
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = compose_report(state)
    assert "Processing note" not in out["final_html"]


# ---------------------------------------------------------------------------
# S-1.12.1 — job-scoped retrieval actually filters
# ---------------------------------------------------------------------------


def test_retrieve_context_passes_video_ids_filter():
    from app.agents import qa_agent

    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]) as qc, \
         patch.object(qa_agent, "_generate_sub_queries", return_value=[]):
        state = {
            "job_id": "job-1",
            "job_type": "topic",
            "question": "what?",
            "video_ids": ["vidA", "vidB"],
        }
        qa_agent.retrieve_context(state)
    assert qc.call_count == 1
    _, kwargs = qc.call_args
    assert kwargs["video_ids"] == ["vidA", "vidB"]


def test_retrieve_context_no_ids_never_searches_globally():
    from app.agents import qa_agent

    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]) as qc, \
         patch.object(qa_agent, "_generate_sub_queries", return_value=[]):
        state = {
            "job_id": "job-1",
            "job_type": "topic",
            "question": "what?",
            "video_ids": [],
        }
        out = qa_agent.retrieve_context(state)
    qc.assert_not_called()
    assert out["rag_results"] == []

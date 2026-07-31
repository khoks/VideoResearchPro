"""Tests for the Report Agent (backend/app/agents/report_agent.py).

compute_statistics is pure and deterministic — we test it against synthetic
chunks. The LLM-driven map/reduce/compose nodes are exercised via mocks.
"""
from unittest.mock import MagicMock, patch


from app.agents import report_agent


def _fake_llm_returning(payload: str) -> MagicMock:
    response = MagicMock()
    response.content = payload
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


def _chunk(video_id: str, channel: str, ts_start: float, ts_end: float,
           text: str = "some transcript text here", word_count: int | None = None,
           video_title: str = "A Video") -> dict:
    return {
        "text": text,
        "metadata": {
            "video_id": video_id,
            "video_title": video_title,
            "channel_name": channel,
            "channel_id": f"UC_{channel}",
            "timestamp_start": ts_start,
            "timestamp_end": ts_end,
            "word_count": word_count if word_count is not None else len(text.split()),
        },
    }


# ---------- compute_statistics ----------

def test_compute_statistics_empty_chunks():
    result = report_agent.compute_statistics({"transcript_chunks": []})
    stats = result["statistics"]
    assert stats["video_count"] == 0
    assert stats["transcript_count"] == 0
    assert stats["total_words"] == 0
    assert stats["total_minutes"] == 0
    assert stats["channel_breakdown"] == []


def test_compute_statistics_counts_unique_videos_and_words():
    chunks = [
        _chunk("v1", "ChA", 0.0, 60.0, word_count=100),
        _chunk("v1", "ChA", 60.0, 120.0, word_count=80),
        _chunk("v2", "ChB", 0.0, 300.0, word_count=200),
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    stats = result["statistics"]

    assert stats["video_count"] == 2
    assert stats["transcript_count"] == 2
    assert stats["total_words"] == 380


def test_compute_statistics_builds_channel_breakdown():
    chunks = [
        _chunk("v1", "ChA", 0.0, 60.0, word_count=100),
        _chunk("v2", "ChA", 0.0, 120.0, word_count=50),
        _chunk("v3", "ChB", 0.0, 600.0, word_count=200),
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    breakdown = {ch["channel_name"]: ch for ch in result["statistics"]["channel_breakdown"]}

    assert "ChA" in breakdown
    assert "ChB" in breakdown
    assert breakdown["ChA"]["video_count"] == 2
    assert breakdown["ChB"]["video_count"] == 1
    # Words summed across chunks per channel
    assert breakdown["ChA"]["word_count"] == 150
    assert breakdown["ChB"]["word_count"] == 200


def test_compute_statistics_handles_missing_channel_name():
    chunks = [
        {
            "text": "x",
            "metadata": {
                "video_id": "v1",
                "timestamp_start": 0.0,
                "timestamp_end": 60.0,
                "word_count": 10,
            },
        }
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    breakdown = {ch["channel_name"]: ch for ch in result["statistics"]["channel_breakdown"]}
    assert "Unknown" in breakdown


def test_compute_statistics_word_count_falls_back_to_text_split():
    chunks = [
        {
            "text": "one two three four five",
            "metadata": {
                "video_id": "v1",
                "channel_name": "ChA",
                "timestamp_start": 0.0,
                "timestamp_end": 60.0,
                # no word_count — should use len(text.split())
            },
        }
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    assert result["statistics"]["total_words"] == 5


def test_compute_statistics_total_minutes_uses_last_chunk_end():
    # v1 spans 0..180s (3 min), v2 spans 0..60s (1 min) → ~4 min total
    chunks = [
        _chunk("v1", "ChA", 0.0, 60.0, word_count=10),
        _chunk("v1", "ChA", 60.0, 180.0, word_count=10),  # last end for v1 = 180
        _chunk("v2", "ChB", 0.0, 60.0, word_count=10),
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    assert result["statistics"]["total_minutes"] == round((180 + 60) / 60)


# ---------- map_chunks ----------

def test_map_chunks_skipped_for_channel_job():
    state = {
        "job_type": "channel",
        "transcript_chunks": [_chunk("v1", "ChA", 0.0, 60.0)],
        "topic": "x",
    }
    result = report_agent.map_chunks(state)
    assert result == {"chunk_summaries": []}


def test_map_chunks_empty_returns_empty():
    state = {"job_type": "topic", "transcript_chunks": [], "topic": "x"}
    result = report_agent.map_chunks(state)
    assert result == {"chunk_summaries": []}


def test_map_chunks_invokes_llm_and_parses_json():
    chunks = [_chunk("v1", "ChA", 0.0, 60.0, text="hello world")]
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning(
            '{"themes": ["t1"], "insights": ["i1"]}'
        )
        result = report_agent.map_chunks(
            {"job_type": "topic", "transcript_chunks": chunks, "topic": "x"}
        )

    assert len(result["chunk_summaries"]) == 1
    assert result["chunk_summaries"][0] == {"themes": ["t1"], "insights": ["i1"]}


def test_map_chunks_wraps_non_json_response():
    chunks = [_chunk("v1", "ChA", 0.0, 60.0)]
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("free-form text not json")
        result = report_agent.map_chunks(
            {"job_type": "topic", "transcript_chunks": chunks, "topic": "x"}
        )

    assert result["chunk_summaries"] == [{"raw": "free-form text not json"}]


def test_map_chunks_continues_when_llm_batch_raises():
    chunks = [_chunk("v1", "ChA", 0.0, 60.0)]
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("LLM timeout")
        mock_get_llm.return_value = llm

        result = report_agent.map_chunks(
            {"job_type": "topic", "transcript_chunks": chunks, "topic": "x"}
        )

    # Batch skipped gracefully
    assert result["chunk_summaries"] == []


# ---------- reduce_summaries ----------

def test_reduce_summaries_channel_job_short_circuits():
    state = {
        "job_type": "channel",
        "chunk_summaries": [{"a": 1}, {"b": 2}],
        "topic": "x",
    }
    result = report_agent.reduce_summaries(state)
    assert result == {"chunk_summaries": [{"a": 1}, {"b": 2}]}


def test_reduce_summaries_single_summary_is_normalized_losslessly():
    """S-1.14.8: reduce normalizes even one summary, and never drops content.

    An unexpected shape (no facts/comments/... keys) is preserved rather than
    discarded — silent narrowing is the defect this stage exists to prevent.
    """
    state = {
        "job_type": "topic",
        "chunk_summaries": [{"a": 1}],
        "topic": "x",
    }
    result = report_agent.reduce_summaries(state)
    merged = result["chunk_summaries"][0]
    assert set(merged) == set(report_agent._REDUCE_KEYS)
    assert any('"a": 1' in str(f.get("content", "")) for f in merged["facts"])


def test_reduce_summaries_consolidates_without_an_llm():
    """S-1.14.8 / D-055: reduce is deterministic now.

    The old LLM merge-and-dedupe applied a flat 6,000-token output cap on
    every pairwise round and was measured destroying ~91% of items and 46% of
    videos on a real corpus — with zero true duplicates to remove.
    """
    summaries = [
        {"facts": [{"content": "one", "video_url": "u1"}]},
        {"facts": [{"content": "two", "video_url": "u2"}]},
        {"conclusions": [{"content": "three", "video_url": "u3"}]},
    ]
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        result = report_agent.reduce_summaries(
            {"job_type": "topic", "chunk_summaries": summaries, "topic": "x"}
        )

    mock_get_llm.assert_not_called()
    merged = result["chunk_summaries"][0]
    assert len(merged["facts"]) == 2
    assert len(merged["conclusions"]) == 1
    assert result["processing_notes"]["reduce_items_trimmed"] == 0


# ---------- compose_report ----------

def test_compose_report_channel_returns_empty_html():
    state = {"job_type": "channel", "chunk_summaries": [{"a": 1}], "statistics": {}, "topic": "x"}
    assert report_agent.compose_report(state) == {"final_html": ""}


def test_compose_report_no_summaries_returns_placeholder():
    state = {"job_type": "topic", "chunk_summaries": [], "statistics": {}, "topic": "x"}
    result = report_agent.compose_report(state)
    assert "No transcript data" in result["final_html"]


def test_compose_report_invokes_llm():
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("<section>Report body</section>")
        state = {
            "job_type": "topic",
            "chunk_summaries": [{"themes": ["t"]}],
            "statistics": {"video_count": 1},
            "topic": "x",
        }
        result = report_agent.compose_report(state)

    # Composition is sectioned now (S-1.14.8), so the body is assembled from
    # per-section calls plus a deterministic Statistics block.
    assert "<section>Report body</section>" in result["final_html"]
    assert "Statistics" in result["final_html"]


def test_compose_report_returns_error_html_on_failure():
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("boom")
        mock_get_llm.return_value = llm

        state = {
            "job_type": "topic",
            "chunk_summaries": [{"x": 1}],
            "statistics": {},
            "topic": "x",
        }
        result = report_agent.compose_report(state)

    assert "Report generation failed" in result["final_html"]


# ---------- Graph routing ----------

def test_route_after_statistics_routes_channel_to_compose_channel():
    """Channel jobs go to the lightweight per-channel narrative path."""
    assert report_agent.route_after_statistics({"job_type": "channel"}) == "compose_channel_report"


def test_route_after_statistics_routes_topic_to_map():
    assert report_agent.route_after_statistics({"job_type": "topic"}) == "map_chunks"


def test_run_report_agent_channel_returns_narrative_body():
    """Full graph run for a channel job: stats + a lightweight LLM-composed narrative."""
    chunks = [_chunk("v1", "ChA", 0.0, 60.0, word_count=10)]
    # Channel jobs invoke get_llm_for twice: once per channel for CHANNEL_MAP_PROMPT,
    # then once more for the cross-channel composition.
    fake_llms = [
        _fake_llm_returning('{"channel_name": "ChA", "themes": ["t"], "highlights": []}'),
        _fake_llm_returning("<section>Channel narrative</section>"),
    ]
    with patch.object(report_agent, "get_llm_for", side_effect=fake_llms):
        stats, body = report_agent.run_report_agent(
            job_type="channel", topic="", transcript_chunks=chunks
        )
    assert stats["video_count"] == 1
    assert "Channel narrative" in body

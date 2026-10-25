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
           video_title: str = "A Video", document_words: int | None = None) -> dict:
    meta = {
        "video_id": video_id,
        "video_title": video_title,
        "channel_name": channel,
        "channel_id": f"UC_{channel}",
        "timestamp_start": ts_start,
        "timestamp_end": ts_end,
        "word_count": word_count if word_count is not None else len(text.split()),
    }
    if document_words is not None:
        meta["document_word_count"] = document_words
    return {"text": text, "metadata": meta}


# Two documents of real sentences, short enough that chunk_size=40 /
# chunk_overlap=16 packs several per chunk and repeats one at each boundary.
_SPEECH = {
    "vidA": [
        "Seaborn wraps Matplotlib.",
        "It adds statistical defaults.",
        "A box plot shows the median.",
        "It also shows the quartiles.",
        "Violin plots add the density.",
        "Swarm plots show every point.",
        "Pair plots compare many columns.",
        "Heat maps show correlations.",
    ],
    "vidB": [
        "Matplotlib controls the figure.",
        "Subplots share one axis.",
        "Tick labels can be rotated.",
        "Legends can sit outside the axes.",
        "Styles change every default.",
        "Savefig writes the image.",
    ],
}


def _real_chunks(with_frames: bool) -> list[dict]:
    """Chunks built the way the job builds them: `chunk_transcript` over the
    transcript, with `[VISUAL @ ...]` annotations merged first on a visual run."""
    from types import SimpleNamespace

    from app.services.visual_service import annotate_segments
    from app.utils.chunking import chunk_transcript

    chunks: list[dict] = []
    for vid, sentences in _SPEECH.items():
        segments = [{"text": s, "start": i * 5.0, "duration": 5.0} for i, s in enumerate(sentences)]
        if with_frames:
            frames = [
                SimpleNamespace(
                    timestamp_seconds=t, informative=True, status="described",
                    description=f"A notebook cell at {t:.0f} seconds plots tips by day and by time.",
                )
                for t in (6.0, 16.0)
            ]
            segments = annotate_segments(segments, frames)
        chunks.extend(chunk_transcript(
            segments, chunk_size=40, chunk_overlap=16,
            video_metadata={"video_id": vid, "channel_name": f"chan-{vid}", "title": vid},
        ))
    return chunks


_SPOKEN = {vid: sum(len(s.split()) for s in sentences) for vid, sentences in _SPEECH.items()}


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
    # Each document's own count is read once, however many chunks carry it
    # (summing the chunks' `word_count` would give 380).
    chunks = [
        _chunk("v1", "ChA", 0.0, 60.0, word_count=100, document_words=170),
        _chunk("v1", "ChA", 60.0, 120.0, word_count=80, document_words=170),
        _chunk("v2", "ChB", 0.0, 300.0, word_count=200, document_words=200),
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    stats = result["statistics"]

    assert stats["video_count"] == 2
    assert stats["transcript_count"] == 2
    assert stats["total_words"] == 370


def test_compute_statistics_builds_channel_breakdown():
    chunks = [
        _chunk("v1", "ChA", 0.0, 60.0, document_words=100),
        _chunk("v2", "ChA", 0.0, 120.0, document_words=50),
        _chunk("v3", "ChB", 0.0, 600.0, document_words=200),
    ]
    result = report_agent.compute_statistics({"transcript_chunks": chunks})
    breakdown = {ch["channel_name"]: ch for ch in result["statistics"]["channel_breakdown"]}

    assert "ChA" in breakdown
    assert "ChB" in breakdown
    assert breakdown["ChA"]["video_count"] == 2
    assert breakdown["ChB"]["video_count"] == 1
    # Each channel's words are its documents' words.
    assert breakdown["ChA"]["word_count"] == 150
    assert breakdown["ChB"]["word_count"] == 200


def test_compute_statistics_counts_words_once_per_document_not_per_chunk():
    """Overlapping chunks and `[VISUAL @ ...]` spans must not inflate the count.

    The old code summed each chunk's `word_count`: every overlap region twice
    (the 200-video reference job said 1,057,331 words for 947,239) and, on a
    visual run, the descriptions as well (R1 run 10: 55,443 for 42,999).
    """
    chunks = _real_chunks(with_frames=True)
    # The fixture exercises both defects, so the summing code fails here:
    # the plain run's chunks over-count by the overlap, the visual run's by
    # the descriptions on top.
    plain_sum = sum(c["metadata"]["word_count"] for c in _real_chunks(with_frames=False))
    assert plain_sum > sum(_SPOKEN.values())
    assert sum(c["metadata"]["word_count"] for c in chunks) > plain_sum
    assert any("[VISUAL @" in c["text"] for c in chunks)

    stats = report_agent.compute_statistics({"transcript_chunks": chunks})["statistics"]
    assert stats["total_words"] == sum(_SPOKEN.values())
    breakdown = {row["channel_name"]: row["word_count"] for row in stats["channel_breakdown"]}
    assert breakdown == {f"chan-{vid}": n for vid, n in _SPOKEN.items()}


def test_compute_statistics_rebuilds_a_document_from_unstamped_chunks():
    """Chunks from before `document_word_count`: the document is put back
    together in order without its overlap, and the descriptions dropped."""
    chunks = _real_chunks(with_frames=True)
    for chunk in chunks:
        del chunk["metadata"]["document_word_count"]
    chunks.reverse()   # order comes from chunk_index, not list position

    stats = report_agent.compute_statistics({"transcript_chunks": chunks})["statistics"]
    assert stats["total_words"] == sum(_SPOKEN.values())


def test_run_report_agent_reports_the_spoken_word_count():
    """At the production caller: the statistics the job stores and renders."""
    chunks = _real_chunks(with_frames=True)
    fake_llms = [
        _fake_llm_returning('{"channel_name": "chan-vidA", "themes": ["t"], "highlights": []}'),
        _fake_llm_returning('{"channel_name": "chan-vidB", "themes": ["t"], "highlights": []}'),
        _fake_llm_returning("<section>Channel narrative</section>"),
    ]
    with patch.object(report_agent, "get_llm_for", side_effect=fake_llms):
        stats, _ = report_agent.run_report_agent(
            job_type="channel", topic="", transcript_chunks=chunks
        )
    assert stats["total_words"] == sum(_SPOKEN.values())
    assert f"Total words: {sum(_SPOKEN.values()):,}" in report_agent._render_statistics_html(stats)


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


def test_map_chunks_drops_a_non_json_response_and_says_so():
    # S-1.14.19: this used to come back as {"raw": ...}, count as a success,
    # and reach the composer as one unattributed fact. Now it is a failed
    # batch: dropped from the summaries and counted, so the report discloses it.
    chunks = [_chunk("v1", "ChA", 0.0, 60.0)]
    with patch.object(report_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("free-form text not json")
        result = report_agent.map_chunks(
            {"job_type": "topic", "transcript_chunks": chunks, "topic": "x"}
        )

    assert result["chunk_summaries"] == []
    notes = result["processing_notes"]
    assert (notes["map_batches_failed"], notes["map_chunks_dropped"]) == (1, 1)


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

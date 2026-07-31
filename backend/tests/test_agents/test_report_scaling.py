"""S-1.14.8 — report pipeline no longer starves itself.

D-055 measured the defect these guard: map emitted <=3,000 tokens per
~116K-token batch, reduce collapsed everything through a flat 6,000-token cap
on every pairwise round, and compose wrote the whole corpus in one call. The
shipped report for a 200-video job cited 2 channels out of 92.
"""
from unittest.mock import MagicMock, patch

from app.agents import report_agent as ra
from app.services.llm_routing import DEFAULT_MAX_OUTPUT_TOKENS, max_output_for


# --- output ceilings -------------------------------------------------------
def test_max_output_known_and_prefix_and_default() -> None:
    assert max_output_for("claude-sonnet-5") == 128_000
    assert max_output_for("gpt-5.4-nano") == 128_000
    assert max_output_for("claude-haiku-4-5") == 64_000
    # Dated snapshots resolve by longest-prefix match.
    assert max_output_for("claude-haiku-4-5-20251001") == 64_000
    # Unmeasured models fall back conservatively rather than over-promising.
    assert max_output_for("some-unknown-model") == DEFAULT_MAX_OUTPUT_TOKENS


def test_completion_budget_scales_with_work_and_clamps_to_ceiling() -> None:
    # Scales with the work in front of the call...
    assert ra._completion_budget("report_map_chunks", 120_000, 0.20) == 24_000
    # ...never below the floor for tiny batches...
    assert ra._completion_budget("report_map_chunks", 1_000, 0.20) == ra._MIN_COMPLETION_TOKENS
    # ...and never above the model's measured ceiling.
    huge = ra._completion_budget("report_map_chunks", 10_000_000, 0.20)
    assert huge == max_output_for("gpt-5.4-nano") == 128_000


def test_map_completion_budget_beats_the_old_constant() -> None:
    """The regression that mattered: 3,000 tokens for a ~116K-token batch."""
    budget = ra._batch_budget("report_map_chunks")
    assert ra._completion_budget("report_map_chunks", budget, ra._MAP_EXTRACTION_RATIO) > 3_000


# --- reduce: lossless, and never drops a whole video -----------------------
def _item(video: str, content: str, ts: int = 0) -> dict:
    return {
        "content": content,
        "video_title": f"title-{video}",
        "video_url": f"https://youtu.be/{video}",
        "channel_name": f"chan-{video}",
        "timestamp_seconds": ts,
    }


def test_reduce_is_lossless_when_under_budget() -> None:
    summaries = [
        {"facts": [_item("v1", "fact one"), _item("v2", "fact two")], "comments": []},
        {"facts": [_item("v3", "fact three")], "conclusions": [_item("v1", "concl")]},
    ]
    out = ra.reduce_summaries(
        {"chunk_summaries": summaries, "job_type": "topic", "topic": "t"}
    )
    merged = out["chunk_summaries"][0]
    assert len(merged["facts"]) == 3
    assert len(merged["conclusions"]) == 1
    assert out["processing_notes"]["reduce_items_trimmed"] == 0


def test_reduce_collapses_only_byte_identical_items() -> None:
    dup = _item("v1", "same fact", 10)
    summaries = [
        {"facts": [dup, _item("v2", "same fact", 10)]},  # same text, DIFFERENT video
        {"facts": [dict(dup)]},                          # true duplicate
    ]
    out = ra.reduce_summaries(
        {"chunk_summaries": summaries, "job_type": "topic", "topic": "t"}
    )
    merged = out["chunk_summaries"][0]
    # The same claim from a different source is distinct attribution — kept.
    assert len(merged["facts"]) == 2
    assert out["processing_notes"]["reduce_exact_duplicates_collapsed"] == 1


def test_reduce_never_makes_llm_calls_for_a_normal_corpus() -> None:
    summaries = [{"facts": [_item(f"v{i}", f"fact {i}")]} for i in range(50)]
    with patch.object(ra, "get_llm_for") as mock_llm:
        ra.reduce_summaries(
            {"chunk_summaries": summaries, "job_type": "topic", "topic": "t"}
        )
    mock_llm.assert_not_called()


def test_reduce_over_budget_keeps_every_video_represented() -> None:
    """The shipped failure mode was non-uniform: 46% of videos vanished."""
    summaries = [
        {"facts": [_item(f"v{v}", f"fact {v}-{n} " + "x" * 400) for n in range(20)]}
        for v in range(30)
    ]
    with patch.object(ra, "_MAX_COMPOSE_INPUT_TOKENS", 5_000):
        out = ra.reduce_summaries(
            {"chunk_summaries": summaries, "job_type": "topic", "topic": "t"}
        )
    merged = out["chunk_summaries"][0]
    videos = {ra._item_video(i) for i in merged["facts"]}
    assert len(videos) == 30, "every video must survive compression"
    assert out["processing_notes"]["reduce_items_trimmed"] > 0


def test_reduce_preserves_unparsed_map_output() -> None:
    """A map batch that failed JSON parsing must not silently vanish."""
    out = ra.reduce_summaries(
        {
            "chunk_summaries": [{"raw": "unparsed model text"}, {"facts": [_item("v1", "f")]}],
            "job_type": "topic",
            "topic": "t",
        }
    )
    merged = out["chunk_summaries"][0]
    assert any("unparsed model text" in str(f.get("content", "")) for f in merged["facts"])


# --- compose: sectioned, scaled, deterministic statistics ------------------
def test_compose_splits_sections_so_output_scales_with_corpus() -> None:
    big = {"facts": [_item(f"v{i}", "f " + "y" * 3_000) for i in range(60)]}
    calls: list = []

    def _fake_get_llm(use_case, **kw):
        calls.append(kw.get("max_tokens"))
        m = MagicMock()
        m.invoke.return_value = MagicMock(content="<h2>Key Facts</h2><p>x</p>")
        return m

    # Shrink the per-call input budget so the split is exercised without
    # building a 100K-token fixture.
    with patch.object(ra, "_QUALITY_BATCH_CAP", 5_000), \
            patch.object(ra, "get_llm_for", side_effect=_fake_get_llm):
        out = ra.compose_report(
            {
                "chunk_summaries": [big],
                "statistics": {"video_count": 60, "total_words": 1_000, "channel_breakdown": []},
                "job_type": "topic",
                "topic": "t",
            }
        )
    # One section fanned out across several calls => report length tracks
    # corpus size instead of being clipped by a single completion cap.
    assert len(calls) > 3
    assert "Key Facts" in out["final_html"]


def test_compose_renders_statistics_deterministically() -> None:
    """The LLM-written stats block undercounted the corpus by 31.5% (D-055)."""
    stats = {
        "video_count": 200,
        "transcript_count": 200,
        "total_words": 1_057_331,
        "total_minutes": 9_000,
        "channel_breakdown": [
            {"channel_name": "IBM Technology", "video_count": 20, "word_count": 100_000, "minutes": 900},
            {"channel_name": "bycloud", "video_count": 13, "word_count": 34_048, "minutes": 300},
        ],
    }
    html = ra._render_statistics_html(stats)
    assert "200" in html and "1,057,331" in html
    assert "IBM Technology" in html and "bycloud" in html
    assert "Channels represented: 2" in html


def test_compose_discloses_reduce_trimming_in_the_report() -> None:
    """Silent narrowing is the defect; drops must surface to the reader."""
    with patch.object(ra, "get_llm_for") as mock:
        mock.return_value.invoke.return_value = MagicMock(content="<h2>Key Facts</h2>")
        out = ra.compose_report(
            {
                "chunk_summaries": [{"facts": [_item("v1", "f")]}],
                "statistics": {},
                "job_type": "topic",
                "topic": "t",
                "processing_notes": {
                    "reduce_items_trimmed": 120,
                    "reduce_videos_represented": 200,
                },
            }
        )
    assert "Processing note" in out["final_html"]
    assert "120" in out["final_html"]


def test_compose_survives_a_failed_section() -> None:
    state = {
        "chunk_summaries": [{"facts": [_item("v1", "f")], "comments": [_item("v2", "c")]}],
        "statistics": {},
        "job_type": "topic",
        "topic": "t",
    }
    calls = {"n": 0}

    def _flaky(use_case, **kw):
        calls["n"] += 1
        m = MagicMock()
        if calls["n"] == 1:
            m.invoke.side_effect = RuntimeError("boom")
        else:
            m.invoke.return_value = MagicMock(content="<h2>Analysis &amp; Commentary</h2>")
        return m

    with patch.object(ra, "get_llm_for", side_effect=_flaky):
        out = ra.compose_report(state)
    # One section died; the report still ships and says so.
    assert "Analysis" in out["final_html"]
    assert "failed to compose" in out["final_html"]


# --- S-1.14.9: citations must actually link --------------------------------
def test_map_chunk_header_carries_the_video_url() -> None:
    """MAP_CHUNK_PROMPT asks every item for a video_url, but nothing supplied
    one — so every report citation rendered as href="&t=123", a dead link."""
    captured: dict = {}

    def _fake(use_case, **kw):
        m = MagicMock()

        def _invoke(msgs):
            captured["prompt"] = msgs[0].content
            return MagicMock(content='{"facts": []}')

        m.invoke.side_effect = _invoke
        return m

    chunks = [{
        "text": "some transcript text",
        "metadata": {
            "video_title": "T", "channel_name": "C", "timestamp_start": 12,
            "video_url": "https://www.youtube.com/watch?v=abc12345678",
        },
    }]
    with patch.object(ra, "get_llm_for", side_effect=_fake):
        ra.map_chunks({"chunk_summaries": [], "transcript_chunks": chunks,
                       "job_type": "topic", "topic": "t"})
    assert "https://www.youtube.com/watch?v=abc12345678" in captured["prompt"]


def test_broken_anchors_are_unwrapped_but_real_links_survive() -> None:
    html = (
        '<p><a href="&t=0">0:00</a> dead, '
        '<a href="https://youtu.be/x?v=1&t=5">0:05</a> live, '
        '<a href="">1:00</a> empty</p>'
    )
    out, n = ra._strip_broken_links(html)
    assert n == 2
    assert 'href="https://youtu.be/x?v=1&t=5"' in out
    # Labels survive as plain text rather than as dead links.
    assert "0:00" in out and "1:00" in out
    assert 'href="&t=0"' not in out


def test_compose_output_contains_no_dead_links() -> None:
    with patch.object(ra, "get_llm_for") as mock:
        mock.return_value.invoke.return_value = MagicMock(
            content='<h2>Key Facts</h2><p><a href="&t=9">0:09</a></p>'
        )
        out = ra.compose_report({
            "chunk_summaries": [{"facts": [_item("v1", "f")]}],
            "statistics": {}, "job_type": "topic", "topic": "t",
        })
    assert 'href="&t=' not in out["final_html"]
    assert "0:09" in out["final_html"]

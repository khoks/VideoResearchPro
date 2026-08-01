"""Visual agent — selection filtering, parsing tolerance, vision plumbing.

Two themes:

1. **The budget guarantees are enforced in code, not requested in a prompt.**
   Every extra frame is real money and real bot-wall exposure (D-051), so
   spacing and caps are verified here rather than trusted to the model.
2. **Nothing fails silently.** An unparseable response yields zero moments
   and a log line, never a partial guess.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.visual_agent import (
    _enforce_spacing_and_cap,
    _parse_description,
    _parse_moments,
    transcript_window,
)


def _m(ts, reason="r"):
    return {"timestamp_seconds": ts, "reason": reason, "expected_content": ""}


# ---------------------------------------------------------------------------
# Selection parsing
# ---------------------------------------------------------------------------
def test_parse_moments_plain_array():
    out = _parse_moments('[{"timestamp_seconds": 132, "reason": "chart", "expected_content": "bar chart"}]')
    assert out == [{"timestamp_seconds": 132.0, "reason": "chart", "expected_content": "bar chart"}]


def test_parse_moments_tolerates_code_fence():
    raw = '```json\n[{"timestamp_seconds": 10, "reason": "slide"}]\n```'
    assert _parse_moments(raw)[0]["timestamp_seconds"] == 10.0


def test_parse_moments_recovers_an_array_wrapped_in_prose():
    """Losing a whole video's selection to a leading sentence would be a
    silent quality regression, not an error anyone would notice."""
    raw = 'Here are the moments:\n[{"timestamp_seconds": 5, "reason": "x"}]\nHope that helps!'
    assert len(_parse_moments(raw)) == 1


def test_parse_moments_returns_empty_on_garbage():
    assert _parse_moments("no json here") == []
    assert _parse_moments("") == []
    assert _parse_moments('{"not": "an array"}') == []


def test_parse_moments_drops_unusable_entries_rather_than_the_batch():
    raw = """[
      {"timestamp_seconds": 10, "reason": "ok"},
      {"timestamp_seconds": "abc", "reason": "bad type"},
      {"reason": "missing timestamp"},
      {"timestamp_seconds": -5, "reason": "negative"},
      "not an object"
    ]"""
    out = _parse_moments(raw)
    assert [m["timestamp_seconds"] for m in out] == [10.0]


def test_empty_selection_is_a_valid_answer():
    """A video of someone talking to a camera should cost zero vision calls."""
    assert _parse_moments("[]") == []


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------
def test_min_gap_is_enforced_even_when_the_model_ignores_it():
    out = _enforce_spacing_and_cap(
        [_m(0), _m(5), _m(10), _m(40)], max_frames=10, min_gap=20.0, duration=None
    )
    assert [m["timestamp_seconds"] for m in out] == [0, 40]


def test_cap_is_enforced_even_when_the_model_ignores_it():
    out = _enforce_spacing_and_cap(
        [_m(i * 100) for i in range(20)], max_frames=3, min_gap=20.0, duration=None
    )
    assert len(out) == 3


def test_moments_past_the_end_of_the_video_are_dropped():
    """ffmpeg seeking past the end produces no output and no error — the
    frame would just silently never appear."""
    out = _enforce_spacing_and_cap(
        [_m(10), _m(9999)], max_frames=10, min_gap=5.0, duration=600
    )
    assert [m["timestamp_seconds"] for m in out] == [10]


def test_moments_are_returned_in_timestamp_order():
    out = _enforce_spacing_and_cap(
        [_m(300), _m(100), _m(200)], max_frames=10, min_gap=20.0, duration=None
    )
    assert [m["timestamp_seconds"] for m in out] == [100, 200, 300]


# ---------------------------------------------------------------------------
# Description parsing
# ---------------------------------------------------------------------------
def test_parse_description_happy_path():
    out = _parse_description(
        '{"informative": true, "description": "a bar chart", '
        '"reads_as": "chart", "legibility": "clear"}'
    )
    assert out["informative"] is True
    assert out["description"] == "a bar chart"


def test_unreadable_frames_are_forced_uninformative():
    """A description the model itself called unreadable is not evidence.
    Promoting it lets 'roughly 40%?' become a cited figure downstream."""
    out = _parse_description(
        '{"informative": true, "description": "a chart, figures too blurry", '
        '"legibility": "unreadable"}'
    )
    assert out["informative"] is False


def test_informative_true_with_no_description_is_not_informative():
    out = _parse_description('{"informative": true, "description": ""}')
    assert out["informative"] is False


def test_parse_description_returns_none_on_garbage():
    assert _parse_description("sorry, I cannot see the image") is None
    assert _parse_description("") is None


def test_parse_description_tolerates_fence_and_prose():
    out = _parse_description('```json\n{"informative": false, "description": "a face"}\n```')
    assert out["informative"] is False


# ---------------------------------------------------------------------------
# Transcript window
# ---------------------------------------------------------------------------
def test_transcript_window_is_bounded_around_the_frame():
    segments = [{"text": f"line{i}", "start": i * 10, "duration": 10} for i in range(20)]
    window = transcript_window(segments, 100)
    assert "line10" in window       # at the frame
    assert "line7" in window        # -30s
    assert "line13" in window       # +30s
    assert "line5" not in window    # -50s, outside
    assert "line16" not in window   # +60s, outside


def test_transcript_window_marks_the_frame_position():
    """The describer has to know which line the picture belongs to; without
    the marker it averages over the whole window."""
    segments = [{"text": "as you can see", "start": 100, "duration": 5}]
    assert "<-- FRAME" in transcript_window(segments, 100)


def test_transcript_window_is_empty_when_nothing_is_nearby():
    assert transcript_window([{"text": "far away", "start": 0}], 5000) == ""


# ---------------------------------------------------------------------------
# Vision plumbing
# ---------------------------------------------------------------------------
def test_describe_frame_sends_an_actual_image_part():
    """The whole feature is worthless if the image never reaches the model —
    and a text-only call would still return a confident-sounding description
    reconstructed from the transcript."""
    from app.agents.visual_agent import describe_frame
    from app.services.frame_service import CapturedFrame

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(
        content='{"informative": true, "description": "a chart"}'
    )

    with patch("app.agents.visual_agent.get_llm_for", return_value=fake_llm), \
         patch("app.agents.visual_agent._encode_image", return_value="Zm9v"):
        describe_frame(
            video_title="T",
            frame=CapturedFrame(30.0, "/tmp/f.jpg", 1280, 720),
            moment={"reason": "chart", "expected_content": "bar chart"},
            segments=[{"text": "as you can see", "start": 30, "duration": 5}],
        )

    content = fake_llm.invoke.call_args[0][0][0].content
    assert isinstance(content, list)
    parts = {p["type"] for p in content}
    assert parts == {"text", "image_url"}
    image = next(p for p in content if p["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_describe_frame_uses_the_vision_use_case():
    from app.agents.visual_agent import describe_frame
    from app.services.frame_service import CapturedFrame

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content='{"informative": false, "description": "x"}')

    with patch("app.agents.visual_agent.get_llm_for", return_value=fake_llm) as gl, \
         patch("app.agents.visual_agent._encode_image", return_value="Zm9v"):
        describe_frame(
            video_title="T",
            frame=CapturedFrame(1.0, "/tmp/f.jpg", 100, 100),
            moment={},
            segments=[],
        )
    assert gl.call_args[0][0] == "visual_describe_frame"


def test_describe_frame_returns_none_when_the_image_is_unreadable():
    from app.agents.visual_agent import describe_frame
    from app.services.frame_service import CapturedFrame

    with patch("app.agents.visual_agent._encode_image", return_value=None):
        out = describe_frame(
            video_title="T",
            frame=CapturedFrame(1.0, "/nope.jpg", 1, 1),
            moment={},
            segments=[],
        )
    assert out is None


def test_select_moments_returns_empty_when_the_llm_raises():
    """Opt-in enrichment must never take down a job that would otherwise run."""
    from app.agents.visual_agent import select_moments

    with patch("app.agents.visual_agent.get_llm_for", side_effect=RuntimeError("down")):
        out = select_moments(
            video_title="T",
            channel_name="C",
            segments=[{"text": "hello", "start": 0, "duration": 5}],
            duration_seconds=600,
            max_frames=5,
        )
    assert out == []


def test_select_moments_skips_the_llm_entirely_for_an_empty_transcript():
    from app.agents.visual_agent import select_moments

    with patch("app.agents.visual_agent.get_llm_for") as gl:
        assert select_moments(
            video_title="T", channel_name="C", segments=[],
            duration_seconds=600, max_frames=5,
        ) == []
    gl.assert_not_called()


def test_a_failed_persist_rolls_back_rather_than_poisoning_the_session():
    """The caller shares this session with the extraction loop. A failed
    commit left unrolled-back makes every subsequent video in the job fail on
    an unrelated write — one bad visual persist becoming a dead job."""
    from app.agents.visual_agent import run_visual_agent
    from app.services.frame_service import CapturedFrame

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    db.commit.side_effect = RuntimeError("constraint violation")

    with patch("app.agents.visual_agent.select_moments",
               return_value=[{"timestamp_seconds": 10.0, "reason": "r",
                              "expected_content": ""}]), \
         patch("app.agents.visual_agent.frame_service.capture_frames",
               return_value=[CapturedFrame(10.0, "/tmp/f.jpg", 640, 360)]), \
         patch("app.agents.visual_agent.describe_frame",
               return_value={"informative": True, "description": "a chart",
                             "reads_as": "chart", "legibility": "clear"}):
        rows, spent = run_visual_agent(
            db, video_id="v1", video_title="T", channel_name="C",
            segments=[{"text": "hi", "start": 10, "duration": 5}],
        )

    db.rollback.assert_called_once()
    assert rows == []
    assert spent == 0


def test_already_processed_documents_report_zero_spend():
    """Reuse costs nothing, and the budget must be told so."""
    from app.agents.visual_agent import run_visual_agent

    existing = [MagicMock()]
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = existing

    with patch("app.agents.visual_agent.select_moments") as sel:
        rows, spent = run_visual_agent(
            db, video_id="v1", video_title="T", channel_name="C", segments=[],
        )
    assert rows == existing
    assert spent == 0
    sel.assert_not_called()

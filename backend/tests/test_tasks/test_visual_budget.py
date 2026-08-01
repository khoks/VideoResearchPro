"""The visual gate and the per-job frame budget.

Both halves of the gate exist for a reason and both are tested here:
the install-wide `VISUAL_ENABLED` switch (an operator's decision about cost
and bot-wall exposure) and `jobs.visual_analysis` (the user's). Either being
false must mean zero frames — a feature that adds video downloads to a
pipeline that has already been IP-blocked once (D-051) does not get to
default on.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.tasks.job_tasks import VisualBudget, _with_visuals


def _job(visual: bool = True):
    return SimpleNamespace(visual_analysis=visual)


def _video(source_type: str = "video"):
    return SimpleNamespace(
        video_id="v1", title="T", channel_name="C",
        duration_seconds=600, source_type=source_type,
    )


SEGMENTS = [{"text": "hello", "start": 0, "duration": 5}]


# ---------------------------------------------------------------------------
# Budget arithmetic
# ---------------------------------------------------------------------------
def test_budget_hands_out_no_more_than_it_has():
    b = VisualBudget(10)
    assert b.take(4) == 4
    assert b.take(4) == 4
    assert b.take(4) == 2
    assert b.take(4) == 0


def test_budget_of_zero_grants_nothing():
    assert VisualBudget(0).take(5) == 0


def test_negative_budget_is_clamped():
    assert VisualBudget(-5).remaining == 0


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("enabled,opted_in", [(False, True), (True, False), (False, False)])
def test_both_halves_of_the_gate_are_required(enabled, opted_in):
    with patch("app.config.settings.VISUAL_ENABLED", enabled), \
         patch("app.agents.visual_agent.run_visual_agent") as run:
        out = _with_visuals(
            None, _job(opted_in), _video(), SEGMENTS, VisualBudget(100), "j1"
        )
    assert out is SEGMENTS
    run.assert_not_called()


def test_no_budget_object_means_no_visual_work():
    """Call sites that predate the feature pass None; they must be inert."""
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.agents.visual_agent.run_visual_agent") as run:
        assert _with_visuals(None, _job(True), _video(), SEGMENTS, None, "j1") is SEGMENTS
    run.assert_not_called()


def test_non_video_sources_are_skipped():
    """A Reddit thread has no video stream to seek into."""
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.agents.visual_agent.run_visual_agent") as run:
        out = _with_visuals(
            None, _job(True), _video("reddit_post"), SEGMENTS, VisualBudget(100), "j1"
        )
    assert out is SEGMENTS
    run.assert_not_called()


# ---------------------------------------------------------------------------
# Budget behaviour across a job
# ---------------------------------------------------------------------------
def test_unused_allowance_is_returned_to_the_pool():
    """A talking-head video must not consume budget the next video could
    have spent — otherwise a corpus of mostly-plain videos exhausts the job
    cap on documents that produced nothing."""
    budget = VisualBudget(24)
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.config.settings.VISUAL_MAX_FRAMES_PER_VIDEO", 12), \
         patch("app.agents.visual_agent.run_visual_agent", return_value=([], 0)), \
         patch("app.services.visual_service.annotate_segments", side_effect=lambda s, f: s):
        _with_visuals(None, _job(), _video(), SEGMENTS, budget, "j1")
    assert budget.remaining == 24


def test_used_allowance_is_consumed():
    budget = VisualBudget(24)
    frames = [SimpleNamespace(status="described", informative=True, description="x",
                              timestamp_seconds=float(i)) for i in range(12)]
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.config.settings.VISUAL_MAX_FRAMES_PER_VIDEO", 12), \
         patch("app.agents.visual_agent.run_visual_agent", return_value=(frames, len(frames))):
        _with_visuals(None, _job(), _video(), SEGMENTS, budget, "j1")
    assert budget.remaining == 12


def test_budget_exhaustion_stops_further_work():
    budget = VisualBudget(0)
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.agents.visual_agent.run_visual_agent") as run:
        out = _with_visuals(None, _job(), _video(), SEGMENTS, budget, "j1")
    assert out is SEGMENTS
    run.assert_not_called()


def test_exhaustion_is_announced_once_not_per_video(caplog):
    """Silent exhaustion is indistinguishable from 'the selector found
    nothing' — but 200 identical warnings is its own kind of unreadable."""
    budget = VisualBudget(0)
    with patch("app.config.settings.VISUAL_ENABLED", True), caplog.at_level("WARNING"):
        for _ in range(5):
            _with_visuals(None, _job(), _video(), SEGMENTS, budget, "j1")
    assert sum("budget exhausted" in r.message for r in caplog.records) == 1


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------
def test_a_visual_failure_does_not_break_the_job():
    """Opt-in enrichment on top of a working product. A job that would have
    completed must still complete."""
    budget = VisualBudget(24)
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.agents.visual_agent.run_visual_agent",
               side_effect=RuntimeError("yt-dlp blocked")):
        out = _with_visuals(None, _job(), _video(), SEGMENTS, budget, "j1")
    assert out is SEGMENTS
    # And the allowance goes back — one blocked video must not silently
    # shrink the budget available to the rest of the corpus.
    assert budget.remaining == 24


def test_reused_frames_do_not_consume_the_budget():
    """Re-running a job over an already-processed corpus costs nothing.

    Charging for reuse would exhaust a 200-frame job budget on the first ~16
    videos and silently drop annotations from the remaining 90% — a
    regression visible only as a report that quietly says less than last time.
    """
    budget = VisualBudget(24)
    frames = [SimpleNamespace(status="described", informative=True, description="x",
                              timestamp_seconds=float(i)) for i in range(12)]
    with patch("app.config.settings.VISUAL_ENABLED", True), \
         patch("app.config.settings.VISUAL_MAX_FRAMES_PER_VIDEO", 12), \
         patch("app.agents.visual_agent.run_visual_agent", return_value=(frames, 0)):
        _with_visuals(None, _job(), _video(), SEGMENTS, budget, "j1")
    assert budget.remaining == 24

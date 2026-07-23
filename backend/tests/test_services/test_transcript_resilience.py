"""E-1.11 / D-051 — transcript-pipeline resilience unit tests.

Covers the pure-logic pieces: the IP-block circuit breaker state machine,
the segmented-Whisper merge (offset-adjusted timestamps + midpoint-ownership
dedup), and search pagination page math. Network paths (yt-dlp, Whisper,
ffmpeg) are exercised live, not here.
"""
from unittest.mock import patch

from app.services import youtube_service
from app.services.youtube_service import (
    _merge_chunk_transcripts,
    _TranscriptCircuitBreaker,
)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_breaker_stays_closed_below_threshold():
    b = _TranscriptCircuitBreaker()
    b.record_block()
    b.record_block()
    assert b.wait_if_open() is True  # threshold (3) not reached — closed


def test_breaker_opens_at_threshold_and_skips_long_waits(monkeypatch):
    b = _TranscriptCircuitBreaker()
    for _ in range(3):
        b.record_block()
    # Cooldown base is 120s > MAX_WAIT would be False only when remaining
    # exceeds TRANSCRIPT_BREAKER_MAX_WAIT (300) — 120 < 300, so the breaker
    # would sleep. Patch sleep to observe without waiting.
    slept = {}
    monkeypatch.setattr(
        youtube_service.time, "sleep", lambda s: slept.setdefault("s", s)
    )
    assert b.wait_if_open() is True
    assert 0 < slept["s"] <= 120


def test_breaker_cooldown_doubles_and_caps(monkeypatch):
    b = _TranscriptCircuitBreaker()
    monkeypatch.setattr(youtube_service.settings, "TRANSCRIPT_BREAKER_THRESHOLD", 1)
    monkeypatch.setattr(youtube_service.settings, "TRANSCRIPT_BREAKER_COOLDOWN_BASE", 100.0)
    monkeypatch.setattr(youtube_service.settings, "TRANSCRIPT_BREAKER_COOLDOWN_MAX", 250.0)
    b.record_block()
    assert b._current_cooldown == 100.0
    b.record_block()
    assert b._current_cooldown == 200.0
    b.record_block()
    assert b._current_cooldown == 250.0  # capped


def test_breaker_success_resets():
    b = _TranscriptCircuitBreaker()
    for _ in range(5):
        b.record_block()
    b.record_success()
    assert b.wait_if_open() is True
    assert b._consecutive_blocks == 0
    assert b._current_cooldown == 0.0


def test_breaker_returns_false_when_wait_exceeds_cap(monkeypatch):
    b = _TranscriptCircuitBreaker()
    monkeypatch.setattr(youtube_service.settings, "TRANSCRIPT_BREAKER_THRESHOLD", 1)
    monkeypatch.setattr(
        youtube_service.settings, "TRANSCRIPT_BREAKER_COOLDOWN_BASE", 600.0
    )
    monkeypatch.setattr(youtube_service.settings, "TRANSCRIPT_BREAKER_MAX_WAIT", 300.0)
    b.record_block()
    assert b.wait_if_open() is False  # 600s remaining > 300s cap → skip video


# ---------------------------------------------------------------------------
# Segmented-Whisper merge (S-1.11.2 — user-specified design)
# ---------------------------------------------------------------------------


def _seg(text: str, start: float, duration: float = 2.0) -> dict:
    return {"text": text, "start": start, "duration": duration}


def test_merge_adjusts_timestamps_by_chunk_offset():
    # Two 100s chunks, 10s overlap. Chunk 1's audio covers 0-110s,
    # chunk 2's covers 100-200s (its segment starts are chunk-relative).
    per_chunk = [
        (0.0, 100.0, [_seg("a", 5.0), _seg("b", 50.0)]),
        (100.0, 100.0, [_seg("c", 10.0), _seg("d", 80.0)]),
    ]
    merged = _merge_chunk_transcripts(per_chunk, overlap=10.0, tag="")
    starts = {s["text"]: s["start"] for s in merged}
    assert starts["a"] == 5.0
    assert starts["b"] == 50.0
    assert starts["c"] == 110.0  # 10 + 100 offset
    assert starts["d"] == 180.0


def test_merge_dedups_overlap_zone_by_midpoint_ownership():
    # Overlap zone between chunk 0 and chunk 1 spans 100-110s (overlap=10).
    # Midpoint boundary at 105s: chunk 0 owns [0,105), chunk 1 owns [105,∞).
    per_chunk = [
        # chunk 0 heard the overlap-zone words at 102s and 107s (absolute)
        (0.0, 100.0, [_seg("early", 50.0), _seg("dup1", 102.0), _seg("dup2", 107.0)]),
        # chunk 1 heard the same words at 2s and 7s chunk-relative (=102/107 abs)
        (100.0, 100.0, [_seg("dup1", 2.0), _seg("dup2", 7.0), _seg("late", 50.0)]),
    ]
    merged = _merge_chunk_transcripts(per_chunk, overlap=10.0, tag="")
    texts = [s["text"] for s in merged]
    # dup1 (abs 102 < 105) owned by chunk 0; dup2 (abs 107 >= 105) by chunk 1.
    assert texts.count("dup1") == 1
    assert texts.count("dup2") == 1
    assert texts == ["early", "dup1", "dup2", "late"]


def test_merge_output_sorted_by_start():
    per_chunk = [
        (0.0, 60.0, [_seg("b", 30.0), _seg("a", 10.0)]),
        (60.0, 60.0, [_seg("c", 20.0)]),
    ]
    merged = _merge_chunk_transcripts(per_chunk, overlap=0.0, tag="")
    assert [s["text"] for s in merged] == ["a", "b", "c"]
    assert [s["start"] for s in merged] == [10.0, 30.0, 80.0]


# ---------------------------------------------------------------------------
# Search pagination (S-1.11.5)
# ---------------------------------------------------------------------------


def _fake_page(ids: list[str], next_token: str | None) -> dict:
    return {
        "items": [
            {
                "id": {"videoId": vid},
                "snippet": {
                    "title": f"t-{vid}",
                    "channelTitle": "ch",
                    "channelId": "UC1",
                    "publishedAt": None,
                    "thumbnails": {},
                },
            }
            for vid in ids
        ],
        "nextPageToken": next_token,
    }


def test_search_videos_paginates_up_to_max_pages(monkeypatch):
    monkeypatch.setattr(youtube_service.settings, "YOUTUBE_SEARCH_MAX_PAGES", 2)
    pages = [
        _fake_page([f"v{i}" for i in range(50)], "TOK2"),
        _fake_page([f"w{i}" for i in range(50)], "TOK3"),
        _fake_page([f"x{i}" for i in range(50)], None),
    ]
    calls = []

    def fake_execute(request, operation):
        calls.append(operation)
        return pages[len(calls) - 1]

    with patch.object(youtube_service, "get_youtube_client") as gc, patch.object(
        youtube_service, "_execute_youtube_request", side_effect=fake_execute
    ):
        gc.return_value.search.return_value.list.return_value = object()
        result = youtube_service.search_videos("query", max_results=150)

    assert len(calls) == 2  # page cap enforced despite max_results=150
    assert len(result) == 100


def test_search_videos_stops_early_when_satisfied(monkeypatch):
    monkeypatch.setattr(youtube_service.settings, "YOUTUBE_SEARCH_MAX_PAGES", 4)
    pages = [_fake_page([f"v{i}" for i in range(50)], "TOK2")]
    calls = []

    def fake_execute(request, operation):
        calls.append(operation)
        return pages[len(calls) - 1]

    with patch.object(youtube_service, "get_youtube_client") as gc, patch.object(
        youtube_service, "_execute_youtube_request", side_effect=fake_execute
    ):
        gc.return_value.search.return_value.list.return_value = object()
        result = youtube_service.search_videos("query", max_results=30)

    assert len(calls) == 1  # first page already satisfies max_results
    assert len(result) == 30

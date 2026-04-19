from app.utils.chunking import chunk_transcript


def _make_segments(count: int, words_per_seg: int = 50) -> list[dict]:
    """Generate fake transcript segments."""
    segments = []
    for i in range(count):
        text = " ".join([f"word{i}_{j}" for j in range(words_per_seg)])
        segments.append({
            "text": text,
            "start": i * 10.0,
            "duration": 10.0,
        })
    return segments


def test_empty_transcript():
    assert chunk_transcript([]) == []


def test_single_segment():
    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(segs, chunk_size=100)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "Hello world"
    assert chunks[0]["metadata"]["timestamp_start"] == 0.0
    assert chunks[0]["metadata"]["chunk_index"] == 0
    assert chunks[0]["metadata"]["total_chunks"] == 1


def test_metadata_attached():
    segs = [{"text": "Test transcript", "start": 0.0, "duration": 5.0}]
    meta = {
        "video_id": "abc123",
        "title": "Test Video",
        "channel_name": "TestCh",
        "channel_id": "UCxxx",
        "url": "https://youtube.com/watch?v=abc123",
    }
    chunks = chunk_transcript(segs, video_metadata=meta)
    assert chunks[0]["metadata"]["video_id"] == "abc123"
    assert chunks[0]["metadata"]["video_title"] == "Test Video"
    assert chunks[0]["metadata"]["channel_name"] == "TestCh"


def test_multiple_segments_split_into_chunks():
    # Many segments should produce multiple chunks
    segs = _make_segments(50, words_per_seg=50)
    chunks = chunk_transcript(segs, chunk_size=200, chunk_overlap=20)
    assert len(chunks) > 1
    # All chunks have timestamps
    for chunk in chunks:
        assert "timestamp_start" in chunk["metadata"]
        assert "timestamp_end" in chunk["metadata"]
        assert chunk["metadata"]["timestamp_start"] >= 0


def test_chunk_indices_sequential():
    segs = _make_segments(20, words_per_seg=50)
    chunks = chunk_transcript(segs, chunk_size=200, chunk_overlap=20)
    for i, chunk in enumerate(chunks):
        assert chunk["metadata"]["chunk_index"] == i
        assert chunk["metadata"]["total_chunks"] == len(chunks)


def test_empty_text_segments_skipped():
    segs = [
        {"text": "", "start": 0.0, "duration": 5.0},
        {"text": "  ", "start": 5.0, "duration": 5.0},
        {"text": "Actual content", "start": 10.0, "duration": 5.0},
    ]
    chunks = chunk_transcript(segs)
    assert len(chunks) == 1
    assert "Actual content" in chunks[0]["text"]


def test_chunk_start_uses_actual_segment_time_not_offset():
    """Regression: current_start must be the first overlap segment's start
    time, not `seg_start - 1`. Previous code could emit a start time that
    didn't correspond to any real segment (and could even go negative)."""
    segs = _make_segments(50, words_per_seg=50)
    chunks = chunk_transcript(segs, chunk_size=200, chunk_overlap=20)
    valid_starts = {float(i * 10) for i in range(50)}
    for chunk in chunks:
        ts = chunk["metadata"]["timestamp_start"]
        assert ts >= 0
        # Must be an actual segment start we generated, not seg_start - 1.
        assert ts in valid_starts, f"timestamp_start {ts} is not an actual segment start"


def test_sentence_boundary_preferred():
    """Long segments with sentence terminators should be split on sentences."""
    # One giant segment that holds many sentences.
    long_text = " ".join(f"Sentence number {i} goes here." for i in range(40))
    segs = [{"text": long_text, "start": 0.0, "duration": 120.0}]
    chunks = chunk_transcript(segs, chunk_size=50, chunk_overlap=5)
    assert len(chunks) > 1
    # Each chunk should end with a sentence terminator (we split on .!?).
    for chunk in chunks:
        assert chunk["text"].rstrip().endswith((".", "!", "?"))


def test_fallback_when_no_sentence_boundary():
    """Segments with no sentence terminators should still chunk (greedy fallback)."""
    # 30 segments, none ending in punctuation.
    segs = [
        {"text": " ".join(f"word{i}_{j}" for j in range(40)), "start": i * 5.0, "duration": 5.0}
        for i in range(30)
    ]
    chunks = chunk_transcript(segs, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert all(chunk["text"] for chunk in chunks)


def test_published_at_and_duration_in_metadata():
    from datetime import datetime, timezone

    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    meta = {
        "video_id": "abc123",
        "title": "Test",
        "channel_name": "Ch",
        "channel_id": "UCx",
        "url": "https://youtube.com/watch?v=abc123",
        "published_at": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "duration_seconds": 600,
    }
    chunks = chunk_transcript(segs, video_metadata=meta)
    assert chunks[0]["metadata"]["published_at"] == "2024-01-15T12:00:00+00:00"
    assert chunks[0]["metadata"]["duration_seconds"] == 600


def test_published_at_missing_defaults_to_empty_string():
    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(segs, video_metadata={"video_id": "x"})
    assert chunks[0]["metadata"]["published_at"] == ""
    assert chunks[0]["metadata"]["duration_seconds"] == 0


def test_published_at_accepts_iso_string():
    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    meta = {"video_id": "x", "published_at": "2024-06-01T00:00:00Z", "duration_seconds": 42}
    chunks = chunk_transcript(segs, video_metadata=meta)
    assert chunks[0]["metadata"]["published_at"] == "2024-06-01T00:00:00Z"
    assert chunks[0]["metadata"]["duration_seconds"] == 42

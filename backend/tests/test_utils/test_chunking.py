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

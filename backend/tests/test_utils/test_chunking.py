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


def test_transcription_source_defaults_to_youtube():
    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(segs, video_metadata={"video_id": "x"})
    assert chunks[0]["metadata"]["transcription_source"] == "youtube"


def test_transcription_source_whisper_propagated():
    segs = [{"text": "Hola mundo", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(
        segs,
        video_metadata={"video_id": "x", "language": "es"},
        transcription_source="whisper",
    )
    assert chunks[0]["metadata"]["transcription_source"] == "whisper"
    assert chunks[0]["metadata"]["language"] == "es"


def test_language_preserved_from_metadata_not_hardcoded_en():
    """Non-English transcripts (Hindi, Urdu, Russian, etc.) must keep their
    language tag through chunking rather than being silently reset to 'en'."""
    segs = [{"text": "नमस्ते दुनिया", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(segs, video_metadata={"video_id": "x", "language": "hi"})
    assert chunks[0]["metadata"]["language"] == "hi"


def test_language_defaults_to_unknown_when_missing():
    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(segs, video_metadata={"video_id": "x"})
    assert chunks[0]["metadata"]["language"] == "unknown"


# ---------------------------------------------------------------------------
# Polymorphic per-document fields (M-1.5 / M-1.6 follow-up)
# ---------------------------------------------------------------------------
# These tests lock in the contract that every chunk carries the
# polymorphic source-type fields the Q&A agent's `_chunk_to_reference`
# reads. Before this PR, social-media chunks (Reddit / HN / Mastodon /
# Bluesky) lost their source identity at the chunking layer and ended
# up rendering as YouTube citations in production despite the
# frontend rendering contract being in place since PR #117.


def test_polymorphic_fields_default_to_video_when_missing():
    """Legacy callers that don't pass source_type still get a sensible
    default — `_chunk_to_reference` falls through the YouTube branch."""
    segs = [{"text": "Hello world", "start": 0.0, "duration": 5.0}]
    chunks = chunk_transcript(segs, video_metadata={"video_id": "x"})
    md = chunks[0]["metadata"]
    assert md["source_type"] == "video"
    assert md["source_id"] == ""
    assert md["source_url"] == ""
    assert md["permalink"] == ""
    assert md["author"] == ""
    assert md["subreddit"] == ""
    assert md["instance"] == ""


def test_reddit_polymorphic_fields_propagate_to_chunk_metadata():
    """A Reddit document's source_type / permalink / subreddit / author
    must reach Chroma so qa_agent renders the citation correctly."""
    segs = [{"text": "Reddit thread body", "start": 0.0, "duration": 5.0}]
    meta = {
        "video_id": "reddit:abc",
        "title": "Why tariffs are bad",
        "source_type": "reddit_post",
        "source_id": "reddit:abc",
        "source_url": "https://www.reddit.com/r/economics/comments/abc",
        "permalink": "https://www.reddit.com/r/economics/comments/abc",
        "subreddit": "economics",
        "author": "supply_chain_pro",
    }
    chunks = chunk_transcript(segs, video_metadata=meta)
    md = chunks[0]["metadata"]
    assert md["source_type"] == "reddit_post"
    assert md["source_id"] == "reddit:abc"
    assert md["permalink"] == "https://www.reddit.com/r/economics/comments/abc"
    assert md["subreddit"] == "economics"
    assert md["author"] == "supply_chain_pro"


def test_hn_polymorphic_fields_propagate_to_chunk_metadata():
    segs = [{"text": "HN story body", "start": 0.0, "duration": 5.0}]
    meta = {
        "video_id": "hn:42000",
        "title": "Caching strategies",
        "source_type": "hn_story",
        "source_id": "hn:42000",
        "source_url": "https://news.ycombinator.com/item?id=42000",
        "permalink": "https://news.ycombinator.com/item?id=42000",
        "author": "throwaway_dev",
    }
    chunks = chunk_transcript(segs, video_metadata=meta)
    md = chunks[0]["metadata"]
    assert md["source_type"] == "hn_story"
    assert md["permalink"] == "https://news.ycombinator.com/item?id=42000"
    assert md["author"] == "throwaway_dev"
    # Reddit-only field should still serialize as empty for HN.
    assert md["subreddit"] == ""


def test_mastodon_polymorphic_fields_propagate_to_chunk_metadata():
    segs = [{"text": "Status body", "start": 0.0, "duration": 5.0}]
    meta = {
        "video_id": "mastodon:111222",
        "title": "Federated identity",
        "source_type": "mastodon_post",
        "source_id": "mastodon:111222",
        "source_url": "https://mastodon.social/@privacynerd/111222",
        "permalink": "https://mastodon.social/@privacynerd/111222",
        "author": "privacynerd",
        "instance": "mastodon.social",
    }
    chunks = chunk_transcript(segs, video_metadata=meta)
    md = chunks[0]["metadata"]
    assert md["source_type"] == "mastodon_post"
    assert md["permalink"] == "https://mastodon.social/@privacynerd/111222"
    assert md["author"] == "privacynerd"
    assert md["instance"] == "mastodon.social"


def test_bluesky_polymorphic_fields_propagate_to_chunk_metadata():
    segs = [{"text": "Post body", "start": 0.0, "duration": 5.0}]
    meta = {
        "video_id": "bluesky:at://did:plc:abc/app.bsky.feed.post/100",
        "title": "AT-Proto thoughts",
        "source_type": "bluesky_post",
        "source_id": "bluesky:at://did:plc:abc/app.bsky.feed.post/100",
        "source_url": "https://bsky.app/profile/alice.bsky.social/post/100",
        "permalink": "https://bsky.app/profile/alice.bsky.social/post/100",
        "author": "alice.bsky.social",
    }
    chunks = chunk_transcript(segs, video_metadata=meta)
    md = chunks[0]["metadata"]
    assert md["source_type"] == "bluesky_post"
    assert md["permalink"] == "https://bsky.app/profile/alice.bsky.social/post/100"
    assert md["author"] == "alice.bsky.social"


def test_polymorphic_fields_present_on_every_chunk():
    """Multi-chunk documents — each chunk in the result must carry the
    polymorphic block, not just the first."""
    segs = _make_segments(20, words_per_seg=50)
    meta = {
        "video_id": "reddit:abc",
        "source_type": "reddit_post",
        "permalink": "https://www.reddit.com/r/x/comments/abc",
        "subreddit": "x",
        "author": "user",
    }
    chunks = chunk_transcript(segs, video_metadata=meta, chunk_size=200, chunk_overlap=20)
    assert len(chunks) > 1  # ensure we have multi-chunk coverage
    for c in chunks:
        md = c["metadata"]
        assert md["source_type"] == "reddit_post"
        assert md["subreddit"] == "x"
        assert md["author"] == "user"
        assert md["permalink"].startswith("https://")

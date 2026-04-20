import logging
import re

import tiktoken

logger = logging.getLogger(__name__)

# Matches a sentence terminator (. ! ?) followed by whitespace.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))


def _split_into_sentences(text: str) -> list[str]:
    """Split a segment's text into sentences on .!? boundaries.

    Returns the original text as a single-element list if no boundary is found.
    Empty fragments are discarded.
    """
    parts = [p.strip() for p in _SENTENCE_BOUNDARY_RE.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _expand_segments_to_sentences(
    segments: list[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    """Expand transcript segments into sentence-level sub-segments.

    Timestamps for each sentence are linearly interpolated from the parent
    segment's (start, end) window by character-count share. If no sentence
    boundary is found within a segment, it is emitted unchanged (greedy
    fallback).
    """
    expanded: list[tuple[str, float, float]] = []
    for text, start, end in segments:
        sentences = _split_into_sentences(text)
        if len(sentences) <= 1:
            expanded.append((text, start, end))
            continue

        total_chars = sum(len(s) for s in sentences) or 1
        duration = max(end - start, 0.0)
        cursor = start
        for i, sentence in enumerate(sentences):
            share = len(sentence) / total_chars
            sent_duration = duration * share
            sent_start = cursor
            sent_end = end if i == len(sentences) - 1 else cursor + sent_duration
            expanded.append((sentence, sent_start, sent_end))
            cursor = sent_end
    return expanded


def chunk_transcript(
    transcript_segments: list[dict],
    chunk_size: int = 256,
    chunk_overlap: int = 32,
    video_metadata: dict | None = None,
    transcription_source: str = "youtube",
) -> list[dict]:
    """
    Chunk a YouTube transcript into RAG-ready documents with timestamp mapping.

    Prefers sentence boundaries when splitting: each transcript segment is
    first expanded into sentence-level sub-segments, then sub-segments are
    greedily packed up to `chunk_size` tokens. If a segment contains no
    sentence terminator it falls through to the greedy behavior unchanged.

    Args:
        transcript_segments: List of {text, start, duration} from youtube-transcript-api.
        chunk_size: Target tokens per chunk.
        chunk_overlap: Overlap tokens between consecutive chunks.
        video_metadata: {video_id, title, channel_name, channel_id, url,
            published_at, duration_seconds, language} to attach to every chunk.
        transcription_source: Provenance tag for how the transcript was
            produced. ``"youtube"`` (default) means it came from the YouTube
            Transcript API; ``"whisper"`` means it was produced by the
            OpenAI Whisper fallback. Propagated into per-chunk metadata
            so downstream consumers can reason about quality/language
            reliability.

    Returns:
        List of {text, metadata} dicts ready for ChromaDB insertion.
    """
    if not transcript_segments:
        return []

    metadata = video_metadata or {}

    # Build (text, start, end) tuples for each non-empty segment.
    segments: list[tuple[str, float, float]] = []
    for seg in transcript_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0))
        duration = float(seg.get("duration", 0))
        segments.append((text, start, start + duration))

    if not segments:
        return []

    # Prefer sentence boundaries over raw segment boundaries.
    segments = _expand_segments_to_sentences(segments)

    chunks: list[dict] = []
    current_items: list[tuple[str, float, float]] = []
    current_tokens = 0

    for text, seg_start, seg_end in segments:
        seg_tokens = _count_tokens(text)

        if current_tokens + seg_tokens > chunk_size and current_items:
            # Emit the current chunk.
            chunk_text = " ".join(item[0] for item in current_items)
            chunks.append({
                "text": chunk_text,
                "timestamp_start": current_items[0][1],
                "timestamp_end": current_items[-1][2],
                "word_count": len(chunk_text.split()),
            })

            # Build overlap window from the tail of the emitted chunk.
            overlap_items: list[tuple[str, float, float]] = []
            overlap_tokens = 0
            for item in reversed(current_items):
                item_tokens = _count_tokens(item[0])
                if overlap_tokens + item_tokens > chunk_overlap:
                    break
                overlap_items.insert(0, item)
                overlap_tokens += item_tokens

            current_items = overlap_items
            current_tokens = overlap_tokens

        current_items.append((text, seg_start, seg_end))
        current_tokens += seg_tokens

    # Emit the final chunk.
    if current_items:
        chunk_text = " ".join(item[0] for item in current_items)
        chunks.append({
            "text": chunk_text,
            "timestamp_start": current_items[0][1],
            "timestamp_end": current_items[-1][2],
            "word_count": len(chunk_text.split()),
        })

    # Normalize optional metadata so ChromaDB (which requires flat scalar
    # metadata) gets predictable types.
    published_at = metadata.get("published_at") or ""
    if hasattr(published_at, "isoformat"):
        published_at = published_at.isoformat()
    else:
        published_at = str(published_at) if published_at else ""

    duration_seconds = metadata.get("duration_seconds", 0)
    try:
        duration_seconds = int(duration_seconds or 0)
    except (TypeError, ValueError):
        logger.exception("Invalid duration_seconds=%r, defaulting to 0", duration_seconds)
        duration_seconds = 0

    result = []
    for i, chunk in enumerate(chunks):
        result.append({
            "text": chunk["text"],
            "metadata": {
                "video_id": metadata.get("video_id", ""),
                "video_title": metadata.get("title", ""),
                "channel_name": metadata.get("channel_name", ""),
                "channel_id": metadata.get("channel_id", ""),
                "video_url": metadata.get("url", ""),
                "published_at": published_at,
                "duration_seconds": duration_seconds,
                "timestamp_start": chunk["timestamp_start"],
                "timestamp_end": chunk["timestamp_end"],
                "chunk_index": i,
                "total_chunks": len(chunks),
                "language": metadata.get("language", "unknown"),
                "transcription_source": transcription_source,
                "word_count": chunk["word_count"],
            },
        })

    return result

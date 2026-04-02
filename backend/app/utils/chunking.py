import tiktoken


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))


def chunk_transcript(
    transcript_segments: list[dict],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    video_metadata: dict | None = None,
) -> list[dict]:
    """
    Chunk a YouTube transcript into RAG-ready documents with timestamp mapping.

    Args:
        transcript_segments: List of {text, start, duration} from youtube-transcript-api.
        chunk_size: Target tokens per chunk.
        chunk_overlap: Overlap tokens between consecutive chunks.
        video_metadata: {video_id, title, channel_name, channel_id, url} to attach.

    Returns:
        List of {text, metadata} dicts ready for ChromaDB insertion.
    """
    if not transcript_segments:
        return []

    metadata = video_metadata or {}

    # Build a list of (text, start_time, end_time) for each segment
    segments = []
    for seg in transcript_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0))
        duration = float(seg.get("duration", 0))
        segments.append((text, start, start + duration))

    if not segments:
        return []

    # Concatenate segments into larger chunks respecting token limits
    chunks = []
    current_texts = []
    current_start = segments[0][1]
    current_tokens = 0

    for text, seg_start, seg_end in segments:
        seg_tokens = _count_tokens(text)

        if current_tokens + seg_tokens > chunk_size and current_texts:
            # Emit current chunk
            chunk_text = " ".join(current_texts)
            chunks.append({
                "text": chunk_text,
                "timestamp_start": current_start,
                "timestamp_end": seg_start,
                "word_count": len(chunk_text.split()),
            })

            # Handle overlap: keep last few segments for context
            overlap_texts = []
            overlap_tokens = 0
            for t in reversed(current_texts):
                t_tokens = _count_tokens(t)
                if overlap_tokens + t_tokens > chunk_overlap:
                    break
                overlap_texts.insert(0, t)
                overlap_tokens += t_tokens

            current_texts = overlap_texts
            current_tokens = overlap_tokens
            current_start = seg_start - 1 if seg_start > 0 else 0

        current_texts.append(text)
        current_tokens += seg_tokens

    # Emit final chunk
    if current_texts:
        chunk_text = " ".join(current_texts)
        last_end = segments[-1][2] if segments else 0
        chunks.append({
            "text": chunk_text,
            "timestamp_start": current_start,
            "timestamp_end": last_end,
            "word_count": len(chunk_text.split()),
        })

    # Attach metadata and indices
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
                "timestamp_start": chunk["timestamp_start"],
                "timestamp_end": chunk["timestamp_end"],
                "chunk_index": i,
                "total_chunks": len(chunks),
                "language": metadata.get("language", "en"),
                "word_count": chunk["word_count"],
            },
        })

    return result

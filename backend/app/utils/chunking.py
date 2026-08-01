import logging
import re
from typing import Any

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


# Internal segment shape used through expansion + packing. We carry
# `extra` alongside `(text, start, end)` so per-segment metadata
# (e.g. `comment_id` / `comment_url` / `kind` / `author` from social
# connectors) survives all the way to chunk emission. For sources
# without per-segment metadata (YouTube transcripts), `extra` is an
# empty dict.
_Seg = tuple[str, float, float, dict[str, Any]]


def _expand_segments_to_sentences(
    segments: list[_Seg],
) -> list[_Seg]:
    """Expand transcript segments into sentence-level sub-segments.

    Timestamps for each sentence are linearly interpolated from the parent
    segment's (start, end) window by character-count share. If no sentence
    boundary is found within a segment, it is emitted unchanged (greedy
    fallback).

    The parent segment's ``extra`` dict propagates to every sentence-level
    sub-segment — all sentences within one segment share the same
    provenance (same reply, same author, etc.).

    Segments carrying ``extra["atomic"]`` are exempt (R1). A visual
    annotation is a single indivisible unit whose `[VISUAL @ mm:ss — ...]`
    wrapper is what tells every downstream model these words were never
    spoken. Sentence-splitting it would leave the opening marker on the
    first fragment and the closing bracket on the last, with the middle
    sentences reading as speech — the precise failure this feature must
    not have. The interpolated per-sentence timestamps would be fiction
    too: an annotation describes one instant, not a span to divide up.
    """
    expanded: list[_Seg] = []
    for text, start, end, extra in segments:
        if extra.get("atomic"):
            expanded.append((text, start, end, extra))
            continue
        sentences = _split_into_sentences(text)
        if len(sentences) <= 1:
            expanded.append((text, start, end, extra))
            continue

        total_chars = sum(len(s) for s in sentences) or 1
        duration = max(end - start, 0.0)
        cursor = start
        for i, sentence in enumerate(sentences):
            share = len(sentence) / total_chars
            sent_duration = duration * share
            sent_start = cursor
            sent_end = end if i == len(sentences) - 1 else cursor + sent_duration
            expanded.append((sentence, sent_start, sent_end, extra))
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
        video_metadata: per-document fields to attach to every chunk's
            Chroma metadata. Legacy YouTube-shaped: ``{video_id, title,
            channel_name, channel_id, url, published_at, duration_seconds,
            language}``. Polymorphic (M-1.5 / M-1.6 follow-up):
            ``{source_type, source_id, source_url, permalink, author,
            subreddit, instance}``. The Q&A agent's
            ``_chunk_to_reference`` reads the polymorphic block on
            every chunk to dispatch citation rendering by source_type
            (video / reddit_post / hn_story / mastodon_post / bluesky_post).
            Legacy chunks without the polymorphic fields keep working
            because the agent falls back to the YouTube branch.

            **Per-segment fields** (S-1.5.12 T-1.5.12.2) are read
            *automatically* from each `transcript_segments` entry's
            optional ``extra`` dict — the caller does not pass them
            in ``video_metadata``. Connector flatten layers (Reddit /
            HN / Mastodon / Bluesky) emit ``extra = {kind, author,
            comment_id, comment_url, depth, ...}`` per reply, and
            this function promotes the dominant-by-tokens segment's
            ``comment_id`` / ``comment_url`` / ``author`` to the
            chunk's metadata. For YouTube transcripts (no `extra`),
            those chunk fields are empty strings.
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

    # Build (text, start, end, extra) tuples for each non-empty segment.
    # `extra` carries per-segment provenance from text-based connectors
    # (Reddit / HN / Mastodon / Bluesky): `{kind, author, comment_id,
    # comment_url, depth, ...}` per-reply identity. YouTube transcripts
    # don't supply `extra`, so it defaults to an empty dict.
    segments: list[_Seg] = []
    for seg in transcript_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0))
        duration = float(seg.get("duration", 0))
        extra = seg.get("extra") or {}
        if not isinstance(extra, dict):
            extra = {}
        segments.append((text, start, start + duration, extra))

    if not segments:
        return []

    # Prefer sentence boundaries over raw segment boundaries.
    segments = _expand_segments_to_sentences(segments)

    chunks: list[dict] = []
    current_items: list[_Seg] = []
    current_tokens = 0

    def _emit_chunk(items: list[_Seg]) -> dict:
        """Build a chunk dict from a list of packed segments.

        Per S-1.5.12 T-1.5.12.2: we promote per-reply identity to chunk
        level using a **dominant-segment heuristic** — the segment in
        the chunk with the most tokens "wins" and contributes its
        ``comment_id`` / ``comment_url`` / ``author`` / ``kind`` /
        ``depth`` to the chunk's metadata. Rationale:

        - Most chunks contain a single segment (or several from the
          same reply) — dominant is then trivial.
        - When a chunk straddles multiple replies (a small reply at
          the start, a long reply at the end), the longer reply
          supplies the bulk of the searchable text, so its identity
          is the more meaningful citation target.
        - Falling back to first-segment would systematically
          mis-attribute citations to short top-line replies in a
          straddling chunk; falling back to last-segment loses the
          natural reading order intuition. Dominant-by-tokens is a
          neutral tie-breaker that aligns with retrieval relevance.

        Cross-reply chunks happen mostly because of the chunk-overlap
        window stitching the tail of one reply onto the head of the
        next. The heuristic still picks the longer one, which is the
        right call since the overlap region is semantically
        ambiguous-by-design (it's there for retrieval continuity, not
        citation accuracy).
        """
        chunk_text = " ".join(it[0] for it in items)

        # R1: visual annotations are excluded from the dominant-segment
        # vote. `dominant` decides whose REPLY this chunk is attributed to,
        # and an annotation belongs to no reply — letting a long
        # description outvote the speech would blank the chunk's
        # comment_id/author and mis-attribute the citation. They are
        # aggregated separately below instead.
        speech_items = [it for it in items if not (it[3] or {}).get("atomic")]
        vote_items = speech_items or items

        # Dominant segment — most tokens wins. Ties broken by first-
        # occurrence (Python max() is stable, returns the first
        # equal-key element).
        dominant = max(
            vote_items,
            key=lambda it: _count_tokens(it[0]),
        )
        dominant_extra = dominant[3] or {}

        # R1: aggregate ACROSS ALL segments rather than promoting one.
        # The dominant heuristic exists to pick a single citation target;
        # visual presence is not a competition — a chunk with 240 tokens of
        # speech and one 12-token annotation genuinely has both, and the
        # annotation would always lose a dominance vote it should never
        # have been entered into.
        visual_ts = [
            it[3]["frame_timestamp"]
            for it in items
            if (it[3] or {}).get("kind") == "visual"
            and it[3].get("frame_timestamp") is not None
        ]

        return {
            "text": chunk_text,
            "timestamp_start": items[0][1],
            "timestamp_end": items[-1][2],
            "word_count": len(chunk_text.split()),
            # Per-segment provenance (S-1.5.12 T-1.5.12.2). Empty
            # for video transcripts; populated for social connectors.
            "kind": dominant_extra.get("kind") or "",
            "comment_id": dominant_extra.get("comment_id") or "",
            "comment_url": dominant_extra.get("comment_url") or "",
            "segment_author": dominant_extra.get("author") or "",
            "segment_depth": dominant_extra.get("depth"),
            # R1 visual context.
            "visual_frame_count": len(visual_ts),
            "visual_timestamps": ",".join(f"{t:.0f}" for t in sorted(visual_ts)),
        }

    for text, seg_start, seg_end, extra in segments:
        seg_tokens = _count_tokens(text)

        if current_tokens + seg_tokens > chunk_size and current_items:
            # Emit the current chunk.
            chunks.append(_emit_chunk(current_items))

            # Build overlap window from the tail of the emitted chunk.
            overlap_items: list[_Seg] = []
            overlap_tokens = 0
            for item in reversed(current_items):
                item_tokens = _count_tokens(item[0])
                if overlap_tokens + item_tokens > chunk_overlap:
                    break
                overlap_items.insert(0, item)
                overlap_tokens += item_tokens

            current_items = overlap_items
            current_tokens = overlap_tokens

        current_items.append((text, seg_start, seg_end, extra))
        current_tokens += seg_tokens

    # Emit the final chunk.
    if current_items:
        chunks.append(_emit_chunk(current_items))

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
        # Per-segment provenance (S-1.5.12 T-1.5.12.2). Promoted by
        # the dominant-segment heuristic in `_emit_chunk`. Empty for
        # video transcripts (no per-segment metadata); populated for
        # social-connector chunks that came from a specific reply.
        # The Q&A agent's `_chunk_to_reference` reads `comment_id` +
        # `comment_url` to deep-link a citation to the exact reply
        # rather than the OP.
        comment_id = chunk.get("comment_id") or ""
        comment_url = chunk.get("comment_url") or ""
        segment_author = chunk.get("segment_author") or ""
        segment_kind = chunk.get("kind") or ""
        segment_depth_raw = chunk.get("segment_depth")
        # Chroma metadata only stores flat primitives; coerce None /
        # missing to 0 so the column type stays uniform across chunks.
        try:
            segment_depth = (
                int(segment_depth_raw) if segment_depth_raw is not None else 0
            )
        except (TypeError, ValueError):
            segment_depth = 0

        result.append({
            "text": chunk["text"],
            "metadata": {
                # Legacy YouTube-shaped fields. Still populated for
                # every source_type because the report-agent and the
                # Q&A agent's video-default branch read them; for non-
                # video sources `video_id` doubles as the dedup key
                # but the polymorphic fields below are the citation
                # source.
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
                # Polymorphic per-document fields per S-1.5.5 follow-up.
                # The Q&A agent's `_chunk_to_reference` dispatches on
                # `source_type` and reads the matching set of fields.
                # Missing keys default to "" / "video" so legacy chunks
                # written before this PR continue to render via the
                # YouTube default branch.
                "source_type": str(metadata.get("source_type") or "video"),
                "source_id": str(metadata.get("source_id") or ""),
                "source_url": str(metadata.get("source_url") or ""),
                "permalink": str(metadata.get("permalink") or ""),
                "author": str(metadata.get("author") or ""),
                "subreddit": str(metadata.get("subreddit") or ""),
                "instance": str(metadata.get("instance") or ""),
                # Per-segment provenance (S-1.5.12 T-1.5.12.2 — the
                # reply-anchor refinement). When set, the Q&A agent
                # promotes these to the citation's permalink so a
                # cite from a specific reply opens at that reply's
                # URL rather than the OP. `comment_url` wins when
                # present (Mastodon / Bluesky reply URLs); when only
                # `comment_id` is present (Reddit / HN), the agent
                # synthesises the reply URL from it.
                "comment_id": str(comment_id),
                "comment_url": str(comment_url),
                "segment_author": str(segment_author),
                "segment_kind": str(segment_kind),
                "segment_depth": segment_depth,
                # R1 visual context. The annotation TEXT is already inside
                # `text` — these exist so retrieval can filter/boost on
                # visual evidence and so a citation can point at the frame
                # that grounded it. Chroma stores flat scalars only, hence
                # the comma-joined timestamp string.
                "visual_frame_count": int(chunk.get("visual_frame_count") or 0),
                "visual_timestamps": str(chunk.get("visual_timestamps") or ""),
            },
        })

    return result

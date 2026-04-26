"""Shared helpers for text-based connectors (Reddit, HN, articles, ...).

The chunker (`app.utils.chunking`) was designed for video transcripts:
it walks a list of `{text, start, duration}` segments and packs them
into chunks under a token budget. Text-based sources have no time axis,
so we synthesise pseudo-timestamps using a rough 3-words-per-second
heuristic. The actual values don't matter for retrieval — they just
need to be present, monotonic, and non-negative.

See ADR D-013 in `docs/decisions.md` for the rationale. Future
text-based connectors should import these symbols rather than
re-defining the constant, so the convention stays a one-line tunable.
"""
from __future__ import annotations

from typing import Any

# Synthesised reading-rate for pseudo-timestamps. Roughly 3 wps ≈ 180
# wpm — a comfortable narration tempo. The chunker only cares that
# `start`/`duration` are non-negative and monotonic; the exact value
# is not load-bearing.
_WORDS_PER_SECOND = 3.0


def _segment_for_text(
    text: str, cursor: float, extra: dict[str, Any]
) -> tuple[dict[str, Any], float]:
    """Build a segment dict + return the new cursor.

    Empty text is rejected by the caller; this helper assumes ``text`` is
    non-empty so the duration floor is meaningful.
    """
    words = max(1, len(text.split()))
    duration = words / _WORDS_PER_SECOND
    seg = {"text": text, "start": cursor, "duration": duration, "extra": extra}
    return seg, cursor + duration

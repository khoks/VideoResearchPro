"""Flatten an HN story + comment tree into chunkable text segments.

The chunker (`app.utils.chunking`) was designed for video transcripts:
it walks a list of `{text, start, duration}` segments and packs them
into chunks under a token budget. HN stories have no time axis, so
we synthesise pseudo-timestamps via `app.sources._text_utils._segment_for_text`
(D-013, 3 wps).

Output shape per segment::

    {
        "text": "<the rendered text — see formatting below>",
        "start": <float seconds, monotonic from 0>,
        "duration": <float seconds>,
        "extra": {
            "kind": "story" | "comment",
            "author": "<hn handle or [deleted]>",
            "points": <int or None>,
            "depth": <int>,           # comments only
            "comment_id": <int>,      # comments only
        },
    }

Comments are sorted by points (descending) and trimmed to ``top_n``
across the entire tree. Replies retain a ``↳ `` depth marker so the
reader can see threading even after sorting.

HN comment text is HTML (``<p>`` tags, anchors). We strip tags very
cheaply rather than pulling in a full parser — the chunker is
forgiving and the embedding model handles surface noise well enough.
A future PR may swap this for `html2text` if quality demands it.
"""
from __future__ import annotations

import re
from typing import Any

from app.sources._text_utils import _segment_for_text

# Cheap HTML scrub. HN comment text is well-formed but uses <p>, <a>,
# and <i>/<pre> tags. Replace <p> with a blank line, then strip every
# remaining tag, then unescape the common entities.
_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"<p>", re.IGNORECASE)
_ENTITY_FIXES = (
    ("&#x27;", "'"),
    ("&#39;", "'"),
    ("&quot;", '"'),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&nbsp;", " "),
)


def _strip_html(text: str) -> str:
    """Cheap HTML → plain text. Good enough for embedding/retrieval."""
    if not text:
        return ""
    text = _PARA_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    for needle, replacement in _ENTITY_FIXES:
        text = text.replace(needle, replacement)
    return text.strip()


def _comment_tree_iter(item: dict, depth: int = 0) -> list[dict]:
    """Walk an Algolia HN comment tree depth-first; yield ``{depth, data}``.

    Algolia returns recursive ``children`` arrays directly on each
    item, unlike Reddit's separate `Listing` envelope. Items with
    `text == None` (deleted/dead) are kept here so the caller can
    skip them after sorting — `points` may still be relevant for
    ordering even if the body is gone.
    """
    out: list[dict] = []
    for child in item.get("children") or []:
        if child.get("type") != "comment":
            continue
        out.append({"depth": depth, "data": child})
        out.extend(_comment_tree_iter(child, depth=depth + 1))
    return out


def flatten_story_with_comments(
    item: dict, top_n: int = 50
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Flatten an Algolia ``/items/<id>`` payload into ``(segments, story_data)``.

    - The first segment is the OP (title + ``text`` body if present,
      joined by a blank line).
    - Subsequent segments are top-N comments by points with depth markers.
    - If the payload is malformed or not a story, returns ``([], {})``.
    - If the story has no body *and* no comments, returns ``([], story_data)``
      so the caller can still see the story metadata if needed.
    """
    if not isinstance(item, dict):
        return [], {}
    if item.get("type") != "story":
        return [], {}

    story_data = item

    segments: list[dict[str, Any]] = []
    cursor = 0.0

    title = (story_data.get("title") or "").strip()
    body = _strip_html(story_data.get("text") or "")
    op_parts = [t for t in (title, body) if t]
    op_text = "\n\n".join(op_parts)
    if op_text:
        seg, cursor = _segment_for_text(
            op_text,
            cursor,
            extra={
                "kind": "story",
                "author": story_data.get("author"),
                "points": story_data.get("points"),
            },
        )
        segments.append(seg)

    flat_comments = _comment_tree_iter(story_data)
    flat_comments.sort(
        key=lambda c: c["data"].get("points") or 0, reverse=True
    )
    flat_comments = flat_comments[:top_n]

    for entry in flat_comments:
        data = entry["data"]
        body = _strip_html(data.get("text") or "")
        if not body:
            continue
        depth = entry["depth"]
        author = data.get("author") or "[deleted]"
        points = data.get("points") or 0
        marker = "\u21b3 " * depth  # "↳ " per depth level
        text = f"{marker}{author} (points {points}): {body}"
        seg, cursor = _segment_for_text(
            text,
            cursor,
            extra={
                "kind": "comment",
                "author": author,
                "points": points,
                "depth": depth,
                "comment_id": data.get("id"),
            },
        )
        segments.append(seg)

    return segments, story_data

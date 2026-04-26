"""Flatten a Reddit post + comment tree into chunkable text segments.

The chunker (`app.utils.chunking`) was designed for video transcripts:
it walks a list of `{text, start, duration}` segments and packs them
into chunks under a token budget. Reddit posts have no time axis, so
this module synthesises pseudo-timestamps using a rough 3-words-per-
second heuristic. The actual values don't matter for retrieval — they
just need to be present, monotonic, and non-negative.

Output shape per segment::

    {
        "text": "<the rendered text — see formatting below>",
        "start": <float seconds, monotonic from 0>,
        "duration": <float seconds>,
        "extra": {
            "kind": "post" | "comment",
            "author": "<reddit handle or [deleted]>",
            "score": <int or None>,
            "depth": <int>,           # comments only
            "comment_id": "<id>",     # comments only
        },
    }

Comments are sorted by score (descending) and trimmed to ``top_n``
across the entire tree. Replies retain a ``↳ `` depth marker so the
reader can see threading even after sorting.
"""
from __future__ import annotations

from typing import Any

from app.sources._text_utils import _segment_for_text


def _comment_tree_iter(comment_listing: dict, depth: int = 0) -> list[dict]:
    """Walk a Reddit comment listing depth-first; yield ``{depth, data}``.

    `kind == "more"` placeholders are skipped (expanding them requires
    extra API calls, deferred to a follow-up PR). `replies` is sometimes
    the literal empty string for childless comments — guard against that.
    """
    children = (comment_listing or {}).get("data", {}).get("children", [])
    out: list[dict] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data") or {}
        out.append({"depth": depth, "data": data})
        replies = data.get("replies")
        if isinstance(replies, dict):
            out.extend(_comment_tree_iter(replies, depth=depth + 1))
    return out


def flatten_post_with_comments(
    listing: list, top_n: int = 50
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Flatten a `[post, comments]` listing into ``(segments, post_data)``.

    - The first segment is the OP (title + selftext joined by a blank line).
    - Subsequent segments are top-N comments by score with depth markers.
    - If the listing is malformed or has no post, returns ``([], {})``.
    - If the post has no body *and* no comments, returns ``([], post_data)``
      so the caller can still see the post metadata if needed.
    """
    if not isinstance(listing, list) or len(listing) < 2:
        return [], {}

    post_listing, comment_listing = listing[0], listing[1]
    post_children = (post_listing or {}).get("data", {}).get("children", [])
    if not post_children:
        return [], {}
    post_data = post_children[0].get("data") or {}

    segments: list[dict[str, Any]] = []
    cursor = 0.0

    title = (post_data.get("title") or "").strip()
    selftext = (post_data.get("selftext") or "").strip()
    op_parts = [t for t in (title, selftext) if t]
    op_text = "\n\n".join(op_parts)
    if op_text:
        seg, cursor = _segment_for_text(
            op_text,
            cursor,
            extra={
                "kind": "post",
                "author": post_data.get("author"),
                "score": post_data.get("score"),
            },
        )
        segments.append(seg)

    flat_comments = _comment_tree_iter(comment_listing)
    flat_comments.sort(key=lambda c: c["data"].get("score") or 0, reverse=True)
    flat_comments = flat_comments[:top_n]

    for entry in flat_comments:
        data = entry["data"]
        body = (data.get("body") or "").strip()
        if not body:
            continue
        depth = entry["depth"]
        author = data.get("author") or "[deleted]"
        score = data.get("score") or 0
        marker = "\u21b3 " * depth  # "↳ " per depth level
        text = f"{marker}u/{author} (score {score}): {body}"
        seg, cursor = _segment_for_text(
            text,
            cursor,
            extra={
                "kind": "comment",
                "author": author,
                "score": score,
                "depth": depth,
                "comment_id": data.get("id"),
            },
        )
        segments.append(seg)

    return segments, post_data

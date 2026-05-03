"""Flatten a Mastodon status + context into chunkable text segments.

The chunker (`app.utils.chunking`) was designed for video transcripts:
it walks a list of `{text, start, duration}` segments and packs them
into chunks under a token budget. Mastodon statuses have no time axis,
so we synthesise pseudo-timestamps via
`app.sources._text_utils._segment_for_text` (D-013, 3 wps).

Output shape per segment::

    {
        "text": "<the rendered text — see formatting below>",
        "start": <float seconds, monotonic from 0>,
        "duration": <float seconds>,
        "extra": {
            "kind": "status" | "reply",
            "author": "<user@instance>",
            "favourites": <int or None>,
            "depth": <int>,            # replies only
            "comment_id": <str>,       # replies only — Mastodon status id
        },
    }

Replies are sorted by favourites (descending) and trimmed to ``top_n``
across the entire descendant set. Replies retain a ``↳ `` depth marker
so the reader can see threading even after sorting.

Mastodon delivers status `content` as HTML (``<p>`` tags, anchors).
We strip tags very cheaply rather than pulling in a full parser — the
chunker is forgiving and the embedding model handles surface noise
well enough. A future PR may swap this for `html2text` if quality
demands it. (Same calculus we made for HN.)
"""
from __future__ import annotations

import re
from typing import Any

from app.sources._text_utils import _segment_for_text

# Cheap HTML scrub. Mastodon content is well-formed HTML using <p>, <a>,
# <span>, and <br> tags. Replace <br> with newline, <p> with double
# newline, then strip every remaining tag, then unescape common entities.
_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"<p\b[^>]*>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
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
    text = _BR_RE.sub("\n", text)
    text = _PARA_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    for needle, replacement in _ENTITY_FIXES:
        text = text.replace(needle, replacement)
    return text.strip()


def _account_handle(account: dict | None) -> str:
    """Format a Mastodon account dict as a display handle.

    Local accounts return `acct = "user"`; remote accounts return
    `acct = "user@instance"`. We always render with a leading `@`
    so it reads as a Mastodon handle in flattened output.
    """
    if not isinstance(account, dict):
        return "@unknown"
    acct = account.get("acct") or account.get("username") or "unknown"
    return f"@{acct}"


def _build_depth_index(descendants: list[dict], root_id: str) -> dict[str, int]:
    """Compute reply depth for every descendant relative to the root.

    Mastodon flattens the conversation into a single descendants list
    but each entry carries `in_reply_to_id`. We walk the parent chain
    until we hit either the root status or a status not in the index,
    so depth is always relative to the OP being flattened.

    Status IDs are strings (Mastodon uses snowflake-ish IDs). Cycles
    are guarded against defensively even though the API never produces
    them — a malformed payload shouldn't infinite-loop the worker.
    """
    by_id = {str(d.get("id")): d for d in descendants if isinstance(d, dict)}
    depth: dict[str, int] = {}
    root_id = str(root_id)

    for sid, status in by_id.items():
        if sid in depth:
            continue
        # Walk up to the root. Direct reply to root → depth 1.
        chain: list[str] = []
        cursor: str | None = sid
        seen: set[str] = set()
        while cursor is not None and cursor != root_id and cursor not in seen:
            seen.add(cursor)
            chain.append(cursor)
            parent = by_id.get(cursor, {}).get("in_reply_to_id")
            cursor = str(parent) if parent is not None else None
        # If we exited because cursor == root_id, chain has the path
        # back to root in reverse order; depth is len(chain).
        # If we exited because cursor is None (orphan reply not in
        # the descendants set) or hit a cycle, treat as depth 1 so
        # the segment still renders sensibly.
        if cursor == root_id:
            for i, link in enumerate(reversed(chain)):
                depth[link] = i + 1
        else:
            for link in chain:
                depth.setdefault(link, 1)

    return depth


def flatten_status_with_context(
    status: dict,
    context: dict,
    top_n: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Flatten a Mastodon status + ``/context`` payload into segments.

    Args:
        status: the OP — `/api/v1/statuses/<id>` payload.
        context: the conversation context — `/api/v1/statuses/<id>/context`
            with `ancestors` (ignored — we anchor on the OP) and
            `descendants` (the replies we flatten).
        top_n: max number of replies to keep, ranked by favourites.

    Returns:
        ``(segments, status_data)``. The first segment is the OP body;
        subsequent segments are top-N replies by favourites with depth
        markers. If the payload is malformed, returns ``([], {})``.
        If the status has no body *and* no replies, returns
        ``([], status_data)`` so the caller can still see metadata.
    """
    if not isinstance(status, dict):
        return [], {}

    status_data = status

    segments: list[dict[str, Any]] = []
    cursor = 0.0

    op_body = _strip_html(status_data.get("content") or "")
    op_author = _account_handle(status_data.get("account"))
    op_favs = status_data.get("favourites_count")
    if op_body:
        # OP body only — Mastodon statuses have no separate title/body
        # split; the whole `content` field is the post.
        seg, cursor = _segment_for_text(
            op_body,
            cursor,
            extra={
                "kind": "status",
                "author": op_author,
                "favourites": op_favs,
            },
        )
        segments.append(seg)

    descendants = (
        context.get("descendants") if isinstance(context, dict) else None
    ) or []
    descendants = [d for d in descendants if isinstance(d, dict)]

    root_id = str(status_data.get("id") or "")
    depth_index = _build_depth_index(descendants, root_id)

    # Sort replies by favourites (descending), trim to top_n. Stable
    # sort means replies with the same favourite count keep their
    # API-order which is recency for Mastodon.
    descendants_sorted = sorted(
        descendants,
        key=lambda d: d.get("favourites_count") or 0,
        reverse=True,
    )[:top_n]

    for reply in descendants_sorted:
        body = _strip_html(reply.get("content") or "")
        if not body:
            continue
        rid = str(reply.get("id") or "")
        depth = depth_index.get(rid, 1)
        author = _account_handle(reply.get("account"))
        favs = reply.get("favourites_count") or 0
        marker = "↳ " * depth  # "↳ " per depth level
        text = f"{marker}{author} (favs {favs}): {body}"
        seg, cursor = _segment_for_text(
            text,
            cursor,
            extra={
                "kind": "reply",
                "author": author,
                "favourites": favs,
                "depth": depth,
                "comment_id": rid,
            },
        )
        segments.append(seg)

    return segments, status_data

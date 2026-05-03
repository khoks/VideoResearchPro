"""Flatten a Bluesky post-thread payload into chunkable text segments.

The chunker (`app.utils.chunking`) was designed for video transcripts:
it walks a list of `{text, start, duration}` segments and packs them
into chunks under a token budget. Bluesky posts have no time axis,
so we synthesise pseudo-timestamps via
`app.sources._text_utils._segment_for_text` (D-013, 3 wps).

Output shape per segment::

    {
        "text": "<the rendered text — see formatting below>",
        "start": <float seconds, monotonic from 0>,
        "duration": <float seconds>,
        "extra": {
            "kind": "post" | "reply",
            "author": "<handle>",
            "likes": <int or None>,
            "depth": <int>,            # replies only
            "comment_id": <str>,       # replies only — AT-URI of the reply
            "comment_url": <str>,      # replies only — bsky.app web URL
        },
    }

The ``getPostThread`` payload is recursive: the top-level ``thread``
object has a ``post`` and a ``replies`` list, each of which is
itself a thread object with the same shape. We walk the tree
depth-first to collect every reply with its absolute depth, then
sort by like count and trim to ``top_n`` for the final segment list.

Replies retain a ``↳ `` depth marker so the reader can see threading
even after sorting.

Bluesky post text is plain text (Markdown-ish — links and mentions
are flagged via separate ``facets`` / ``embed`` records, not inline
HTML), so there's no HTML scrub step. Mentions like ``@handle``
appear in the text as written.
"""
from __future__ import annotations

from typing import Any

from app.sources._text_utils import _segment_for_text


def _author_handle(author: dict | None) -> str:
    """Format a Bluesky author dict as a display handle.

    AT-Proto ``post.author`` is ``{did, handle, displayName, ...}``.
    Bluesky's convention in client UIs is the bare handle (no leading
    `@`); we emit `@handle` so segment text reads naturally inline.
    """
    if not isinstance(author, dict):
        return "@unknown"
    handle = author.get("handle") or "unknown"
    return f"@{handle}"


def _post_text(post: dict | None) -> str:
    """Return the body text of an AT-Proto post.

    Posts store text under ``record.text`` (the original record) for
    posts created by the user, and ``embed.record.value.text`` for
    embedded quotes — but we only flatten direct posts in the thread
    so the simple path is fine.
    """
    if not isinstance(post, dict):
        return ""
    record = post.get("record")
    if isinstance(record, dict):
        text = record.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _post_uri(post: dict | None) -> str:
    """Return the canonical AT-URI of a post (or empty string)."""
    if not isinstance(post, dict):
        return ""
    return str(post.get("uri") or "")


def _post_web_url(post: dict | None) -> str:
    """Build the ``https://bsky.app/profile/<handle>/post/<rkey>`` URL.

    Bluesky's web client deeplinks on this shape. We prefer the
    handle-based form (rather than DID-based) because it's what users
    see when they share posts, and it's still canonical because Bluesky
    redirects when a handle changes.
    """
    if not isinstance(post, dict):
        return ""
    uri = _post_uri(post)
    author = post.get("author") or {}
    handle = author.get("handle") if isinstance(author, dict) else None
    if not uri or not handle:
        return ""
    # AT-URIs are at://<did>/<collection>/<rkey>; we want the rkey.
    parts = uri.rsplit("/", 1)
    if len(parts) != 2:
        return ""
    rkey = parts[1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def _walk_replies(thread: dict, depth: int = 0) -> list[dict]:
    """Walk an AT-Proto thread depth-first; yield ``{depth, post}`` dicts.

    The thread shape is::

        {"post": {...}, "replies": [{"post": {...}, "replies": [...]}]}

    Some replies appear as ``$type=app.bsky.feed.defs#notFoundPost`` or
    ``#blockedPost`` rather than full posts — those carry no ``post``
    key, so we skip them defensively.
    """
    out: list[dict] = []
    replies = thread.get("replies") if isinstance(thread, dict) else None
    if not isinstance(replies, list):
        return out
    for child in replies:
        if not isinstance(child, dict):
            continue
        post = child.get("post")
        if isinstance(post, dict):
            out.append({"depth": depth + 1, "post": post})
        # Recurse regardless of whether this reply itself rendered —
        # a blocked post can still have visible children.
        out.extend(_walk_replies(child, depth=depth + 1))
    return out


def _likes(post: dict) -> int:
    """Reach into the AT-Proto post for the like count."""
    if not isinstance(post, dict):
        return 0
    return int(post.get("likeCount") or 0)


def flatten_thread(
    thread_payload: dict,
    top_n: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Flatten a ``app.bsky.feed.getPostThread`` payload into segments.

    Args:
        thread_payload: the XRPC response — ``{thread: {post: ..., replies: [...]}}``.
        top_n: max number of replies to keep, ranked by likes.

    Returns:
        ``(segments, post_data)``. The first segment is the OP body;
        subsequent segments are top-N replies by likes with depth
        markers. If the payload is malformed, returns ``([], {})``.
        If the post has no body *and* no replies, returns
        ``([], post_data)`` so the caller can still see metadata.
    """
    if not isinstance(thread_payload, dict):
        return [], {}
    thread = thread_payload.get("thread")
    if not isinstance(thread, dict):
        return [], {}
    op_post = thread.get("post")
    if not isinstance(op_post, dict):
        return [], {}

    segments: list[dict[str, Any]] = []
    cursor = 0.0

    op_text = _post_text(op_post)
    op_author = _author_handle(op_post.get("author"))
    op_likes = _likes(op_post)
    if op_text:
        seg, cursor = _segment_for_text(
            op_text,
            cursor,
            extra={
                "kind": "post",
                "author": op_author,
                "likes": op_likes,
            },
        )
        segments.append(seg)

    flat_replies = _walk_replies(thread)
    flat_replies.sort(
        key=lambda entry: _likes(entry["post"]),
        reverse=True,
    )
    flat_replies = flat_replies[:top_n]

    for entry in flat_replies:
        post = entry["post"]
        body = _post_text(post)
        if not body:
            continue
        depth = entry["depth"]
        author = _author_handle(post.get("author"))
        likes = _likes(post)
        marker = "↳ " * depth
        text = f"{marker}{author} (likes {likes}): {body}"
        seg, cursor = _segment_for_text(
            text,
            cursor,
            extra={
                "kind": "reply",
                "author": author,
                "likes": likes,
                "depth": depth,
                "comment_id": _post_uri(post),
                "comment_url": _post_web_url(post),
            },
        )
        segments.append(seg)

    return segments, op_post

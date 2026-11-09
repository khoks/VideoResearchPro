"""Who posted a pasted social page, and when (T-1.5.8.4).

trafilatura's metadata pass is written for articles. On a Facebook,
Instagram, LinkedIn or X page its author is often empty or the site's
name, and its date a guess. These pages say both in their own metadata
when they say them at all: JSON-LD (``SocialMediaPosting`` and kin),
Open Graph and ``article:`` tags, ``twitter:creator``. X also says it in
the address: ``x.com/<handle>/status/<id>`` names the handle, and the id
is a snowflake that encodes the moment of posting, which matters because
X serves a page with no metadata to a client that runs no script.
LinkedIn activity ids encode their time the same way.

``read`` returns what the page or its address says and nothing else; the
connector keeps trafilatura's value for whatever is missing here. A date
outside 1995 to tomorrow is no date (htmldate, inside trafilatura, has the
same floor), because a 1970 or year-1 date is a placeholder, and D-072
leaves an unknown date out rather than storing one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

#: The social source types this reads. ``article`` keeps trafilatura's view.
PLATFORM_SOURCE_TYPES = frozenset({"fb_post", "ig_post", "li_post", "tweet"})

# A page is read up to here. JSON-LD can sit anywhere in a page, and a
# Facebook shell runs to several hundred kilobytes; this bounds the cost.
_MAX_HTML_CHARS = 2_000_000

# Same floor as htmldate's default ``min_date``.
_EARLIEST = datetime(1995, 1, 1, tzinfo=timezone.utc)

# JSON-LD types that describe a post or the media in one, best first.
_POST_TYPES = (
    "SocialMediaPosting",
    "DiscussionForumPosting",
    "BlogPosting",
    "NewsArticle",
    "Article",
    "VideoObject",
    "ImageObject",
)

# X: ``x.com/<handle>/status/<id>``. Handles are 1-15 of [A-Za-z0-9_]; these
# first segments are X's own pages, never a handle.
_X_HOSTS = ("x.com", "twitter.com")
_X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_X_RESERVED = frozenset(
    {"i", "home", "search", "explore", "intent", "share", "hashtag", "settings",
     "messages", "notifications", "compose", "login", "signup", "tos", "privacy"}
)
# Snowflake: milliseconds since X's epoch in the bits above 22. Ids below
# about an hour after that epoch are pre-snowflake sequential ids, or too
# close to it to tell apart, and say nothing about time.
_X_EPOCH_MS = 1288834974657
_X_FIRST_DATED_ID = (60 * 60 * 1000) << 22

# LinkedIn: an activity, share or ugcPost id carries Unix milliseconds in
# its first 41 bits, in the address of every public post.
_LI_POST_ID = re.compile(r"(?:activity|ugcPost|share)[-:](\d{16,20})", re.IGNORECASE)

# Instagram's description: "1,234 likes, 56 comments - <handle> on March 3,
# 2024: "caption"". The title: "<Name> on Instagram: "caption"".
_IG_HANDLE = re.compile(r"^[A-Za-z0-9_.]{1,30}$")
_IG_DESCRIPTION = re.compile(
    r"-\s+(?P<handle>[A-Za-z0-9_.]{1,30})\s+on\s+"
    r"(?P<date>(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4})\s*:"
)
_IG_TITLE_NAME = re.compile(r"^(?P<name>.+?)\s+on\s+Instagram\s*:", re.IGNORECASE)

# "Name (@handle)" in an Open Graph title, on X and Instagram.
_TITLE_HANDLE = re.compile(r"\(@(?P<handle>[A-Za-z0-9_.]{1,30})\)")
# Where the poster's part of that title ends: at " on X" / " on Instagram",
# or at the quote that opens the caption. A "(@name)" after it is someone
# the caption mentions, not the poster.
_TITLE_CAPTION_START = re.compile(
    r"\s+on\s+(?:Instagram|X|Twitter)\b|[\"“”«]", re.IGNORECASE
)

_MAX_AUTHOR_CHARS = 200


@dataclass(frozen=True)
class PostMetadata:
    """What a pasted post's page or address says. None when it says nothing.

    ``author`` is the name to show: a display name when the page gives one,
    else the handle. ``handle`` starts with ``@``. ``published_at`` is
    timezone-aware UTC, the form the other connectors store.
    """

    author: str | None = None
    handle: str | None = None
    published_at: datetime | None = None


class _HeadReader(HTMLParser):
    """Collects ``<meta>`` values and JSON-LD script bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").strip().lower()
            content = values.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "script" and values.get("type", "").strip().lower() == "application/ld+json":
            self._in_json_ld = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld.append("".join(self._buffer))
            self._buffer = []


def read(source_type: str, url: str, html: str | None) -> PostMetadata:
    """The author, handle and post date ``url``'s page and address give.

    Never raises: a page this cannot read gives an empty ``PostMetadata``.
    """
    if source_type not in PLATFORM_SOURCE_TYPES:
        return PostMetadata()
    try:
        meta, objects = _page_metadata(html)
        if source_type == "tweet":
            return _x(url, meta, objects)
        if source_type == "ig_post":
            return _instagram(meta, objects)
        if source_type == "li_post":
            return _linkedin(url, meta, objects)
        return _facebook(meta, objects)
    except Exception:  # a malformed page is a page with no metadata
        return PostMetadata()


# ---------------------------------------------------------------------------
# Per platform
# ---------------------------------------------------------------------------


def _x(url: str, meta: dict[str, str], objects: list[dict]) -> PostMetadata:
    handle, status_id = _x_address(url)
    handle = handle or _handle(meta.get("twitter:creator"), _X_HANDLE)
    name, ld_handle = _json_ld_author(objects)
    ld_handle = _handle(ld_handle, _X_HANDLE)
    handle = handle or ld_handle or _title_handle(meta, _X_HANDLE)
    if name and ld_handle and handle and ld_handle.lower() != handle.lower():
        # The JSON-LD author is another account (a quoted or parent post):
        # its name is not this post's poster's, so the handle stands alone.
        name = None
    published = _x_snowflake_time(status_id) or _json_ld_date(objects) or _meta_date(meta)
    return PostMetadata(author=name or handle, handle=handle, published_at=published)


def _instagram(meta: dict[str, str], objects: list[dict]) -> PostMetadata:
    name, ld_handle = _json_ld_author(objects)
    description = _IG_DESCRIPTION.search(meta.get("og:description", ""))
    handle = (
        _handle(ld_handle, _IG_HANDLE)
        or _handle(description.group("handle") if description else None, _IG_HANDLE)
        or _title_handle(meta, _IG_HANDLE)
    )
    if not name:
        title = _IG_TITLE_NAME.match(meta.get("og:title", ""))
        name = _clean_name(title.group("name")) if title else None
    published = _json_ld_date(objects) or _meta_date(meta)
    if published is None and description:
        published = to_utc_post_date(_strptime(description.group("date"), "%B %d, %Y"))
    return PostMetadata(author=name or handle, handle=handle, published_at=published)


def _linkedin(url: str, meta: dict[str, str], objects: list[dict]) -> PostMetadata:
    name, _ = _json_ld_author(objects)
    name = name or _meta_author(meta)
    published = _linkedin_id_time(url) or _json_ld_date(objects) or _meta_date(meta)
    return PostMetadata(author=name, published_at=published)


def _facebook(meta: dict[str, str], objects: list[dict]) -> PostMetadata:
    name, _ = _json_ld_author(objects)
    name = name or _meta_author(meta)
    return PostMetadata(author=name, published_at=_json_ld_date(objects) or _meta_date(meta))


# ---------------------------------------------------------------------------
# The address
# ---------------------------------------------------------------------------


def _x_address(url: str) -> tuple[str | None, str | None]:
    """``(@handle, status id)`` from an X post's address, each None if absent."""
    try:
        parts = urlsplit(url)
    except (TypeError, ValueError):
        return None, None
    host = (parts.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _X_HOSTS):
        return None, None
    segments = [s for s in parts.path.split("/") if s]
    for i, segment in enumerate(segments[:-1]):
        if segment.lower() in ("status", "statuses") and segments[i + 1].isdigit():
            status_id = segments[i + 1]
            first = segments[0] if i == 1 else None
            if first and first.lower() not in _X_RESERVED and _X_HANDLE.match(first):
                return "@" + first, status_id
            return None, status_id
    return None, None


def _x_snowflake_time(status_id: str | None) -> datetime | None:
    if not status_id:
        return None
    value = int(status_id)
    if value < _X_FIRST_DATED_ID:
        return None
    return to_utc_post_date(datetime.fromtimestamp(((value >> 22) + _X_EPOCH_MS) / 1000, tz=timezone.utc))


def _linkedin_id_time(url: str) -> datetime | None:
    match = _LI_POST_ID.search(unquote(url or ""))
    if not match:
        return None
    return to_utc_post_date(datetime.fromtimestamp((int(match.group(1)) >> 22) / 1000, tz=timezone.utc))


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def _page_metadata(html: str | None) -> tuple[dict[str, str], list[dict]]:
    if not html:
        return {}, []
    reader = _HeadReader()
    reader.feed(html[:_MAX_HTML_CHARS])
    reader.close()
    objects: list[dict] = []
    for body in reader.json_ld:
        try:
            data = json.loads(body, strict=False)
        except (ValueError, TypeError):
            continue
        objects.extend(_walk(data))
    return reader.meta, _posts_first(objects)


def _walk(data: Any, depth: int = 0) -> Iterator[dict]:
    """Every JSON-LD object with a post type, ``@graph`` and lists opened."""
    if depth > 4:
        return
    if isinstance(data, list):
        for item in data:
            yield from _walk(item, depth + 1)
    elif isinstance(data, dict):
        if _types(data) & set(_POST_TYPES):
            yield data
        if "@graph" in data:
            yield from _walk(data["@graph"], depth + 1)
        main = data.get("mainEntity")
        if isinstance(main, (dict, list)):
            yield from _walk(main, depth + 1)


def _types(obj: dict) -> set[str]:
    value = obj.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    return set()


def _posts_first(objects: list[dict]) -> list[dict]:
    def rank(obj: dict) -> int:
        return min((_POST_TYPES.index(t) for t in _types(obj) if t in _POST_TYPES), default=len(_POST_TYPES))

    return sorted(objects, key=rank)


def _json_ld_author(objects: list[dict]) -> tuple[str | None, str | None]:
    """``(name, handle)`` of the first post's author that gives either."""
    for obj in objects:
        author = obj.get("author") or obj.get("creator")
        if isinstance(author, list):
            author = next((a for a in author if a), None)
        if isinstance(author, str):
            name = _clean_name(author)
            if name:
                return name, None
            continue
        if isinstance(author, dict):
            name = _clean_name(author.get("name"))
            handle = author.get("alternateName")
            if not isinstance(handle, str) or not handle.strip():
                handle = author.get("identifier")
            # A bare number is the account's id, not its handle.
            handle = handle if isinstance(handle, str) and not handle.strip().isdigit() else None
            if name or handle:
                return name, handle
    return None, None


def _json_ld_date(objects: list[dict]) -> datetime | None:
    for obj in objects:
        for key in ("datePublished", "dateCreated", "uploadDate"):
            value = _parse_date(obj.get(key))
            if value is not None:
                return value
    return None


def _meta_author(meta: dict[str, str]) -> str | None:
    for key in ("article:author", "author"):
        name = _clean_name(meta.get(key))
        if name:
            return name
    return None


def _meta_date(meta: dict[str, str]) -> datetime | None:
    for key in ("article:published_time", "og:published_time", "datepublished", "date"):
        value = _parse_date(meta.get(key))
        if value is not None:
            return value
    return None


def _title_handle(meta: dict[str, str], pattern: re.Pattern) -> str | None:
    """The ``(@handle)`` in the poster's part of the Open Graph title only:
    the caption that follows can mention anyone."""
    title = meta.get("og:title", "")
    caption = _TITLE_CAPTION_START.search(title)
    match = _TITLE_HANDLE.search(title[: caption.start()] if caption else title)
    return _handle(match.group("handle"), pattern) if match else None


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _handle(value: Any, pattern: re.Pattern) -> str | None:
    """``@name`` when ``value`` is a handle this platform allows."""
    if not isinstance(value, str):
        return None
    bare = value.strip().lstrip("@")
    return "@" + bare if bare and pattern.match(bare) else None


def _clean_name(value: Any) -> str | None:
    """A display name, or None for nothing, a link or a bare number."""
    if not isinstance(value, str):
        return None
    name = " ".join(value.split())
    if not name or "://" in name or name.startswith("www.") or name.isdigit():
        return None
    return name[:_MAX_AUTHOR_CHARS]


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return to_utc_post_date(parsed)


def _strptime(value: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def to_utc_post_date(value: datetime | None) -> datetime | None:
    """A post date as the connectors store it: timezone-aware UTC.

    A naive value is read as UTC (a date with no time is midnight UTC). One
    before 1995 or after tomorrow is a placeholder, not a date, so None.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if value < _EARLIEST or value > datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return value

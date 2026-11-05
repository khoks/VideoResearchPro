"""Which source types a topic run searches (S-1.5.13).

A topic job's ``source_types`` decide which connectors the worker fans out
to: ``video`` goes through the LangGraph search agent, every other type
through ``connector_dispatch`` (S-1.5.11). Until S-1.5.13 nothing wrote
``jobs.source_types_json``, so every run searched YouTube only.

This module is the one place that knows:

- which types a run can search at all (``SEARCHABLE_SOURCE_TYPES``) and
  which only enter through the library (upload / paste);
- which of them need an operator setting, and the ``/health`` capability
  that reports it, so the submit form offers only what this install can
  run and the API refuses the rest with a 422;
- what a podcast run needs beyond search (``transcription_gap``);
- how a run's budget is shared, and given on when a source comes back
  short (``share_limits``, ``redistribute``);
- how the choice is stored: NULL for the default (YouTube only), so the
  column means exactly one thing, as with ``output_length``.

The checks read settings, never the connector registry: tests swap
connectors in and out of the registry, and a type's availability is an
install fact, not a registration accident.
"""
from __future__ import annotations

import json
import logging
import math
import shutil
from typing import Collection, Iterable, Mapping

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TYPES: tuple[str, ...] = ("video",)

# The types a topic run can search, in the order the worker dispatches
# them and the submit form lists them. Stored lists are put in this order,
# so a template does not gain a version because a reader clicked in a
# different order.
SEARCHABLE_SOURCE_TYPES: tuple[str, ...] = (
    "video",
    "reddit_post",
    "hn_story",
    "mastodon_post",
    "bluesky_post",
    "podcast_episode",
    "article",
    "tweet",
)

# Registered connectors whose ``search()`` raises NotImplementedError: they
# are ingested from the library's Add sources tab (upload, paste), never
# searched by a run.
LIBRARY_ONLY_SOURCE_TYPES: tuple[str, ...] = ("pdf", "fb_post", "ig_post", "li_post")

# The `/health` capability that says whether this install can search a type.
# YouTube has none: it is every run's default. The frontend mirrors this map
# in `frontend/src/utils/jobForm.ts` (SOURCE_TYPE_OPTIONS).
CAPABILITY_FOR_SOURCE_TYPE: dict[str, str] = {
    "reddit_post": "reddit_search_enabled",
    "hn_story": "hn_search_enabled",
    "mastodon_post": "mastodon_search_enabled",
    "bluesky_post": "bluesky_search_enabled",
    "podcast_episode": "podcast_search_enabled",
    "article": "article_search_enabled",
    "tweet": "twitter_search_enabled",
}

# What a run calls each type, on its notes (frontend: SOURCE_TYPE_OPTIONS).
SOURCE_TYPE_LABELS: dict[str, str] = {
    "video": "YouTube",
    "reddit_post": "Reddit",
    "hn_story": "Hacker News",
    "mastodon_post": "Mastodon",
    "bluesky_post": "Bluesky",
    "podcast_episode": "Podcasts",
    "article": "Web articles",
    "tweet": "X / Twitter",
}

# Types billed by what a search reads, not by the request. Asked for their
# share only, so spare budget never makes a run read more of them.
METERED_SOURCE_TYPES: frozenset[str] = frozenset({"tweet"})

# `plan_searches` asks the model for 4 to 6 broad queries, and each can spend
# every page `search_videos` allows.
_MOST_BROAD_QUERIES = 6
_YOUTUBE_UNITS_PER_SEARCH_PAGE = 100
_YOUTUBE_RESULTS_PER_PAGE = 50


def missing_setting(source_type: str) -> str | None:
    """The setting this install lacks to search ``source_type``, or None."""
    if source_type == "mastodon_post":
        # Both have defaults, so only a setting blanked on purpose lands here
        # (T-1.5.13.6). Blank, the client would ask for a relative URL.
        if not (settings.MASTODON_INSTANCE_BASE or "").strip():
            return "MASTODON_INSTANCE_BASE"
    elif source_type == "bluesky_post":
        if not (settings.BLUESKY_XRPC_BASE or "").strip():
            return "BLUESKY_XRPC_BASE"
    elif source_type == "reddit_post":
        if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
            return "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET"
    elif source_type == "article":
        if not settings.BRAVE_SEARCH_API_KEY:
            return "BRAVE_SEARCH_API_KEY"
    elif source_type == "tweet":
        if not settings.TWITTER_BEARER_TOKEN:
            return "TWITTER_BEARER_TOKEN"
    return None


def transcription_gap(source_types: Iterable[str]) -> str | None:
    """Why this install would lose podcast episodes after approval, or None.

    Searching podcasts needs no credential, so ``missing_setting`` is right to
    say nothing and the run is accepted. Reading them can need more: an episode
    with no published transcript goes to Whisper at extraction, which takes an
    OpenAI key and a non-zero ``WHISPER_MAX_PER_JOB``, and one past Whisper's
    upload cap has to be split, which takes ffmpeg and ffprobe. Episodes are
    lost one by one only after approval, so a template says so up front. The
    message is reader-facing.
    """
    if "podcast_episode" not in source_types:
        return None
    if not settings.OPENAI_API_KEY or settings.WHISPER_MAX_PER_JOB <= 0:
        return (
            "Podcasts without a published transcript need Whisper, which this "
            "install has not set up, so only episodes that publish one can be read."
        )
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return (
            "Long podcasts without a published transcript need ffmpeg to be split "
            "for Whisper, which this install does not have, so they will be skipped."
        )
    return None


def is_available(source_type: str) -> bool:
    """True when a run on this install can search ``source_type``."""
    return source_type in SEARCHABLE_SOURCE_TYPES and missing_setting(source_type) is None


def available_source_types() -> list[str]:
    return [st for st in SEARCHABLE_SOURCE_TYPES if is_available(st)]


def capabilities(held: Collection[str] = ()) -> dict[str, bool]:
    """The `/health` capability flags, one per type a setting or a hold can
    take away. ``held`` is the types on hold after refusing this install
    (``source_refusal_service``): the form stops offering them."""
    return {
        cap: is_available(st) and st not in held
        for st, cap in CAPABILITY_FOR_SOURCE_TYPE.items()
    }


def normalise(values: Iterable[str]) -> list[str]:
    """Validate a requested list and return it de-duplicated, in canonical
    order. Raises ``ValueError`` with a reader-facing message (the schema
    turns it into a 422) for an empty list, an unknown type, a type that is
    only ingested through the library, or one this install has not set up.
    """
    requested: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if value and value not in requested:
            requested.append(value)
    if not requested:
        raise ValueError(
            "source_types needs at least one source type; leave it out to search YouTube only"
        )

    unknown = [
        st for st in requested
        if st not in SEARCHABLE_SOURCE_TYPES and st not in LIBRARY_ONLY_SOURCE_TYPES
    ]
    if unknown:
        raise ValueError(
            f"Unknown source type: {', '.join(unknown)}. "
            f"A run can search: {', '.join(SEARCHABLE_SOURCE_TYPES)}"
        )
    library_only = [st for st in requested if st in LIBRARY_ONLY_SOURCE_TYPES]
    if library_only:
        raise ValueError(
            f"{', '.join(library_only)} cannot be searched; add these from the "
            "Library's Add sources tab instead"
        )
    unavailable = [st for st in requested if missing_setting(st) is not None]
    if unavailable:
        details = "; ".join(f"{st} needs {missing_setting(st)}" for st in unavailable)
        raise ValueError(f"Not set up on this install: {details}")

    chosen = set(requested)
    return [st for st in SEARCHABLE_SOURCE_TYPES if st in chosen]


def is_default(values: Iterable[str] | None) -> bool:
    return values is None or list(values) == list(DEFAULT_SOURCE_TYPES)


def share_limits(total: int, source_types: Iterable[str]) -> dict[str, int]:
    """Split a run's ``num_videos`` across the types it searches.

    ``num_videos`` is the run's whole document budget, the figure the tier
    cap (``num_videos_cap``) is checked against, so a run that searches
    several sources must not collect ``num_videos`` from each. The split is
    as even as it can be; the remainder goes to the earlier types in the
    given (canonical) order. ``JobCreate`` refuses fewer documents than
    types, so every type normally gets at least one; a type left with zero
    (a row written some other way) is simply not searched.
    """
    types = list(dict.fromkeys(source_types))
    if not types:
        return {}
    budget = max(0, int(total))
    base, remainder = divmod(budget, len(types))
    return {st: base + (1 if i < remainder else 0) for i, st in enumerate(types)}


def redistribute(shares: Mapping[str, int], capacity: Mapping[str, int | None]) -> dict[str, int]:
    """Give what a source could not fill to the sources that can use it.

    ``capacity`` is how many a source has to offer, and None means no known
    end (YouTube before it has searched). A source missing from it was not
    searched. The run's total never grows: each source keeps what it can of
    its share, and what is left goes one at a time around the sources with
    room, in order, so it spreads as evenly as ``share_limits`` does.
    """

    def has_room(st: str, taken: int) -> bool:
        have = capacity.get(st, 0)
        return have is None or taken < have

    limits: dict[str, int] = {}
    for st, share in shares.items():
        have = capacity.get(st, 0)
        limits[st] = share if have is None else min(share, have)
    spare = sum(shares.values()) - sum(limits.values())
    while spare > 0:
        room = [st for st, taken in limits.items() if has_room(st, taken)]
        if not room:
            break
        for st in room[:spare]:
            limits[st] += 1
        spare -= min(spare, len(room))
    return limits


def youtube_search_units(target: int) -> int:
    """The most ``search.list`` can cost the search agent for ``target`` videos.

    Each broad query asks for ``max(target * 3, 50)`` results at 100 units a
    page of 50, up to ``YOUTUBE_SEARCH_MAX_PAGES`` pages. The agent stops once
    it holds five candidates for every video it wants, so a run usually spends
    100 units per 10 videos; this is the ceiling for a quota check, not an
    estimate. ``videos.list`` and ``channels.list`` add a unit per 50 ids.
    """
    wanted = max(target * 3, _YOUTUBE_RESULTS_PER_PAGE)
    pages = min(
        max(1, settings.YOUTUBE_SEARCH_MAX_PAGES),
        math.ceil(wanted / _YOUTUBE_RESULTS_PER_PAGE),
    )
    return _YOUTUBE_UNITS_PER_SEARCH_PAGE * pages * _MOST_BROAD_QUERIES


def to_column(values: Iterable[str] | None) -> str | None:
    """What ``jobs.source_types_json`` stores: NULL for the default."""
    if values is None:
        return None
    listed = list(values)
    if not listed or is_default(listed):
        return None
    return json.dumps(listed)


def from_column(raw: str | None, *, job_id: str | None = None) -> list[str]:
    """Decode ``jobs.source_types_json``, defaulting to YouTube only for
    NULL (every run before S-1.5.13), an empty list or a malformed value.
    Stored values pass through unfiltered: the worker's dispatch isolates a
    type it cannot search."""
    if not raw:
        return list(DEFAULT_SOURCE_TYPES)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Job %s has malformed source_types_json %r; defaulting to ['video']",
            job_id,
            raw,
        )
        return list(DEFAULT_SOURCE_TYPES)
    if not isinstance(parsed, list) or not parsed:
        return list(DEFAULT_SOURCE_TYPES)
    resolved = [str(st) for st in parsed if str(st)]
    return resolved or list(DEFAULT_SOURCE_TYPES)

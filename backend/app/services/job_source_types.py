"""Which source types a topic run searches (S-1.5.13).

A topic job's ``source_types`` decide which connectors the worker fans out
to: ``video`` goes through the LangGraph search agent, every other type
through ``connector_dispatch`` (S-1.5.11). Until S-1.5.13 nothing wrote
``jobs.source_types_json``, so every run searched YouTube only.

This module is the one place that knows:

- which types a run can search at all (``SEARCHABLE_SOURCE_TYPES``) and
  which only enter through the library (upload / paste);
- which of them need an operator credential, and the ``/health``
  capability that reports it, so the submit form offers only what this
  install can run and the API refuses the rest with a 422;
- how the choice is stored: NULL for the default (YouTube only), so the
  column means exactly one thing, as with ``output_length``.

The checks read settings, never the connector registry: tests swap
connectors in and out of the registry, and a type's availability is an
install fact, not a registration accident.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

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

# Types that need an operator credential, and the `/health` capability
# that says whether this install has it. The frontend mirrors this map in
# `frontend/src/utils/jobForm.ts` (SOURCE_TYPE_OPTIONS).
CAPABILITY_FOR_SOURCE_TYPE: dict[str, str] = {
    "reddit_post": "reddit_search_enabled",
    "article": "article_search_enabled",
    "tweet": "twitter_search_enabled",
}


def missing_setting(source_type: str) -> str | None:
    """The setting this install lacks to search ``source_type``, or None."""
    if source_type == "reddit_post":
        if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
            return "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET"
    elif source_type == "article":
        if not settings.BRAVE_SEARCH_API_KEY:
            return "BRAVE_SEARCH_API_KEY"
    elif source_type == "tweet":
        if not settings.TWITTER_BEARER_TOKEN:
            return "TWITTER_BEARER_TOKEN"
    return None


def is_available(source_type: str) -> bool:
    """True when a run on this install can search ``source_type``."""
    return source_type in SEARCHABLE_SOURCE_TYPES and missing_setting(source_type) is None


def available_source_types() -> list[str]:
    return [st for st in SEARCHABLE_SOURCE_TYPES if is_available(st)]


def capabilities() -> dict[str, bool]:
    """The `/health` capability flags for the credential-gated types."""
    return {cap: is_available(st) for st, cap in CAPABILITY_FOR_SOURCE_TYPE.items()}


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

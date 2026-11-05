"""What a run has to tell its reader (S-1.5.14).

"No results" and "the service refused" looked the same on a run, and so did a
share of the budget lost to an empty source. Each note here is one such fact,
stored on ``jobs.run_notes_json`` and returned as ``JobResponse.run_notes``,
so it stays after the progress message has moved on.

A note is ``{kind, text}``, and ``source_type`` when it is about one source.
``text`` is for the reader and is written here. It never carries exception
text, which can hold a request URL, and a YouTube API key is in the query
string of one.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Mapping

from app.models.job import Job
from app.services.job_source_types import SOURCE_TYPE_LABELS
from app.services.source_failure import QUOTA_SPENT, RATE_LIMITED, REFUSED, SourceFailure

logger = logging.getLogger(__name__)

SOURCE_UNAVAILABLE = "source_unavailable"
SOURCE_EMPTY = "source_empty"
BUDGET_MOVED = "budget_moved"
TOP_UP_SKIPPED = "top_up_skipped"
WHISPER_MINUTES_SPENT = "whisper_minutes_spent"


def _label(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(source_type, source_type.replace("_", " "))


def _listed(items: Iterable[str]) -> str:
    names = list(items)
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def unavailable(source_type: str, failure: SourceFailure) -> dict:
    label = _label(source_type)
    if failure.kind == REFUSED:
        why = f"it refused the search (HTTP {failure.status})"
    elif failure.kind == RATE_LIMITED:
        why = f"it asked this install to slow down (HTTP {failure.status})"
    elif failure.kind == QUOTA_SPENT:
        why = "its daily API quota is spent, and resets at midnight Pacific Time"
    elif failure.status:
        why = f"the search failed (HTTP {failure.status})"
    else:
        why = "the search failed"
    return {
        "kind": SOURCE_UNAVAILABLE,
        "source_type": source_type,
        "text": f"{label} was unavailable: {why}.",
    }


def empty(source_type: str) -> dict:
    return {
        "kind": SOURCE_EMPTY,
        "source_type": source_type,
        "text": f"{_label(source_type)} found nothing for this topic.",
    }


def budget_moved(shares: Mapping[str, int], limits: Mapping[str, int]) -> dict | None:
    """Where a short source's share went, or None if nothing moved."""
    short = [st for st, share in shares.items() if limits.get(st, 0) < share]
    gained = {st: limits[st] - share for st, share in shares.items() if limits.get(st, 0) > share}
    moved = sum(gained.values())
    if not moved:
        return None
    return {
        "kind": BUDGET_MOVED,
        "text": (
            f"{moved} {'result' if moved == 1 else 'results'} that "
            f"{_listed(_label(st) for st in short)} could not fill went to "
            f"{_listed(f'{_label(st)} ({n})' for st, n in gained.items())}."
        ),
    }


def top_up_skipped(wanted: int, units_needed: int, units_left: int) -> dict:
    return {
        "kind": TOP_UP_SKIPPED,
        "source_type": "video",
        "text": (
            f"YouTube was not given the {wanted} spare "
            f"{'result' if wanted == 1 else 'results'}: searching for them could "
            f"use {units_needed} quota units and {max(0, units_left)} are left today."
        ),
    }


def whisper_minutes_spent(used_seconds: float, cap_minutes: int, skipped: int) -> dict:
    return {
        "kind": WHISPER_MINUTES_SPENT,
        "text": (
            f"Whisper stopped after {round(used_seconds / 60)} minutes of audio, "
            f"the limit is {cap_minutes} (WHISPER_MAX_MINUTES_PER_JOB). "
            f"{skipped} {'source' if skipped == 1 else 'sources'} could not be read."
        ),
    }


def read(job: Job) -> list[dict]:
    raw = job.run_notes_json
    if not raw:
        return []
    try:
        notes = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Job %s has malformed run_notes_json", job.id)
        return []
    return notes if isinstance(notes, list) else []


def add(job: Job, notes: Iterable[dict]) -> None:
    """Add ``notes`` to ``job``, the caller commits. A note of the same kind
    about the same source replaces the old one, so a redelivered task leaves
    one note, not two."""
    fresh = list(notes)
    if not fresh:
        return
    replaced = {(n["kind"], n.get("source_type")) for n in fresh}
    kept = [n for n in read(job) if (n.get("kind"), n.get("source_type")) not in replaced]
    job.run_notes_json = json.dumps(kept + fresh)

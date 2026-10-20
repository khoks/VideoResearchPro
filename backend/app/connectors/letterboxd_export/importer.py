"""Letterboxd account export (S-3.7.5, T-3.7.5.3). Letterboxd's API refuses
"LLM or GPT-related use" and personal projects; the export zip is the way.

The zip (``letterboxd-<user>-<date>-utc.zip``) holds CSVs:

- ``diary.csv`` — dated viewings: Date, Name, Year, Letterboxd URI, Rating,
  Rewatch, Tags, Watched Date. Each is a ``watched_film`` event.
- ``reviews.csv`` — the same columns plus Review: each is a ``reviewed_film``
  event whose text is the review, the user's own words.
- ``watched.csv`` — every film marked watched, once, dated by when it was
  logged. Films with no diary entry become an undated ``watched_film``.
- ``watchlist.csv`` — ``want_to_watch`` events.
- ``ratings.csv`` — ratings, added to the watched-only films.
"""
from __future__ import annotations

import csv
from typing import Any, Iterator

from app.config import settings
from app.connectors.archive import ExportUnreadable, ImportPreview, ImportSource, parse_datetime
from app.connectors.base import ActivityEvent

NAME = "letterboxd_export"
LABEL = "Letterboxd films"

_DATE = ("%Y-%m-%d",)


def _member(source: ImportSource, name: str) -> str | None:
    for n in source.member_names():
        if n.replace("\\", "/").rsplit("/", 1)[-1].lower() == name:
            return n
    return None


def _rows(source: ImportSource, name: str) -> Iterator[dict]:
    member = _member(source, name)
    if member is None:
        return
    with source.open_text(member) as stream:
        yield from csv.DictReader(stream)


def _film(row: dict) -> tuple[str, str]:
    name, year = (row.get("Name") or "").strip(), (row.get("Year") or "").strip()
    return name, year


def _title(name: str, year: str) -> str:
    return f"{name} ({year})" if year else name


def _rating(value: str | None) -> float | None:
    try:
        return float(value) if value and value.strip() else None
    except ValueError:
        return None


def events(source: ImportSource, stats: dict[str, int]) -> Iterator[ActivityEvent]:
    diary_films: set[tuple[str, str]] = set()
    for row in _rows(source, "diary.csv"):
        name, year = _film(row)
        when = parse_datetime(row.get("Watched Date"), _DATE) or parse_datetime(row.get("Date"), _DATE)
        if not name or when is None:
            continue
        diary_films.add((name, year))
        yield ActivityEvent(
            external_id=f"lb:diary:{(row.get('Letterboxd URI') or '').strip() or name + year + when.date().isoformat()}",
            event_type="watched_film",
            occurred_at=when,
            payload={
                "title": _title(name, year), "film": name, "year": year or None,
                "rating": _rating(row.get("Rating")), "rewatch": (row.get("Rewatch") or "").strip().lower() == "yes",
                "tags": [t.strip() for t in (row.get("Tags") or "").split(",") if t.strip()],
                "uri": (row.get("Letterboxd URI") or "").strip() or None,
            },
        )
    for row in _rows(source, "reviews.csv"):
        name, year = _film(row)
        review = (row.get("Review") or "").strip()
        when = parse_datetime(row.get("Watched Date"), _DATE) or parse_datetime(row.get("Date"), _DATE)
        if not name or not review or when is None:
            continue
        yield ActivityEvent(
            external_id=f"lb:review:{(row.get('Letterboxd URI') or '').strip() or name + year + when.date().isoformat()}",
            event_type="reviewed_film",
            occurred_at=when,
            payload={"title": _title(name, year), "film": name, "year": year or None, "rating": _rating(row.get("Rating"))},
            text_content=review,
        )
    ratings = {_film(r): _rating(r.get("Rating")) for r in _rows(source, "ratings.csv")}
    for row in _rows(source, "watched.csv"):
        name, year = _film(row)
        when = parse_datetime(row.get("Date"), _DATE)
        if not name or when is None or (name, year) in diary_films:
            continue
        yield ActivityEvent(
            external_id=f"lb:watched:{(row.get('Letterboxd URI') or '').strip() or name + year}",
            event_type="watched_film",
            occurred_at=when,
            payload={
                "title": _title(name, year), "film": name, "year": year or None,
                "rating": ratings.get((name, year)), "undated_viewing": True,
                "uri": (row.get("Letterboxd URI") or "").strip() or None,
            },
        )
    for row in _rows(source, "watchlist.csv"):
        name, year = _film(row)
        when = parse_datetime(row.get("Date"), _DATE)
        if not name or when is None:
            continue
        yield ActivityEvent(
            external_id=f"lb:watchlist:{(row.get('Letterboxd URI') or '').strip() or name + year}",
            event_type="want_to_watch",
            occurred_at=when,
            payload={"title": _title(name, year), "film": name, "year": year or None},
        )


def sniff(source: ImportSource) -> bool:
    try:
        return source.is_zip and _member(source, "watched.csv") is not None and (
            _member(source, "diary.csv") is not None or _member(source, "watchlist.csv") is not None
        )
    except Exception:
        return False


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    counts = {"watched": 0, "reviews": 0, "watchlist": 0, "rated": 0}
    first = last = None
    for ev in events(source, {}):
        key = {"watched_film": "watched", "reviewed_film": "reviews", "want_to_watch": "watchlist"}[ev.event_type]
        counts[key] += 1
        counts["rated"] += bool(ev.payload.get("rating")) and ev.event_type == "watched_film"
        first = min(first, ev.occurred_at) if first else ev.occurred_at
        last = max(last, ev.occurred_at) if last else ev.occurred_at
    if not any(counts.values()):
        raise ExportUnreadable("No films were found in this Letterboxd export.")
    return ImportPreview(
        importer=NAME, label=LABEL,
        summary={**counts, "first_at": first.isoformat() if first else None, "last_at": last.isoformat() if last else None},
        options={}, warnings=[],
    )


class LetterboxdExportImporter:
    name = NAME
    display_name = LABEL
    privacy_weight = "medium"
    consent_disclosure = (
        "Reads the account export you downloaded from Letterboxd: the films you watched "
        "and when, your ratings, your watchlist, and your reviews, which count as your "
        "own words. The file itself is not kept."
    )

    def accepts(self, filename: str) -> bool:
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return base.startswith("letterboxd-") and base.endswith(".zip")

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(self, stream, *, tenant_id: str, options: dict[str, Any] | None = None,
              filename: str = "letterboxd.zip", stats: dict[str, int] | None = None) -> Iterator[ActivityEvent]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        yield from events(source, stats if stats is not None else {})


IMPORTER = LetterboxdExportImporter()

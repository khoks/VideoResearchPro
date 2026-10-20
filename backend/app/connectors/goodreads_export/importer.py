"""Goodreads library export (S-3.7.5, T-3.7.5.3). The Goodreads API closed in
December 2020; the CSV from "Import and export" is the only way out.

``goodreads_library_export.csv`` has one row per book: Book Id, Title,
Author, ISBN13 (as ``="…"``), My Rating, Year Published, Number of Pages,
Date Read, Date Added, Bookshelves, Exclusive Shelf, My Review, Private
Notes, Read Count. Each row becomes one event by its exclusive shelf:
``read_book`` (dated by Date Read, else Date Added), ``reading_book`` or
``want_to_read``. The user's review and private notes are their own words
and become the event's text.
"""
from __future__ import annotations

import csv
import re
from typing import Any, Iterator

from app.config import settings
from app.connectors.archive import ExportUnreadable, ImportPreview, ImportSource, parse_datetime
from app.connectors.base import ActivityEvent

NAME = "goodreads_export"
LABEL = "Goodreads library"

_SHELF_EVENT = {"read": "read_book", "currently-reading": "reading_book", "to-read": "want_to_read"}
_DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d")
_TAGS = re.compile(r"<br\s*/?>", re.I)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _isbn(value: str | None) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", value or "")
    return digits or None


def _own_words(row: dict) -> str | None:
    review = _TAGS.sub("\n", _clean(row.get("My Review")))
    notes = _clean(row.get("Private Notes"))
    parts = [p for p in (review, f"Private notes: {notes}" if notes else "") if p]
    return "\n\n".join(parts) or None


def events(source: ImportSource, stats: dict[str, int]) -> Iterator[ActivityEvent]:
    with source.open_text(None) as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "Book Id" not in reader.fieldnames:
            raise ExportUnreadable("This CSV is not a Goodreads library export.")
        for row in reader:
            shelf = _clean(row.get("Exclusive Shelf")) or "read"
            kind = _SHELF_EVENT.get(shelf, "shelved_book")
            when = None
            if kind == "read_book":
                when = parse_datetime(row.get("Date Read"), _DATE_FORMATS)
            when = when or parse_datetime(row.get("Date Added"), _DATE_FORMATS)
            if when is None:
                stats["undated_skipped"] = stats.get("undated_skipped", 0) + 1
                continue
            title, author = _clean(row.get("Title")), _clean(row.get("Author"))
            rating = int(_clean(row.get("My Rating")) or 0)
            yield ActivityEvent(
                external_id=f"gr:{_clean(row.get('Book Id'))}:{shelf}",
                event_type=kind,
                occurred_at=when,
                payload={
                    "title": f"{title} by {author}" if author else title,
                    "book": title,
                    "author": author or None,
                    "isbn13": _isbn(row.get("ISBN13")),
                    "rating": rating or None,
                    "shelf": shelf,
                    "shelves": [s.strip() for s in _clean(row.get("Bookshelves")).split(",") if s.strip()],
                    "year_published": _clean(row.get("Year Published")) or None,
                    "pages": _clean(row.get("Number of Pages")) or None,
                    "read_count": _clean(row.get("Read Count")) or None,
                },
                text_content=_own_words(row),
            )


def sniff(source: ImportSource) -> bool:
    try:
        if source.is_zip or not source.filename.lower().endswith(".csv"):
            return False
        head = source.head(4096).decode("utf-8-sig", "replace")
        return "Book Id" in head and "Exclusive Shelf" in head
    except Exception:
        return False


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    stats: dict[str, int] = {}
    counts = {"books": 0, "read": 0, "reading": 0, "want_to_read": 0, "reviewed": 0, "rated": 0}
    first = last = None
    for ev in events(source, stats):
        counts["books"] += 1
        key = {"read_book": "read", "reading_book": "reading", "want_to_read": "want_to_read"}.get(ev.event_type)
        if key:
            counts[key] += 1
        counts["reviewed"] += bool(ev.text_content)
        counts["rated"] += bool(ev.payload.get("rating"))
        first = min(first, ev.occurred_at) if first else ev.occurred_at
        last = max(last, ev.occurred_at) if last else ev.occurred_at
    if not counts["books"]:
        raise ExportUnreadable("No books were found in this Goodreads export.")
    return ImportPreview(
        importer=NAME, label=LABEL,
        summary={**counts, "first_at": first.isoformat() if first else None, "last_at": last.isoformat() if last else None},
        options={}, warnings=[],
    )


class GoodreadsExportImporter:
    name = NAME
    display_name = LABEL
    privacy_weight = "medium"
    consent_disclosure = (
        "Reads the library you exported from Goodreads: what you read, are reading and "
        "want to read, your ratings, and your reviews and private notes, which count as "
        "your own words. The file itself is not kept."
    )

    def accepts(self, filename: str) -> bool:
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return base.startswith("goodreads_library_export") and base.endswith(".csv")

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(self, stream, *, tenant_id: str, options: dict[str, Any] | None = None,
              filename: str = "goodreads_library_export.csv", stats: dict[str, int] | None = None) -> Iterator[ActivityEvent]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        yield from events(source, stats if stats is not None else {})


IMPORTER = GoodreadsExportImporter()

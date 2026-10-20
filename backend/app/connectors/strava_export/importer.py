"""Strava bulk export (S-3.7.5, T-3.7.5.3).

Strava's API agreement (in force from 2026-06-01, §5.3) forbids using its
API data with any AI application, so Echo has no Strava connector. The bulk
export ("Download or delete your account") is the user's own copy of their
data, outside that agreement; the plan asks for counsel to confirm before a
SaaS launch relies on it.

The zip (``export_<athlete id>.zip``) holds ``activities.csv``: Activity ID,
Activity Date ("Jan 31, 2024, 9:05:00 PM", UTC), Activity Name, Activity
Type, Activity Description, Elapsed Time, Moving Time, Distance, and dozens
more. Each row is one ``workout`` event. GPS tracks (``activities/*.gpx``,
``.fit``) are never read: where the user runs is not needed to know that
they run.
"""
from __future__ import annotations

import csv
import re
from typing import Any, Iterator

from app.config import settings
from app.connectors.archive import ExportUnreadable, ImportPreview, ImportSource, parse_datetime
from app.connectors.base import ActivityEvent

NAME = "strava_export"
LABEL = "Strava activities"

_DATE = ("%b %d, %Y, %I:%M:%S %p", "%d %b %Y, %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _member(source: ImportSource) -> str | None:
    if not source.is_zip:
        return None
    for n in source.member_names():
        if n.replace("\\", "/").rsplit("/", 1)[-1].lower() == "activities.csv":
            return n
    return None


def _number(value: str | None) -> float | None:
    try:
        return round(float((value or "").replace(",", "")), 2) if value and value.strip() else None
    except ValueError:
        return None


def events(source: ImportSource, stats: dict[str, int]) -> Iterator[ActivityEvent]:
    member = _member(source)
    with source.open_text(member) as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration:
            raise ExportUnreadable("activities.csv is empty.") from None
        # Columns repeat (two "Distance", two "Elapsed Time"); the first of
        # each is the summary value in the athlete's units.
        index: dict[str, int] = {}
        for i, col in enumerate(header):
            index.setdefault(col.strip(), i)
        if "Activity ID" not in index or "Activity Date" not in index:
            raise ExportUnreadable("This activities.csv is not from a Strava export.")

        def get(row: list[str], col: str) -> str:
            i = index.get(col)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in reader:
            when = parse_datetime(get(row, "Activity Date"), _DATE)
            activity_id = get(row, "Activity ID")
            if when is None or not activity_id:
                stats["undated_skipped"] = stats.get("undated_skipped", 0) + 1
                continue
            name, kind = get(row, "Activity Name"), get(row, "Activity Type")
            description = get(row, "Activity Description")
            yield ActivityEvent(
                external_id=f"strava:{activity_id}",
                event_type="workout",
                occurred_at=when,
                payload={
                    "title": f"{name} ({kind})" if kind else name,
                    "name": name,
                    "type": kind or None,
                    "elapsed_s": _number(get(row, "Elapsed Time")),
                    "moving_s": _number(get(row, "Moving Time")),
                    "distance": _number(get(row, "Distance")),
                },
                # What the athlete wrote about the activity: their own words.
                text_content=description or None,
            )


def sniff(source: ImportSource) -> bool:
    try:
        return _member(source) is not None
    except Exception:
        return False


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    counts: dict[str, int] = {}
    total = described = 0
    first = last = None
    for ev in events(source, {}):
        total += 1
        described += bool(ev.text_content)
        kind = ev.payload.get("type") or "Other"
        counts[kind] = counts.get(kind, 0) + 1
        first = min(first, ev.occurred_at) if first else ev.occurred_at
        last = max(last, ev.occurred_at) if last else ev.occurred_at
    if not total:
        raise ExportUnreadable("No activities were found in this Strava export.")
    return ImportPreview(
        importer=NAME, label=LABEL,
        summary={
            "activities": total, "described": described,
            "by_type": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "first_at": first.isoformat() if first else None, "last_at": last.isoformat() if last else None,
        },
        options={},
        warnings=["Routes and GPS tracks in the export are not read."],
    )


class StravaExportImporter:
    name = NAME
    display_name = LABEL
    privacy_weight = "high"
    consent_disclosure = (
        "Reads activities.csv from the bulk export you downloaded from Strava: each "
        "activity's date, type, name, duration and distance, and your description of "
        "it. Routes and GPS tracks are never read. The file itself is not kept."
    )

    def accepts(self, filename: str) -> bool:
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return re.fullmatch(r"export_\d+\.zip", base) is not None

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(self, stream, *, tenant_id: str, options: dict[str, Any] | None = None,
              filename: str = "export.zip", stats: dict[str, int] | None = None) -> Iterator[ActivityEvent]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        yield from events(source, stats if stats is not None else {})


IMPORTER = StravaExportImporter()

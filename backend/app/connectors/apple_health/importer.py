"""Apple Health export (S-3.7.5, T-3.7.5.3). HealthKit has no web API; the
Health app's "Export All Health Data" writes ``export.zip`` holding
``apple_health_export/export.xml``, which runs to gigabytes after a few
years.

The XML is read with ``iterparse`` and every element is cleared once read, so
memory holds only per-day totals, never the records. Nothing raw is stored:
the import yields three ``daily_routine`` facts for ``personal_context``,
derived over the last ``window_days`` (default 365) of data and therefore
below 1.0 confidence:

- ``sleep`` — median hours asleep, typical bedtime and wake time, from
  ``HKCategoryTypeIdentifierSleepAnalysis`` "asleep" records. Watches write
  sleep as many short stage segments, so each source's segments are joined
  into sessions wherever the gap is under ``_SESSION_GAP``; a session with
  at least three hours asleep is a night (a nap is not), dated by waking;
- ``steps`` — median and mean daily steps;
- ``workouts`` — workouts per week by type.

An iPhone and a Watch both record steps and sleep, so totals are summed per
source and the larger source wins each day; adding them would double count.
Times of day are read in the offset each record carries, so a bedtime is the
local bedtime wherever the user was.
"""
from __future__ import annotations

import re
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from app.config import settings
from app.connectors.archive import ExportUnreadable, ImportPreview, ImportSource
from app.connectors.base import DerivedFact

NAME = "apple_health_export"
LABEL = "Apple Health routines"
CONFIDENCE = 0.8

_SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
_STEPS = "HKQuantityTypeIdentifierStepCount"
_ASLEEP = re.compile(r"Asleep", re.I)
_WORKOUT_PREFIX = re.compile(r"^HKWorkoutActivityType")
_SESSION_GAP = timedelta(minutes=90)
_NIGHT_MINUTES = 180


def _member(source: ImportSource) -> str | None:
    if not source.is_zip:
        return None
    for n in source.member_names():
        if n.replace("\\", "/").lower().endswith("export.xml") and "cda" not in n.lower():
            return n
    raise ExportUnreadable("No export.xml was found in this Apple Health archive.")


def _when(value: str | None) -> datetime | None:
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def _minutes_from_noon(t: datetime) -> int:
    """Minutes since local noon, so bedtimes either side of midnight sort."""
    return ((t.hour - 12) % 24) * 60 + t.minute


def _clock(minutes_from_noon: float) -> str:
    total = int(round(minutes_from_noon)) % (24 * 60)
    hour, minute = divmod(total, 60)
    return f"{(hour + 12) % 24:02d}:{minute:02d}"


class _Totals:
    def __init__(self) -> None:
        # source -> asleep segments (start, end)
        self.sleep: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        # day -> source -> steps
        self.steps: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        # (day, type, minutes)
        self.workouts: list[tuple[date, str, float]] = []
        self.latest: date | None = None
        self.earliest: date | None = None
        self.records = 0

    def seen(self, d: date) -> None:
        self.latest = max(self.latest, d) if self.latest else d
        self.earliest = min(self.earliest, d) if self.earliest else d


def _read(source: ImportSource, stats: dict[str, int]) -> _Totals:
    totals = _Totals()
    member = _member(source)
    with source.open_binary(member) as fh:
        try:
            for _event, elem in ET.iterparse(fh, events=("end",)):
                tag = elem.tag
                if tag == "Record":
                    totals.records += 1
                    kind = elem.get("type")
                    if kind == _SLEEP and _ASLEEP.search(elem.get("value") or ""):
                        start, end = _when(elem.get("startDate")), _when(elem.get("endDate"))
                        if start and end and end > start:
                            totals.sleep[elem.get("sourceName") or "?"].append((start, end))
                            totals.seen(end.date())
                    elif kind == _STEPS:
                        start = _when(elem.get("startDate"))
                        try:
                            value = float(elem.get("value") or 0)
                        except ValueError:
                            value = 0.0
                        if start:
                            totals.steps[start.date()][elem.get("sourceName") or "?"] += value
                            totals.seen(start.date())
                    elem.clear()
                elif tag == "Workout":
                    start = _when(elem.get("startDate"))
                    kind = _WORKOUT_PREFIX.sub("", elem.get("workoutActivityType") or "Other") or "Other"
                    try:
                        minutes = float(elem.get("duration") or 0)
                    except ValueError:
                        minutes = 0.0
                    if (elem.get("durationUnit") or "min") == "s":
                        minutes /= 60
                    if start:
                        totals.workouts.append((start.date(), kind, minutes))
                        totals.seen(start.date())
                    elem.clear()
                elif tag in ("ActivitySummary", "ClinicalRecord", "Correlation", "Me", "ExportDate"):
                    elem.clear()
        except ET.ParseError as e:
            raise ExportUnreadable(f"export.xml is damaged: {e}") from e
    stats["records_read"] = totals.records
    return totals


def nights(segments: list[tuple[datetime, datetime]]) -> list[tuple[float, datetime, datetime]]:
    """One source's segments joined into sessions; the sessions long enough
    to be a night, as (minutes asleep, onset, wake)."""
    out: list[tuple[float, datetime, datetime]] = []
    session: list | None = None
    for start, end in sorted(segments):
        if session is not None and start - session[2] <= _SESSION_GAP:
            # Overlapping stage records count once.
            session[0] += max(0.0, (end - max(start, session[2])).total_seconds() / 60)
            session[2] = max(session[2], end)
            continue
        if session is not None and session[0] >= _NIGHT_MINUTES:
            out.append(tuple(session))
        session = [(end - start).total_seconds() / 60, start, end]
    if session is not None and session[0] >= _NIGHT_MINUTES:
        out.append(tuple(session))
    return out


def facts(totals: _Totals, window_days: int) -> list[DerivedFact]:
    if totals.latest is None:
        return []
    since = totals.latest - timedelta(days=window_days)
    out: list[DerivedFact] = []

    # Each source's nights, keyed by the date of waking; the source that
    # recorded the most sleep that night wins (two devices are not two nights).
    by_wake: dict[date, tuple[float, datetime, datetime]] = {}
    for segments in totals.sleep.values():
        for night in nights(segments):
            key = night[2].date()
            if key >= since and (key not in by_wake or night[0] > by_wake[key][0]):
                by_wake[key] = night
    slept = list(by_wake.values())
    if slept:
        out.append(DerivedFact(
            kind="daily_routine", key="sleep", confidence=CONFIDENCE,
            value={
                "median_hours_asleep": round(statistics.median(m for m, _, _ in slept) / 60, 1),
                "typical_bedtime": _clock(statistics.median(_minutes_from_noon(o) for _, o, _ in slept)),
                "typical_wake_time": _clock(statistics.median(_minutes_from_noon(w) for _, _, w in slept)),
                "nights": len(slept),
                "window_days": window_days,
                "source": "Apple Health",
            },
        ))

    days = [max(by_source.values()) for day, by_source in totals.steps.items() if day >= since]
    if days:
        out.append(DerivedFact(
            kind="daily_routine", key="steps", confidence=CONFIDENCE,
            value={
                "median_daily_steps": int(statistics.median(days)),
                "mean_daily_steps": int(statistics.fmean(days)),
                "days": len(days),
                "window_days": window_days,
                "source": "Apple Health",
            },
        ))

    recent = [(d, k, m) for d, k, m in totals.workouts if d >= since]
    if recent:
        # Over the span the data covers, not the whole window: a month of
        # records is four weeks of evidence, not fifty-two.
        start = max(since, totals.earliest or since)
        weeks = max(1.0, ((totals.latest - start).days + 1) / 7)
        by_type: dict[str, list[float]] = defaultdict(list)
        for _, kind, minutes in recent:
            by_type[kind].append(minutes)
        out.append(DerivedFact(
            kind="daily_routine", key="workouts", confidence=CONFIDENCE,
            value={
                "per_week": round(len(recent) / weeks, 1),
                "by_type": {
                    k: {"per_week": round(len(v) / weeks, 2), "median_minutes": round(statistics.median(v))}
                    for k, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
                },
                "workouts": len(recent),
                "window_days": window_days,
                "source": "Apple Health",
            },
        ))
    return out


def _window(options: dict[str, Any]) -> int:
    try:
        return max(30, min(int(options.get("window_days") or 365), 3650))
    except (TypeError, ValueError):
        return 365


def sniff(source: ImportSource) -> bool:
    try:
        if source.is_zip:
            return any(n.replace("\\", "/").lower().endswith("apple_health_export/export.xml") for n in source.member_names())
        if not source.filename.lower().endswith(".xml"):
            return False
        return b"<HealthData" in source.head(65536)
    except Exception:
        return False


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    stats: dict[str, int] = {}
    totals = _read(source, stats)
    window = _window(options)
    found = facts(totals, window)
    if not found:
        raise ExportUnreadable("No sleep, step or workout records were found in this Apple Health export.")
    return ImportPreview(
        importer=NAME, label=LABEL,
        summary={
            "records_read": stats.get("records_read", 0),
            "facts": {f.key: f.value for f in found},
            "latest": totals.latest.isoformat() if totals.latest else None,
        },
        options={"window_days": window},
        warnings=["Only these summaries are stored, not the records themselves."],
    )


class AppleHealthImporter:
    name = NAME
    display_name = LABEL
    privacy_weight = "very_high"
    consent_disclosure = (
        "Reads the Apple Health export you made on your iPhone and keeps three "
        "summaries of your routine: how you sleep, how much you walk, and how often "
        "you work out. The health records themselves are not stored."
    )

    def accepts(self, filename: str) -> bool:
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return base in ("export.zip", "export.xml")

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(self, stream, *, tenant_id: str, options: dict[str, Any] | None = None,
              filename: str = "export.zip", stats: dict[str, int] | None = None) -> Iterator[DerivedFact]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        opts = dict(options or {})
        yield from facts(_read(source, stats if stats is not None else {}), _window(opts))


IMPORTER = AppleHealthImporter()

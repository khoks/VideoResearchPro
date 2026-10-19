"""Measure how evenly the report map stage covers a job's sources under a batching config. Research tool.

R1 run 6 found the map model (gpt-5.6-luna, reasoning off) writes roughly
100 to 140 items per call whatever the batch holds: 0.23 to 0.37 items per
chunk in a 400-chunk batch, 1.4 to 1.6 in a 27-chunk one. So a source's share
of the report depended on which batch it landed in, and sources late in a
large batch could get nothing at all. Mixed batches also let one video's
on-screen span or script leak into another video's items.

This script re-runs ONLY the map stage over a replayed job's chunks under a
given `REPORT_MAP_BATCHING` / `REPORT_MAP_BATCH_TOKENS` (S-1.14.19) and
reports per-source coverage plus two contamination measures:
``cross_source_labels`` (a `shown`/`both` item whose OWN source has no visual
span within its moment +-60 s) and ``wrong_script_originals`` (kept quotes
the pipeline had to drop as script mismatches). One config per process.

Usage (from backend/, inside the venv):
    python scripts/measure_map_coverage.py --job-id <id> --arm on --cap 30000 --batching source \\
        --descriptions data/r1_ab/retier/baseline_describe.json --out data/map_coverage
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_VIDEO_ID = re.compile(r"(?:[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})")
_SPAN = re.compile(r"\[VISUAL @ (\d+):(\d{2})(?::(\d{2}))?")
_TS = re.compile(r"(\d+):(\d{2})(?::(\d{2}))?")
SPAN_WINDOW = 60.0

# Sources this small can legitimately yield nothing; the zero-item count
# ignores them so a two-chunk outro never reads as a coverage failure.
MIN_CHUNKS_FOR_ZERO_CHECK = 10


def source_key(item_or_meta: dict) -> str:
    for k in ("video_url", "url", "permalink"):
        m = _VIDEO_ID.search(str(item_or_meta.get(k) or ""))
        if m:
            return m.group(1)
    return str(item_or_meta.get("video_id") or item_or_meta.get("video_title") or "?")


def _iter_items(summaries: list):
    for s in summaries:
        if not isinstance(s, dict):
            continue
        for items in s.values():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        yield it


def items_by_source(summaries: list) -> Counter:
    return Counter(source_key(it) for it in _iter_items(summaries))


def _seconds(m: re.Match) -> float:
    a, b, c = m.group(1), m.group(2), m.group(3)
    return float(int(a) * 3600 + int(b) * 60 + int(c)) if c else float(int(a) * 60 + int(b))


def span_index(chunks: list[dict]) -> dict[str, list[float]]:
    """Seconds of every `[VISUAL @ ...]` span, per source."""
    out: dict[str, list[float]] = {}
    for c in chunks:
        key = source_key(c.get("metadata") or {})
        for m in _SPAN.finditer(c.get("text") or ""):
            out.setdefault(key, []).append(_seconds(m))
    return out


def item_window(item: dict) -> tuple[float, float]:
    """The item's moment: its start, and the end of an `a-b` display range, widened by SPAN_WINDOW."""
    times = [_seconds(m) for m in _TS.finditer(str(item.get("timestamp_display") or ""))]
    try:
        start = float(item.get("timestamp_seconds"))
    except (TypeError, ValueError):
        start = times[0] if times else 0.0
    end = max(times) if len(times) > 1 else start
    return start - SPAN_WINDOW, max(end, start) + SPAN_WINDOW


def cross_source_labels(summaries: list, spans: dict[str, list[float]]) -> int:
    """`shown`/`both` items whose own source shows nothing near their moment."""
    n = 0
    for it in _iter_items(summaries):
        if it.get("modality") in ("shown", "both"):
            lo, hi = item_window(it)
            if not any(lo <= t <= hi for t in spans.get(source_key(it), [])):
                n += 1
    return n


def coverage(chunk_counts: Counter, item_counts: Counter) -> dict:
    """Per-source density and the summary figures the decision rule uses."""
    density = {s: item_counts.get(s, 0) / n for s, n in chunk_counts.items() if n}
    eligible = [s for s, n in chunk_counts.items() if n >= MIN_CHUNKS_FOR_ZERO_CHECK]
    zero = sorted(s for s in eligible if item_counts.get(s, 0) == 0)
    vals = [density[s] for s in eligible] or [0.0]
    med = statistics.median(vals)
    return {
        "sources": len(chunk_counts),
        "zero_item_sources": zero,
        "items_total": sum(item_counts.values()),
        "unattributed_items": sum(c for s, c in item_counts.items() if s not in chunk_counts),
        "density_min": round(min(vals), 3),
        "density_median": round(med, 3),
        "floor_ratio": round(min(vals) / med, 3) if med else 0.0,
        "density_cv": round(statistics.pstdev(vals) / statistics.mean(vals), 3) if statistics.mean(vals) else 0.0,
        "per_source": {s: {"chunks": chunk_counts[s], "items": item_counts.get(s, 0),
                           "density": round(density.get(s, 0.0), 3)} for s in sorted(chunk_counts)},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--job-id", required=True)
    p.add_argument("--arm", choices=["on", "off"], required=True)
    p.add_argument("--cap", type=int, required=True, help="REPORT_MAP_BATCH_TOKENS")
    p.add_argument("--batching", choices=["packed", "source"], default="packed")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--descriptions", default=None)
    p.add_argument("--topic", default=None)
    p.add_argument("--tag", default="", help="suffix for the output file, e.g. a repeat number")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    # First: importing the replay module lets backend/.env win over stale
    # OS-level API keys before any app module builds its settings.
    import replay_visual_ab as rv
    from app.agents import report_agent as ra
    from app.config import settings
    from app.database import SessionLocal
    from app.models.job import Job

    settings.REPORT_MAP_BATCH_TOKENS = args.cap
    settings.REPORT_MAP_BATCHING = args.batching
    settings.REPORT_MAP_CONCURRENCY = args.concurrency
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == args.job_id).first()
        descriptions = rv.load_descriptions(args.descriptions) if args.descriptions else None
        _manifest, chunks_on, chunks_off, _blocks = rv.build_arms(db, args.job_id, descriptions)
    finally:
        db.close()
    chunks = chunks_on if args.arm == "on" else chunks_off
    topic = args.topic or (job.topic if job else "")

    t0 = time.time()
    result = ra.map_chunks({"job_type": "topic", "transcript_chunks": chunks, "topic": topic})
    secs = round(time.time() - t0, 1)

    summaries = result.get("chunk_summaries") or []
    chunk_counts = Counter(source_key(c.get("metadata") or {}) for c in chunks)
    notes = result.get("processing_notes") or {}
    out = {
        "job_id": args.job_id, "arm": args.arm, "cap": args.cap, "batching": args.batching,
        "concurrency": args.concurrency, "seconds": secs,
        "batches": notes.get("map_batches"), "batches_failed": notes.get("map_batches_failed"),
        "chunks_dropped": notes.get("map_chunks_dropped"), "chunks": len(chunks),
        "originals_kept": notes.get("map_originals_kept"),
        "originals_dropped": notes.get("map_originals_dropped"),
        "wrong_script_originals": (notes.get("map_originals_dropped_by_reason") or {}).get("script_mismatch", 0),
        "cross_source_labels": cross_source_labels(summaries, span_index(chunks)),
        "modality": notes.get("map_modality"),
        **coverage(chunk_counts, items_by_source(summaries)),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    name = f"{args.arm}_{args.batching}{args.cap}{('_' + args.tag) if args.tag else ''}.json"
    (args.out / name).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{args.arm} {args.batching}@{args.cap}: batches={out['batches']} failed={out['batches_failed']} "
          f"items={out['items_total']} zero={out['zero_item_sources']} floor_ratio={out['floor_ratio']} "
          f"cv={out['density_cv']} cross_source={out['cross_source_labels']} "
          f"wrong_script={out['wrong_script_originals']} {secs}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

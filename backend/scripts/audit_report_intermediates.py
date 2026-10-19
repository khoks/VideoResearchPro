"""Audit a job's persisted report intermediates (S-1.14.6).

Reads `job_report_intermediates` and answers the questions the pipeline
could not answer before: what did each map batch extract, which batches
failed or came back unparseable, what did reduce hand to compose, and did
anything go missing between the two.

    ./venv/Scripts/python scripts/audit_report_intermediates.py --job 0d4db8c3
    ./venv/Scripts/python scripts/audit_report_intermediates.py --job 0d4db8c3 --run 1a2b --batches

Read-only. With no `--run`, the job's most recent run is audited and every
run is listed.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_KEYS = ("facts", "comments", "conclusions", "references", "speakers")


def _items(payload: str | None) -> list[tuple[str, dict]]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, dict]] = []
    for key in _KEYS:
        for item in data.get(key) or []:
            out.append((key, item if isinstance(item, dict) else {"content": str(item)}))
    return out


def audit(db, job_id_prefix: str, run_prefix: str | None, show_batches: bool) -> int:
    from app.models.job import Job
    from app.models.job_report_intermediate import (
        MAP_FAILED,
        MAP_UNPARSED,
        STAGE_MAP,
        STAGE_REDUCE,
        JobReportIntermediate,
    )

    job = db.query(Job).filter(Job.id.like(f"{job_id_prefix}%")).first()
    if job is None:
        print(f"no job matching {job_id_prefix!r}")
        return 2
    rows = (
        db.query(JobReportIntermediate)
        .filter(JobReportIntermediate.job_id == job.id)
        .order_by(JobReportIntermediate.created_at)
        .all()
    )
    if not rows:
        print(f"job {job.id}: no persisted intermediates")
        return 1

    runs: dict[str, list] = {}
    for r in rows:
        runs.setdefault(r.run_id, []).append(r)
    print(f"job {job.id} ({job.topic or job.job_type}): {len(runs)} run(s)")
    for rid, rs in runs.items():
        print(f"  run {rid[:8]}  {rs[0].created_at:%Y-%m-%d %H:%M}  {len(rs)} row(s)")

    if run_prefix:
        chosen = [rid for rid in runs if rid.startswith(run_prefix)]
        if not chosen:
            print(f"no run matching {run_prefix!r}")
            return 2
        run_id = chosen[0]
    else:
        run_id = list(runs)[-1]
    rs = runs[run_id]
    maps = sorted(
        (r for r in rs if r.stage == STAGE_MAP),
        key=lambda r: (r.batch_index, -1 if r.sub_index is None else r.sub_index),
    )
    reduce_rows = [r for r in rs if r.stage == STAGE_REDUCE]

    print(f"\nrun {run_id}")
    status = Counter(r.status for r in maps)
    print(f"  map: {len(maps)} call(s) — " + ", ".join(f"{k} {v}" for k, v in status.items()))
    print(f"  map items: {sum(r.item_count for r in maps):,}; "
          f"chunks covered: {sum(r.chunk_count or 0 for r in maps):,}; "
          f"chunks dropped: {sum(r.chunk_count or 0 for r in maps if r.status == MAP_FAILED):,}")

    map_items = [it for r in maps for it in _items(r.payload_json)]
    by_key = Counter(k for k, _ in map_items)
    print("  map items by category: " + ", ".join(f"{k} {by_key.get(k, 0)}" for k in _KEYS))
    modality = Counter(str(it.get("modality", "—")) for _, it in map_items)
    if set(modality) - {"—"}:
        print("  map items by modality: " + ", ".join(f"{k} {v}" for k, v in modality.most_common()))

    for r in maps:
        if r.status in (MAP_FAILED, MAP_UNPARSED):
            note = json.loads(r.notes_json or "{}")
            tag = f"{r.batch_index}" + ("" if r.sub_index is None else f".{r.sub_index}")
            print(f"  ! batch {tag} {r.status}: {note.get('error', '')[:160]} "
                  f"({r.chunk_count} chunks; {', '.join(note.get('videos', [])[:3])})")

    if reduce_rows:
        red = reduce_rows[0]
        notes = json.loads(red.notes_json or "{}")
        print(f"\n  reduce: {red.status}, {red.item_count:,} items out")
        items_in = notes.get("reduce_items_in")
        if items_in is not None:
            collapsed = notes.get("reduce_exact_duplicates_collapsed", 0)
            trimmed = notes.get("reduce_items_trimmed", 0)
            print(f"  reduce accounting: {items_in:,} in − {collapsed:,} exact duplicates "
                  f"− {trimmed:,} trimmed = {items_in - collapsed - trimmed:,} "
                  f"({'matches' if items_in - collapsed - trimmed == red.item_count else 'DOES NOT match'} "
                  f"the {red.item_count:,} items out)")
        videos = {str(it.get("video_url") or it.get("video_title") or "") for _, it in _items(red.payload_json)}
        print(f"  reduce covers {len(videos - {''}):,} distinct videos")
    else:
        print("\n  reduce: no record (channel job, or the run stopped before reduce)")

    if show_batches:
        print("\n  per-batch:")
        for r in maps:
            tag = f"{r.batch_index}" + ("" if r.sub_index is None else f".{r.sub_index}")
            vids = json.loads(r.notes_json or "{}").get("videos", [])
            print(f"    {tag:>6} {r.status:9} chunks={r.chunk_count or 0:>4} items={r.item_count:>5} "
                  f"videos={len(vids):>3} model={r.model}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True, help="job id (prefix accepted)")
    ap.add_argument("--run", help="run id prefix; default the job's latest run")
    ap.add_argument("--batches", action="store_true", help="print one line per map call")
    args = ap.parse_args()

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return audit(db, args.job, args.run, args.batches)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

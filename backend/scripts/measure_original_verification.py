"""How many kept `original` quotes survive the verbatim check? (N-002 fix)

Two measurements on a job, both through the production code:

1. OFFLINE (free): run `_verify_originals` over map output already on disk
   (an `*.intermediates.json` written by `replay_visual_ab.py`), against the
   job's own chunks — what the check would have removed from that run.
2. LIVE (``--replay``): run the production map stage on the job's chunks
   (no frames) and count what the check keeps and drops.

Both report originals per channel and per script, kept and dropped.

    python scripts/measure_original_verification.py --job-id 419e691d-... \\
        --intermediates ../data/r1_ab/run5/off.intermediates.json \\
        --intermediates ../data/r1_ab/run5/on.intermediates.json --replay
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import dotenv_values  # noqa: E402

for _k, _v in dotenv_values(BACKEND / ".env").items():
    if _k.endswith("_API_KEY") and _v:
        os.environ[_k] = _v

from app.agents import report_agent  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services import language_service  # noqa: E402

sys.path.insert(0, str(BACKEND / "scripts"))
from replay_visual_ab import build_arms  # noqa: E402

_KEYS = report_agent._REDUCE_KEYS


def _tally(summaries: list[dict]) -> dict:
    kept, dropped, reasons = Counter(), Counter(), Counter()
    examples = []
    for s in summaries:
        if not isinstance(s, dict):
            continue
        for k in _KEYS:
            for it in s.get(k) or []:
                if not isinstance(it, dict):
                    continue
                ch = it.get("channel_name") or "?"
                if it.get("original"):
                    kept[(ch, language_service.dominant_script(it["original"]) or "?")] += 1
                if it.get("original_rejected"):
                    rej = it["original_rejected"]
                    dropped[(ch, language_service.dominant_script(rej) or "?")] += 1
                    reasons[it.get("original_rejected_reason") or "?"] += 1
                    if len(examples) < 6:
                        examples.append(f"{ch}: {rej[:80]}")
    return {
        "kept": sum(kept.values()), "dropped": sum(dropped.values()),
        "kept_by_channel_script": {f"{c} / {s}": n for (c, s), n in sorted(kept.items())},
        "dropped_by_channel_script": {f"{c} / {s}": n for (c, s), n in sorted(dropped.items())},
        "dropped_by_reason": dict(sorted(reasons.items())),
        "dropped_examples": examples,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--intermediates", action="append", default=[])
    ap.add_argument("--replay", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        _, _, chunks_off, _ = build_arms(db, args.job_id)
    finally:
        db.close()
    sources = report_agent._source_texts_for_verification(chunks_off)
    report = {"job_id": args.job_id, "chunks": len(chunks_off), "sources": len(sources["videos"])}

    for path in args.intermediates:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        summaries = [json.loads(r["payload_json"]) for r in data["map"] if r.get("payload_json")]
        counts: dict = {"kept": 0, "dropped": 0}
        for s in summaries:
            report_agent._verify_originals(s, sources, counts)
        report[f"offline:{Path(path).name}"] = _tally(summaries)

    if args.replay:
        out = report_agent.map_chunks({"job_type": "topic", "transcript_chunks": chunks_off, "topic": "replay"})
        report["replay_off"] = _tally(out["chunk_summaries"])
        report["replay_off"]["notes"] = {
            k: v for k, v in out["processing_notes"].items() if k.startswith("map_originals")
        }
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""Calibrate the saved-search change thresholds (S-8.3.3).

Implements the protocol pre-registered in
``docs/notes/2026-10-19-saved-search-change-thresholds.md`` (merged as #323
before this script existed). It reads a database, never writes it, and
prints and saves aggregates only: no question or answer text leaves the
database, because the repository is public.

    cd backend
    ./venv/Scripts/python scripts/calibrate_saved_search_thresholds.py \\
        --db sqlite:///path/to/COPY-of-videoresearchpro.db \\
        --out ../docs/notes/2026-10-19-saved-search-change-thresholds-results.json

Run it on a copy of the dev database.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

MIN_PAIRS = 20
PRIOR_J = 0.50
PRIOR_D = 0.15
NEGATIVE_SEED = 833
SANITY_SHARE = 0.80


def normalise(q: str) -> str:
    q = " ".join((q or "").casefold().split())
    return re.sub(r"[?!.\s]+$", "", q)


def ref_keys(raw: str | None) -> frozenset[str]:
    try:
        refs = json.loads(raw or "[]")
    except ValueError:
        return frozenset()
    keys = set()
    for r in refs if isinstance(refs, list) else []:
        if isinstance(r, dict):
            key = r.get("video_id") or r.get("document_id")
            if key:
                keys.add(str(key))
    return frozenset(keys)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def cosine_distance(u: list[float], v: list[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    return 1.0 - (dot / (nu * nv) if nu and nv else 0.0)


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in 0..100)."""
    xs = sorted(values)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _dt(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def load_exchanges(conn) -> list[dict]:
    rows = []
    for r in conn.execute(text(
        "SELECT id, tenant_id, question, answer, references_json AS refs, created_at FROM library_qa_exchanges"
    )).mappings():
        rows.append({**r, "surface": "library", "context": "library"})
    for r in conn.execute(text(
        "SELECT id, tenant_id, question, answer, \"references\" AS refs, created_at, job_id FROM qa_exchanges"
    )).mappings():
        rows.append({**r, "surface": "job", "context": f"job:{r['job_id']}"})
    for r in rows:
        r["created_at"] = _dt(r["created_at"])
        r["norm"] = normalise(r["question"])
    return [r for r in rows if r["tenant_id"] and r["norm"]]


def visibility_times(conn) -> dict[str, list[datetime]]:
    out: dict[str, list[datetime]] = defaultdict(list)
    for r in conn.execute(text("SELECT tenant_id, created_at FROM document_visibility")).mappings():
        out[r["tenant_id"]].append(_dt(r["created_at"]))
    return out


def build_pairs(exchanges: list[dict], vis: dict[str, list[datetime]]) -> tuple[list, list]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in exchanges:
        groups[(e["tenant_id"], e["context"], e["norm"])].append(e)
    by_context: dict[tuple, list[dict]] = defaultdict(list)
    for e in exchanges:
        by_context[(e["tenant_id"], e["context"])].append(e)

    unchanged: list[tuple[dict, dict]] = []
    for (tenant, context, _norm), items in groups.items():
        items.sort(key=lambda e: e["created_at"])
        for a, b in zip(items, items[1:]):
            if context == "library":
                if any(a["created_at"] < t <= b["created_at"] for t in vis.get(tenant, [])):
                    continue
            unchanged.append((a, b))

    rng = random.Random(NEGATIVE_SEED)
    negatives: list[tuple[dict, dict]] = []
    for a, _b in unchanged:
        pool = [e for e in by_context[(a["tenant_id"], a["context"])] if e["norm"] != a["norm"]]
        if pool:
            negatives.append((a, rng.choice(pool)))
    return unchanged, negatives


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, help="SQLAlchemy URL of a COPY of the dev database")
    ap.add_argument("--out", help="write the aggregates as JSON here")
    args = ap.parse_args()

    engine = create_engine(args.db)
    with engine.connect() as conn:
        exchanges = load_exchanges(conn)
        vis = visibility_times(conn)
    unchanged, negatives = build_pairs(exchanges, vis)

    result: dict = {
        "protocol": "docs/notes/2026-10-19-saved-search-change-thresholds.md",
        "exchanges": len(exchanges),
        "pairs_unchanged": len(unchanged),
        "pairs_unchanged_library": sum(1 for a, _ in unchanged if a["surface"] == "library"),
        "pairs_unchanged_job": sum(1 for a, _ in unchanged if a["surface"] == "job"),
        "pairs_negative": len(negatives),
    }

    if len(unchanged) < MIN_PAIRS:
        result.update({
            "decision": "calibration pending: fewer than 20 re-ask pairs; priors apply",
            "jaccard_threshold": PRIOR_J,
            "embedding_threshold": PRIOR_D,
        })
    else:
        from app.services import embedding_service

        texts: list[str] = []
        index: dict[str, int] = {}
        for a, b in unchanged + negatives:
            for e in (a, b):
                if e["id"] not in index:
                    index[e["id"]] = len(texts)
                    texts.append(e["answer"] or "")
        vectors = embedding_service.encode(texts)

        def d(a, b):
            return cosine_distance(vectors[index[a["id"]]], vectors[index[b["id"]]])

        d_u = [d(a, b) for a, b in unchanged]
        j_u = [jaccard(ref_keys(a["refs"]), ref_keys(b["refs"])) for a, b in unchanged]
        d_n = [d(a, b) for a, b in negatives]

        d_threshold = math.ceil(percentile(d_u, 95) * 100) / 100
        j5 = percentile(j_u, 5)
        j_threshold = 0.95 if j5 >= 1.0 else math.floor(j5 * 20) / 20

        trips_d = [x > d_threshold for x in d_u]
        trips_j = [x < j_threshold for x in j_u]
        separated = sum(1 for x in d_n if x > d_threshold) / len(d_n) if d_n else float("nan")
        result.update({
            "embedding_distance_unchanged": {
                "p50": round(percentile(d_u, 50), 4),
                "p95": round(percentile(d_u, 95), 4),
                "max": round(max(d_u), 4),
            },
            "embedding_distance_negative": {
                "p5": round(percentile(d_n, 5), 4) if d_n else None,
                "p50": round(percentile(d_n, 50), 4) if d_n else None,
            },
            "jaccard_unchanged": {
                "p5": round(j5, 4),
                "p50": round(percentile(j_u, 50), 4),
                "share_equal_sets": round(sum(1 for x in j_u if x == 1.0) / len(j_u), 4),
            },
            "embedding_threshold": d_threshold,
            "jaccard_threshold": j_threshold,
            "negative_separated_share": round(separated, 4) if d_n else None,
            "sanity_passed": (separated >= SANITY_SHARE) if d_n else None,
            "disagreement_rate_unchanged": round(sum(1 for a, b in zip(trips_d, trips_j) if a != b) / len(d_u), 4),
            "both_trip_rate_unchanged": round(sum(1 for a, b in zip(trips_d, trips_j) if a and b) / len(d_u), 4),
            "decision": "calibrated by the pre-registered rule",
        })

    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

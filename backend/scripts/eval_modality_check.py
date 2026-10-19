"""Score app.services.modality_check against the R1 runs' verified labels (S-1.18.7).

Ground truth is what the 87–117-agent adversarial verifications concluded for
runs 1–3 (backend/data/r1_ab/run*/judging/verification.json): sweep candidates
and judge claims of the attribution kind, each confirmed or refuted by a
majority of three independent verifiers. Evidence per run is the speech from
transcript_cache plus the frame descriptions THAT run merged (run 1 used the
stored descriptions, run 2 Gemini Flash-Lite's, run 3 a gpt-5.5 re-description).

Prints recall on confirmed errors, which refuted candidates were (wrongly)
flagged, and every flag that matches no label, for hand adjudication.

Usage (from backend/, inside the venv):
    python scripts/eval_modality_check.py [--explicit 20 --link-after 120 --speech 90]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modality_check import Evidence, Windows, check_report, normalise  # noqa: E402

JOB = "419e691d-6370-4042-a22f-7169490ff736"
RUNS = {
    "run1": {"html": "data/r1_ab/run1/on.html", "descriptions": None},
    "run2": {"html": "data/r1_ab/run2/on.html", "descriptions": "data/r1_ab/retier/gemini_flash_lite.json"},
    "run3": {"html": "data/r1_ab/run3/on.html", "descriptions": "data/r1_ab/retier/baseline_describe.json"},
}


def load_evidence(db: sqlite3.Connection, descriptions_path: str | None) -> dict[str, Evidence]:
    vids = [r[0] for r in db.execute("select video_id from job_documents where job_id=? and video_id is not null", (JOB,))]
    subst = None
    if descriptions_path:
        data = json.loads((BACKEND / descriptions_path).read_text(encoding="utf-8"))
        subst = {r["frame_id"]: r for r in data["describe"] if r.get("description")}
    ev: dict[str, Evidence] = {}
    for v in vids:
        row = db.execute("select segments_json from transcript_cache where video_id=?", (v,)).fetchone()
        if not row:
            continue
        segs = json.loads(row[0])
        e = Evidence(speech=[(float(s.get("start", 0) or 0), s.get("text") or "") for s in segs])
        for fid, ts, desc, inf, status in db.execute(
            "select frame_id, timestamp_seconds, description, informative, status from visual_frames where video_id=?", (v,)
        ):
            if subst is not None:
                r = subst.get(fid)
                if not r or not r.get("informative"):
                    continue
                e.visual.append((float(ts), r["description"]))
            elif desc and inf and status not in ("failed", "skipped"):
                e.visual.append((float(ts), desc))
        e.visual.sort()
        ev[v] = e
    return ev


def load_aliases(db: sqlite3.Connection) -> dict[str, str]:
    """Lower-cased channel names and titles -> video id, for prose mentions."""
    out: dict[str, str] = {}
    rows = db.execute(
        "select d.video_id, d.title, c.name from documents d left join channels c on c.channel_id = d.channel_id "
        "where d.video_id in (select video_id from job_documents where job_id=?)", (JOB,)
    ).fetchall()
    names: dict[str, set[str]] = {}
    for vid, title, channel in rows:
        if title:
            out[title.lower()] = vid
        if channel:
            names.setdefault(channel.lower(), set()).add(vid)
    for name, vids in names.items():
        if len(vids) == 1:              # a channel with several videos is ambiguous
            out[name] = next(iter(vids))
    return out


def labels(run: str) -> list[tuple[str, bool]]:
    """(sentence, confirmed) for every attribution-kind item the verification ruled on."""
    p = BACKEND / f"data/r1_ab/{run}/judging/verification.json"
    v = json.loads(p.read_text(encoding="utf-8"))
    out = [(s["sentence"], bool(s["confirmed"])) for s in v.get("sweep", [])]
    out += [(c["claim"], bool(c["confirmed"])) for c in v.get("claims", []) if c["kind"] == "attribution_errors" and c["arm"] == "on"]
    return out


def _key(s: str) -> str:
    s = normalise(s).strip("\"'“” ")
    return s[:55]


def match(sentence: str, labelled: list[tuple[str, bool]]) -> tuple[str, bool] | None:
    k = _key(sentence)
    for text, ok in labelled:
        lk = _key(text)
        if lk and (lk[:40] in normalise(sentence) or k[:40] in normalise(text)):
            return text, ok
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--explicit", type=float, default=20.0)
    ap.add_argument("--link-before", type=float, default=20.0)
    ap.add_argument("--link-after", type=float, default=120.0)
    ap.add_argument("--speech", type=float, default=90.0)
    ap.add_argument("--speaker-weak", type=int, default=1)
    ap.add_argument("--trailing-weak", type=int, default=2)
    ap.add_argument("--trailing-strong", type=int, default=1)
    ap.add_argument("--quiet", action="store_true", help="summary line only")
    args = ap.parse_args()
    w = Windows(explicit=args.explicit, link_before=args.link_before, link_after=args.link_after, speech=args.speech,
                speaker_weak=args.speaker_weak, trailing_weak=args.trailing_weak, trailing_strong=args.trailing_strong)

    db = sqlite3.connect(str(BACKEND / "data/videoresearchpro.db"))
    aliases = load_aliases(db)
    tot = {"confirmed": 0, "caught": 0, "refuted": 0, "refuted_flagged": 0, "unlabelled_flags": 0, "flags": 0}
    for run, cfg in RUNS.items():
        ev = load_evidence(db, cfg["descriptions"])
        html = (BACKEND / cfg["html"]).read_text(encoding="utf-8")
        found = check_report(html, ev, w, aliases)
        lab = labels(run)
        confirmed = [t for t, ok in lab if ok]
        refuted = [t for t, ok in lab if not ok]
        caught = [t for t in confirmed if any(match(f.sentence, [(t, True)]) for f in found)]
        refuted_flagged = [t for t in refuted if any(match(f.sentence, [(t, False)]) for f in found)]
        unlabelled = [f for f in found if match(f.sentence, lab) is None]
        tot["confirmed"] += len(confirmed); tot["caught"] += len(caught)
        tot["refuted"] += len(refuted); tot["refuted_flagged"] += len(refuted_flagged)
        tot["unlabelled_flags"] += len(unlabelled); tot["flags"] += len(found)
        if args.quiet:
            continue
        print(f"\n===== {run}: {len(found)} flags | confirmed {len(caught)}/{len(confirmed)} caught | refuted flagged {len(refuted_flagged)}/{len(refuted)} | unlabelled flags {len(unlabelled)}")
        for t in confirmed:
            print(f"  [{'CAUGHT' if t in caught else 'MISSED'}] {t[:150]}")
        for t in refuted_flagged:
            print(f"  [FALSE+ on refuted] {t[:150]}")
        for f in unlabelled:
            print(f"  [unlabelled {f.kind} @ {f.video_id} {f.seconds:.0f}s tokens={f.tokens[:4]}] {f.sentence[:170]}")
    print(f"\nTOTAL windows={w}: recall {tot['caught']}/{tot['confirmed']}, refuted flagged {tot['refuted_flagged']}/{tot['refuted']}, "
          f"unlabelled flags {tot['unlabelled_flags']}, all flags {tot['flags']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

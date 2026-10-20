"""Blind pairwise judging of Q&A answers, with 3-lens claim verification —
the Q&A sibling of `judge_pair.py` (E-1.14 / D-055 method), first used for
T-7.1.1.5 (trust weights on vs off, D-068).

Input: the per-answer JSON files `measure_trust_weighting.py` writes
(`q{NN}_{surface}_{arm}.json`, each with the answer and the chunks it was
built from). For every (question, surface) pair:

1. **Judge.** Each judge (one per model family) gets the question, both
   answers under an independently coin-flipped A/B mapping, and the pooled,
   shuffled, unlabelled excerpts both answers drew on. Scores relevance and
   faithfulness 1-10, lists unsupported claims, states a preference.
2. **Verify.** Every unsupported claim any judge lists is checked by three
   verifier lenses (one per family) against the excerpts THAT answer was
   built from (plus the report, for job Q&A, which reads it). Confirmed on a
   2-of-3 majority. Judges alone are not evidence of absence or presence —
   the R1 run showed three judges missing what a sweep found.
3. **Summarise** M1 (promoted/demoted share of retrieved chunks and cited
   references), M2 (ON chunks over the raw threshold), R and V, per the
   pre-registered rule in docs/notes/2026-10-19-e71-trust-weighting-measurement.md.

Usage (from backend/, main venv):
    python scripts/judge_qa_pairs.py --runs <dir> --out <dir> --report <report.html>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from dotenv import dotenv_values  # noqa: E402

_MAIN_ENV = Path(os.environ.get("PRATIDHVANI_ENV_FILE", BACKEND / ".env"))

JUDGES = "openai:gpt-5.5:medium,anthropic:claude-sonnet-5:medium,google:gemini-3.1-pro-preview:medium"
VERIFIERS = "openai:gpt-5.5:low,anthropic:claude-sonnet-5:low,google:gemini-3.1-pro-preview:low"

JUDGE_RUBRIC = """You are one of several independent judges comparing two answers, labelled A and B, to the same research question. Both were written by an assistant that could only use the excerpts below (transcript passages from a library of videos). You do not know how either answer was produced and must not guess. Judge the text against the question and the excerpts; do not reward length.

Score each answer 1-10 on:
1. relevance — how directly and completely it answers the question that was asked. Material that is accurate but beside the question lowers this score.
2. faithfulness — whether every substantive claim is supported by the excerpts. Paraphrase is fine; facts, numbers, names or attributions found in no excerpt are not.

Then list, for each answer, unsupported_claims: each sentence (quoted exactly) that makes a claim no excerpt supports. Empty list if none.

Finally state preferred: "A", "B" or "tie" — which answer a researcher asking this question would rather receive, weighing relevance first and faithfulness second.

Return ONLY a JSON object with keys: relevance_A, relevance_B, faithfulness_A, faithfulness_B, unsupported_claims_A (list of strings), unsupported_claims_B (list of strings), preferred, rationale (<= 100 words).
"""

VERIFY_PROMPT = """You are verifying ONE claim taken from an answer written by a research assistant. The answer was built only from the excerpts below{report_clause}. Decide whether that material supports the claim.

A claim is SUPPORTED if the material states it or it follows directly from it; paraphrase, summarising and reasonable generalisation from several excerpts are fine. It is UNSUPPORTED if it adds facts, numbers, names, tools or attributions (who said what) that the material does not contain, or contradicts it.

CLAIM:
{claim}

Return ONLY a JSON object: {{"supported": true or false, "evidence": "<excerpt label or a short quote, empty if none>", "reason": "<= 40 words"}}.

===== EXCERPTS =====
{excerpts}{report}
"""


def _load_keys() -> None:
    for key, value in (dotenv_values(_MAIN_ENV) or {}).items():
        if value is not None and (key.endswith("_API_KEY") or key.startswith("LLM_")):
            os.environ[key] = value


def _llm(spec: str, max_tokens: int):
    from app.services.llm_routing import UseCaseConfig
    from app.services.llm_service import _build_from_config

    provider, model, reasoning = (spec.split(":") + ["medium"])[:3]
    return _build_from_config(UseCaseConfig(provider, model, reasoning), temperature=1.0, max_tokens=max_tokens)


def _invoke(spec: str, prompt: str, max_tokens: int, retries: int = 2) -> str:
    from app.services.llm_service import response_text

    last = None
    for attempt in range(retries + 1):
        try:
            return response_text(_llm(spec, max_tokens).invoke(prompt))
        except Exception as e:  # transient provider errors: retry, then give up on this call only
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{spec}: {type(last).__name__}: {last}")


def _json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in output")
    return json.loads(raw[start:end + 1])


def _chunk_key(c: dict) -> tuple:
    return (c.get("document_id"), c.get("chunk_index"), c.get("timestamp_start"))


_VINTAGE: dict[str, str] = {}


def _load_vintage(db_path: str) -> None:
    """`--dates-db`: each document's `published <date> | discusses <era>`, as
    the answer prompt renders it (qa_agent._vintage_parts), for run files
    recorded before chunk records carried it. Without this, every date an
    answer took from source metadata reads as unsupported to the judges."""
    import sqlite3

    from app.services import temporal_service

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    for doc_id, published_at, era_raw in con.execute(
            "SELECT document_id, published_at, discussed_era_json FROM documents"):
        parts = []
        pub = temporal_service.published_display(published_at)
        if pub:
            parts.append(f"published {pub}")
        era = temporal_service.era_for_prompt(temporal_service.load_era(temporal_service._EraRow(era_raw)))
        if era:
            parts.append(era)
        if parts:
            _VINTAGE[doc_id] = " | ".join(parts)
    con.close()


def _render(chunks: list[dict], labels: dict[tuple, str]) -> str:
    parts = []
    for c in chunks:
        head = f"[{labels[_chunk_key(c)]}] \"{c.get('title', '')}\" by {c.get('channel_name') or 'unknown'}"
        vintage = c.get("vintage") or _VINTAGE.get(c.get("document_id") or "", "")
        if vintage:
            head += f" | {vintage}"
        parts.append(head + "\n" + (c.get("text") or "").strip())
    return "\n\n".join(parts)


def _norm(claim: str) -> str:
    return re.sub(r"\s+", " ", claim.strip().strip('"“”').lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None, help="the job's report (HTML); job-Q&A verifiers see it")
    ap.add_argument("--judges", default=JUDGES)
    ap.add_argument("--verifiers", default=VERIFIERS)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--arms", default="on,off",
                    help="the two arm names in the run files, mapped onto the internal on/off slots "
                         "(e.g. challenger,production for a D-055 replay); the summary records the mapping")
    ap.add_argument("--dates-db", default=None,
                    help="SQLite copy to read each document's publication date and era from, for run "
                         "files whose chunk records predate the `vintage` field")
    ap.add_argument("--tiebreak", default=None,
                    help="same-family fallback for the THIRD verifier: votes only on a claim the first two "
                         "split on and the third has no valid vote for (e.g. after a provider quota runs out)")
    args = ap.parse_args()

    _load_keys()
    from judge_pair import html_to_text

    if args.dates_db:
        _load_vintage(args.dates_db)
        print(f"dates for {len(_VINTAGE)} documents from {args.dates_db}", flush=True)

    runs, out = Path(args.runs), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((runs / "meta.json").read_text(encoding="utf-8"))
    promoted, demoted = set(meta["promoted"]), set(meta["demoted"])
    promoted_names, demoted_names = set(meta["promoted"].values()), set(meta["demoted"].values())
    threshold = float(meta["threshold"])
    report_text = html_to_text(Path(args.report).read_text(encoding="utf-8", errors="replace")) if args.report else ""

    first_arm, second_arm = [a.strip() for a in args.arms.split(",")]
    arm_map = {first_arm: "on", second_arm: "off"}
    pairs: dict[tuple, dict] = {}
    for f in sorted(runs.glob("q*_*_*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        rec["arm"] = arm_map.get(rec["arm"], rec["arm"])
        pairs.setdefault((rec["q"], rec["surface"]), {})[rec["arm"]] = rec
    pairs = {k: v for k, v in pairs.items() if "on" in v and "off" in v and v["on"].get("answer") and v["off"].get("answer")}
    print(f"{len(pairs)} complete pairs", flush=True)

    judge_specs = [s.strip() for s in args.judges.split(",") if s.strip()]
    verifier_specs = [s.strip() for s in args.verifiers.split(",") if s.strip()]
    coin = random.Random(int.from_bytes(os.urandom(8), "big"))

    # ---- 1. judge ---------------------------------------------------------
    tasks = []
    for (q, surface), arms in sorted(pairs.items()):
        pooled: dict[tuple, dict] = {}
        for arm in ("on", "off"):
            for c in arms[arm]["chunks"]:
                pooled.setdefault(_chunk_key(c), c)
        pool = list(pooled.values())
        random.Random(f"{q}-{surface}").shuffle(pool)
        labels = {_chunk_key(c): f"E{i + 1}" for i, c in enumerate(pool)}
        arms["_labels"], arms["_pool_text"] = labels, _render(pool, labels)
        for spec in judge_specs:
            flip = coin.random() < 0.5
            tasks.append((q, surface, spec, ("off", "on") if flip else ("on", "off")))

    def judge(task):
        q, surface, spec, (a_arm, b_arm) = task
        path = out / f"judge_q{q:02d}_{surface}_{re.sub(r'[^a-z0-9]+', '_', spec.lower())}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        arms = pairs[(q, surface)]
        prompt = (JUDGE_RUBRIC + "\n\nQUESTION:\n" + arms["on"]["question"]
                  + "\n\n===== ANSWER A =====\n" + arms[a_arm]["answer"]
                  + "\n\n===== ANSWER B =====\n" + arms[b_arm]["answer"]
                  + "\n\n===== EXCERPTS =====\n" + arms["_pool_text"])
        rec = {"q": q, "surface": surface, "judge": spec, "mapping": {"A": a_arm, "B": b_arm}}
        t0 = time.time()
        try:
            raw = _invoke(spec, prompt, 16_000)
            p = _json(raw)
            rec.update(raw=raw, parsed=p, seconds=round(time.time() - t0, 1))
            rec["unblinded"] = {
                "relevance": {a_arm: p.get("relevance_A"), b_arm: p.get("relevance_B")},
                "faithfulness": {a_arm: p.get("faithfulness_A"), b_arm: p.get("faithfulness_B")},
                "unsupported": {a_arm: p.get("unsupported_claims_A") or [], b_arm: p.get("unsupported_claims_B") or []},
                "preferred": {"A": a_arm, "B": b_arm}.get(p.get("preferred"), "tie"),
            }
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"judged q{q:02d} {surface} {spec}: {rec.get('unblinded', {}).get('preferred', rec.get('error', '?'))}", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as pool_ex:
        verdicts = list(pool_ex.map(judge, tasks))

    # ---- 2. verify --------------------------------------------------------
    claims: dict[tuple, dict] = {}
    for v in verdicts:
        for arm, items in (v.get("unblinded", {}).get("unsupported") or {}).items():
            for claim in items:
                if isinstance(claim, str) and claim.strip():
                    key = (v["q"], v["surface"], arm, _norm(claim))
                    claims.setdefault(key, {"claim": claim.strip(), "flagged_by": []})["flagged_by"].append(v["judge"])

    def existing_checks() -> dict[tuple, dict]:
        # Every check already on disk, keyed by what it checked rather than by
        # file name, so a resumed run re-uses them (a valid vote beats an error).
        # Oldest first: a later run only fills gaps an earlier one left, so a
        # resumed run never re-rolls a vote that already counted.
        found: dict[tuple, dict] = {}
        for f in sorted(out.glob("verify_*.json"), key=lambda f: f.stat().st_mtime):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            k = (rec.get("q"), rec.get("surface"), rec.get("arm"), rec.get("claim_key"), rec.get("verifier"))
            if k not in found or ("error" in found[k] and "error" not in rec):
                found[k] = rec
        return found

    done = existing_checks()

    def votes_for(key, checks_by_key) -> list:
        # One vote per lens. The third lens falls back to --tiebreak only when
        # its configured model never returned a valid vote for this claim.
        out_votes = []
        for i, s in enumerate(verifier_specs):
            rec = checks_by_key.get(key + (s,), {})
            if "supported" not in rec and args.tiebreak and i == len(verifier_specs) - 1:
                rec = checks_by_key.get(key + (args.tiebreak,), {})
            if "supported" in rec:
                out_votes.append(rec)
        return out_votes

    def decided(key) -> bool:
        # Two agreeing valid votes settle a 2-of-3 majority; the third cannot
        # change it, so it is not spent.
        votes = [r["supported"] for r in votes_for(key, done)]
        return votes.count(True) >= 2 or votes.count(False) >= 2

    vtasks = []
    for key in claims:
        if decided(key):
            continue
        for i, spec in enumerate(verifier_specs):
            if "supported" in done.get(key + (spec,), {}):
                continue
            if args.tiebreak and i == len(verifier_specs) - 1:
                # The configured third lens has no valid vote: use the fallback.
                spec = args.tiebreak
                if "supported" in done.get(key + (spec,), {}):
                    continue
            vtasks.append((key, spec))
    print(f"{len(vtasks)} verification checks to run ({len(claims) * len(verifier_specs) - len(vtasks)} reused)", flush=True)

    def verify(task):
        (q, surface, arm, norm), spec = task
        slug = re.sub(r"[^a-z0-9]+", "_", norm)[:60]
        # A STABLE digest: hash() is randomised per process, which made a resumed
        # run miss every earlier file and re-verify everything.
        digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]
        path = out / f"verify_q{q:02d}_{surface}_{arm}_{digest}_{re.sub(r'[^a-z0-9]+', '_', spec.lower())}.json"
        arms = pairs[(q, surface)]
        own = arms[arm]["chunks"]
        report_clause, report = ("", "")
        if surface == "job" and report_text:
            report_clause = " and the research report that follows them"
            report = "\n\n===== REPORT =====\n" + report_text
        prompt = VERIFY_PROMPT.format(claim=claims[(q, surface, arm, norm)]["claim"], report_clause=report_clause,
                                      excerpts=_render(own, arms["_labels"]), report=report)
        rec = {"q": q, "surface": surface, "arm": arm, "claim_key": norm, "slug": slug, "verifier": spec}
        try:
            parsed = _json(_invoke(spec, prompt, 4_000))
            rec["supported"] = bool(parsed.get("supported"))
            rec["evidence"], rec["reason"] = parsed.get("evidence"), parsed.get("reason")
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as pool_ex:
        list(pool_ex.map(verify, vtasks))
    final = existing_checks()
    by_claim: dict[tuple, list] = {key: votes_for(key, final) for key in claims}
    n_valid = sum(len(v) for v in by_claim.values())
    n_tiebreak = sum(1 for v in by_claim.values() for r in v if r.get("verifier") == args.tiebreak)
    print(f"verified {len(claims)} unique claims: {n_valid} valid votes, {n_tiebreak} from the tie-break lens", flush=True)
    claim_rows = []
    for key, info in claims.items():
        votes = [c["supported"] for c in by_claim.get(key, [])]
        unsupported_votes = sum(1 for s in votes if not s)
        status = "confirmed" if unsupported_votes >= 2 else ("refuted" if len(votes) - unsupported_votes >= 2 else "unresolved")
        claim_rows.append({"q": key[0], "surface": key[1], "arm": key[2], "claim": info["claim"],
                           "flagged_by": info["flagged_by"], "votes_unsupported": unsupported_votes,
                           "votes": len(votes), "status": status,
                           "lenses": [c.get("verifier") for c in by_claim.get(key, [])]})

    # ---- 3. summarise -----------------------------------------------------
    def share(rec, ids, names):
        chunks = rec["chunks"]
        refs = rec.get("references") or []
        cs = sum(1 for c in chunks if c.get("channel_id") in ids) / len(chunks) if chunks else 0.0
        rs = sum(1 for r in refs if (r.get("channel_name") or "") in names) / len(refs) if refs else 0.0
        return round(cs, 4), round(rs, 4)

    per_pair = []
    for (q, surface), arms in sorted(pairs.items()):
        row = {"q": q, "surface": surface}
        for arm in ("on", "off"):
            pc, pr = share(arms[arm], promoted, promoted_names)
            dc, dr = share(arms[arm], demoted, demoted_names)
            row[arm] = {"promoted_chunks": pc, "demoted_chunks": dc, "promoted_refs": pr, "demoted_refs": dr,
                        "n_chunks": len(arms[arm]["chunks"]), "n_refs": len(arms[arm].get("references") or []),
                        "over_threshold": sum(1 for c in arms[arm]["chunks"] if float(c.get("distance") or 0) > threshold),
                        "words": len(arms[arm]["answer"].split())}
        per_pair.append(row)

    ok = [v for v in verdicts if "unblinded" in v]

    def mean(xs):
        xs = [float(x) for x in xs if isinstance(x, (int, float))]
        return round(sum(xs) / len(xs), 3) if xs else None

    def m(field, arm, surface=None):
        return mean(r[arm][field] for r in per_pair if surface in (None, r["surface"]))

    prefs = [v["unblinded"]["preferred"] for v in ok]
    non_tie = [p for p in prefs if p in ("on", "off")]
    confirmed = {arm: sum(1 for c in claim_rows if c["arm"] == arm and c["status"] == "confirmed") for arm in ("on", "off")}
    job_rows = [r for r in per_pair if r["surface"] == "job"]
    summary = {
        "arm_names": {"on": first_arm, "off": second_arm},
        "pairs": len(per_pair),
        "judges_ok": len(ok), "judges_total": len(verdicts),
        "M1": {
            "mean_promoted_chunk_share": {a: m("promoted_chunks", a) for a in ("on", "off")},
            "mean_demoted_chunk_share": {a: m("demoted_chunks", a) for a in ("on", "off")},
            "mean_promoted_ref_share": {a: m("promoted_refs", a) for a in ("on", "off")},
            "mean_demoted_ref_share": {a: m("demoted_refs", a) for a in ("on", "off")},
            "job_questions_where_promoted_share_rose": sum(1 for r in job_rows if r["on"]["promoted_chunks"] > r["off"]["promoted_chunks"]),
            "job_questions": len(job_rows),
            "by_surface": {s: {"promoted_chunks": {a: m("promoted_chunks", a, s) for a in ("on", "off")},
                               "demoted_chunks": {a: m("demoted_chunks", a, s) for a in ("on", "off")}}
                           for s in ("job", "library")},
        },
        "M2_on_chunks_over_threshold": sum(r["on"]["over_threshold"] for r in per_pair),
        "R": {
            "mean_relevance": {a: mean(v["unblinded"]["relevance"].get(a) for v in ok) for a in ("on", "off")},
            "mean_faithfulness": {a: mean(v["unblinded"]["faithfulness"].get(a) for v in ok) for a in ("on", "off")},
            "preferred": {k: prefs.count(k) for k in ("on", "off", "tie")},
            "off_share_of_non_tie": round(non_tie.count("off") / len(non_tie), 3) if non_tie else None,
            "by_surface": {s: {"mean_relevance": {a: mean(v["unblinded"]["relevance"].get(a) for v in ok if v["surface"] == s) for a in ("on", "off")},
                               "preferred": {k: [v["unblinded"]["preferred"] for v in ok if v["surface"] == s].count(k) for k in ("on", "off", "tie")}}
                           for s in ("job", "library")},
        },
        "V": {"unique_claims_flagged": {a: sum(1 for c in claim_rows if c["arm"] == a) for a in ("on", "off")},
              "confirmed_unsupported": confirmed,
              "unresolved": sum(1 for c in claim_rows if c["status"] == "unresolved"),
              "decided_with_tiebreak_lens": sum(1 for c in claim_rows if args.tiebreak and args.tiebreak in c["lenses"]),
              "tiebreak_lens": args.tiebreak},
        "mean_words": {a: m("words", a) for a in ("on", "off")},
    }
    r = summary["R"]
    summary["rule"] = {
        "1_mechanism": (summary["M1"]["mean_promoted_chunk_share"]["on"] > summary["M1"]["mean_promoted_chunk_share"]["off"]
                        and summary["M1"]["mean_demoted_chunk_share"]["on"] < summary["M1"]["mean_demoted_chunk_share"]["off"]
                        and summary["M1"]["job_questions_where_promoted_share_rose"] >= 7),
        "2_threshold": summary["M2_on_chunks_over_threshold"] == 0,
        "3_relevance": (r["mean_relevance"]["on"] is not None and r["mean_relevance"]["on"] >= r["mean_relevance"]["off"] - 0.5
                        and (r["off_share_of_non_tie"] is None or r["off_share_of_non_tie"] <= 0.60)),
        "4_faithfulness": confirmed["on"] <= confirmed["off"] + 2,
    }
    (out / "per_pair.json").write_text(json.dumps(per_pair, indent=2), encoding="utf-8")
    (out / "claims.json").write_text(json.dumps(claim_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

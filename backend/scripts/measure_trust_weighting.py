"""T-7.1.1.5 — ask the same questions with trust weights on and off (D-068).

Drives the PRODUCTION callers: `PUT /channels/{id}/weight` sets the weights,
`POST /jobs/{id}/qa` and `POST /library/qa` answer, through FastAPI's
TestClient against COPIES of the dev database and Chroma store, so the
running backend's data is never touched. A spy records the deduplicated
chunks each answer was built from (what the judges and verifiers check
claims against, and what M1/M2 count).

Protocol, weights and questions: docs/notes/2026-10-19-e71-trust-weighting-measurement.md.

Usage (from backend/, with the main venv):
    python scripts/measure_trust_weighting.py --root <scratch dir with vrp.db, chroma/, data/reports/> \
        --env D:/DEV/ClaudeProjects/VideoSearchDB/backend/.env --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

JOB_ID = "0d4db8c3-5f3a-482e-aa00-784d94bb548c"
USER_ID = "d6cdfa65-6fd0-4d01-8460-5eb01302c02c"

# Fixed by the protocol (seeded draw over channels with >= 5 documents).
PROMOTED = {
    "UCKWaEZ-_VweaEx1j62do_vQ": "IBM Technology",
    "UC_x36zCEGilGpB1m-V4gmjg": "IndyDevDan",
    "UCBr1IoxBAF9RDPdTzb6459g": "Volo Builds",
}
DEMOTED = {
    "UCC-lyoTfSrcJzA1ab3APAgw": "LangChain",
    "UCLKPca3kwwd-B59HNr-_lvA": "AI Engineer",
    "UCJS9pqu9BzkAMNTmzNMNhvg": "Google Cloud Tech",
}
ON_WEIGHTS = {**{c: 2.0 for c in PROMOTED}, **{c: 0.0 for c in DEMOTED}}
OFF_WEIGHTS = {c: 1.0 for c in ON_WEIGHTS}

QUESTIONS = [
    "What practices do the sources recommend for writing instruction or rules files (such as CLAUDE.md or Cursor rules) for agentic coding tools?",
    "How do the sources describe the Model Context Protocol (MCP), and what problems is it meant to solve?",
    "What differences do the sources draw between single-agent and multi-agent architectures for software engineering tasks?",
    "What do the sources say about when to use retrieval-augmented generation rather than fine-tuning or a long context window?",
    "How do the sources recommend handling context-window limits during long agentic coding sessions?",
    "Which risks or failure modes of agentic coding tools do the sources warn about, and how do they suggest mitigating them?",
    "How do the sources describe evaluating LLM-based features or agents before shipping them?",
    "What role do sub-agents or parallel agents play in the workflows the sources describe?",
    "What do the sources say about cost and latency trade-offs between LLM models for coding work?",
    "How do the sources suggest structuring a codebase or workflow so that AI coding agents work well in it?",
]


def _prepare_env(root: Path, env_file: Path) -> None:
    """Keys from the main .env (machine-level OS vars shadow it otherwise —
    project memory), storage pointed at the scratch copies. Must run before
    any `app` import: the engine and Chroma path are read at import time."""
    from dotenv import dotenv_values

    for key, value in (dotenv_values(env_file) or {}).items():
        if value is not None:
            os.environ[key] = value
    os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'vrp.db').as_posix()}"
    os.environ["CHROMA_PERSIST_DIR"] = str(root / "chroma")
    os.environ["REPORTS_DIR"] = str(root / "data" / "reports")
    os.environ["RATE_LIMIT_ENABLED"] = "False"
    # jobs.report_path is stored relative to the main backend ("./data/reports/...").
    # Point the SCRATCH copy at its own report copy; never chdir (Alembic's
    # script_location is cwd-relative and the lifespan migrates on start).
    import sqlite3

    con = sqlite3.connect(root / "vrp.db")
    (rel,) = con.execute("select report_path from jobs where id=?", (JOB_ID,)).fetchone()
    if rel and not Path(rel).is_absolute():
        con.execute("update jobs set report_path=? where id=?",
                    (str(root / "data" / "reports" / Path(rel.replace("\\", "/")).name), JOB_ID))
        con.commit()
    con.close()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))


def _chunk_record(r: dict) -> dict:
    m = r.get("metadata", {}) or {}
    return {
        "document_id": m.get("document_id") or "",
        "chunk_index": m.get("chunk_index"),
        "channel_id": m.get("channel_id") or "",
        "channel_name": m.get("channel_name") or "",
        "title": m.get("video_title") or m.get("title") or "",
        "timestamp_start": m.get("timestamp_start"),
        "distance": r.get("distance"),
        "text": r.get("text", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--env", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=71)
    ap.add_argument("--only", default="", help="comma-separated question numbers (1-based), for re-runs")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    _prepare_env(root, Path(args.env).resolve())

    from fastapi.testclient import TestClient

    from app.agents import qa_agent
    from app.config import settings
    from app.database import SessionLocal
    from app.main import app
    from app.services import auth_service, quota_metering_service

    # The harness asks 40 questions as one user; tier quotas are not under test.
    quota_metering_service.enforce_quota_or_raise = lambda *a, **k: None
    quota_metering_service.record_usage = lambda *a, **k: None

    captured: list[dict] = []
    real_retrieve, real_enrich = qa_agent.retrieve_context, qa_agent._enrich_chunks

    def spy_retrieve(state, tally=None):
        result = real_retrieve(state, tally=tally)
        captured.append({"weights": dict(state.get("channel_weights") or {}),
                         "chunks": [_chunk_record(r) for r in result.get("rag_results", [])]})
        return result

    def spy_enrich(chunks):
        captured.append({"weights": None, "chunks": [_chunk_record(r) for r in chunks]})
        return real_enrich(chunks)

    qa_agent.retrieve_context = spy_retrieve
    qa_agent._enrich_chunks = spy_enrich

    db = SessionLocal()
    token, _ = auth_service.create_access_token(USER_ID, db=db)
    db.close()
    headers = {"Authorization": f"Bearer {token}"}

    rng = random.Random(args.seed)
    order = [("on", "off") if rng.random() < 0.5 else ("off", "on") for _ in QUESTIONS]
    only = {int(x) for x in args.only.split(",") if x.strip()}

    with TestClient(app, headers=headers) as client:
        def set_weights(weights: dict) -> None:
            for channel_id, w in weights.items():
                resp = client.put(f"/api/v1/channels/{channel_id}/weight", json={"weight": w})
                resp.raise_for_status()

        meta = {"job": JOB_ID, "threshold": settings.RAG_DISTANCE_THRESHOLD, "top_k": settings.RAG_TOP_K,
                "promoted": PROMOTED, "demoted": DEMOTED, "order": order, "seed": args.seed}
        (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        for qi, question in enumerate(QUESTIONS, start=1):
            if only and qi not in only:
                continue
            for arm in order[qi - 1]:
                set_weights(ON_WEIGHTS if arm == "on" else OFF_WEIGHTS)
                for surface in ("job", "library"):
                    path = out / f"q{qi:02d}_{surface}_{arm}.json"
                    if path.exists():
                        print(f"skip {path.name} (exists)", flush=True)
                        continue
                    captured.clear()
                    t0 = time.time()
                    url = f"/api/v1/jobs/{JOB_ID}/qa" if surface == "job" else "/api/v1/library/qa"
                    resp = client.post(url, json={"question": question})
                    rec = {"q": qi, "question": question, "surface": surface, "arm": arm,
                           "status": resp.status_code, "seconds": round(time.time() - t0, 1)}
                    if resp.status_code == 200:
                        body = resp.json()
                        rec["answer"] = body.get("answer", "")
                        rec["references"] = body.get("references", [])
                    else:
                        rec["error"] = resp.text[:2000]
                    rec["chunks"] = captured[-1]["chunks"] if captured else []
                    rec["weights_seen_by_agent"] = captured[-1]["weights"] if captured else None
                    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(f"q{qi:02d} {surface:7s} {arm:3s} -> {resp.status_code} "
                          f"{len(rec['chunks'])} chunks {rec['seconds']}s", flush=True)
        set_weights(OFF_WEIGHTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

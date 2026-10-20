"""T-5.10.2.7 — D-055 exact-input replay of library Q&A's answer step.

D-055 measures how much answer quality a production tier gives up by replaying
production's EXACT inputs through a stronger model at maximum effort and
judging the two outputs blind. Library Q&A has answered from a per-user corpus
since D-063 (and through the trust re-rank since D-068), so its delta is
re-measured here.

For each question this script:
1. asks `POST /library/qa` through the production route (FastAPI TestClient,
   minted token, scratch COPIES of the dev database and Chroma store — never
   the live ones), capturing the exact system + user messages and token budget
   the `library_qa_formulate_answer` call received, and the chunks retrieved;
2. replays those messages unchanged through the challenger model, giving it
   production's budget plus thinking room;
3. runs the challenger's answer through the same citation sanitiser production
   applies, so the two answers differ only by the model that wrote them.

Output files match `judge_qa_pairs.py` (arms `production` / `challenger`).

Usage (from backend/, main venv):
    python scripts/replay_library_qa_d055.py --root <scratch dir> --env <main backend/.env> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

from measure_trust_weighting import QUESTIONS, USER_ID, _chunk_record, _prepare_env  # noqa: E402

CHALLENGER = "anthropic:claude-opus-5:high"
THINKING_ROOM = 32_000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--env", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--challenger", default=CHALLENGER)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    root, out = Path(args.root).resolve(), Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    _prepare_env(root, Path(args.env).resolve())

    from fastapi.testclient import TestClient

    from app.agents import qa_agent
    from app.config import settings
    from app.database import SessionLocal
    from app.main import app
    from app.services import auth_service, quota_metering_service
    from app.services.llm_routing import UseCaseConfig, resolve_config
    from app.services.llm_service import _build_from_config, response_text

    quota_metering_service.enforce_quota_or_raise = lambda *a, **k: None
    quota_metering_service.record_usage = lambda *a, **k: None

    captured: dict = {}
    real_get_llm, real_enrich = qa_agent.get_llm_for, qa_agent._enrich_chunks

    def spy_get_llm(use_case, **kwargs):
        llm = real_get_llm(use_case, **kwargs)
        if use_case != "library_qa_formulate_answer":
            return llm

        class _Recorder:
            def invoke(self, messages, *a, **k):
                captured["messages"] = [(type(m).__name__, m.content) for m in messages]
                captured["kwargs"] = dict(kwargs)
                return llm.invoke(messages, *a, **k)

        return _Recorder()

    def spy_enrich(chunks):
        captured["rag_results"] = chunks
        return real_enrich(chunks)

    qa_agent.get_llm_for = spy_get_llm
    qa_agent._enrich_chunks = spy_enrich

    prod_cfg = resolve_config("library_qa_formulate_answer")
    provider, model, reasoning = args.challenger.split(":")
    meta = {
        "method": "D-055 exact-input replay", "surface": "library",
        "production": f"{prod_cfg.provider}:{prod_cfg.model}:{prod_cfg.reasoning}",
        "challenger": args.challenger, "thinking_room": THINKING_ROOM,
        "threshold": settings.RAG_DISTANCE_THRESHOLD, "top_k": settings.RAG_TOP_K,
        # judge_qa_pairs.py reads these for the E-7.1 mechanism metrics; empty here.
        "promoted": {}, "demoted": {},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    db = SessionLocal()
    token, _ = auth_service.create_access_token(USER_ID, db=db)
    db.close()
    only = {int(x) for x in args.only.split(",") if x.strip()}

    from langchain_core.messages import HumanMessage, SystemMessage

    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        for qi, question in enumerate(QUESTIONS, start=1):
            if only and qi not in only:
                continue
            p_path, c_path = out / f"q{qi:02d}_library_production.json", out / f"q{qi:02d}_library_challenger.json"
            if p_path.exists() and c_path.exists():
                print(f"skip q{qi:02d} (exists)", flush=True)
                continue
            captured.clear()
            t0 = time.time()
            resp = client.post("/api/v1/library/qa", json={"question": question})
            resp.raise_for_status()
            body = resp.json()
            chunks = [_chunk_record(r) for r in captured.get("rag_results", [])]
            base = {"q": qi, "question": question, "surface": "library", "chunks": chunks}
            p_path.write_text(json.dumps({**base, "arm": "production", "answer": body.get("answer", ""),
                                          "references": body.get("references", []),
                                          "seconds": round(time.time() - t0, 1),
                                          "max_tokens": captured.get("kwargs", {}).get("max_tokens"),
                                          "messages": captured.get("messages")},
                                         indent=2, ensure_ascii=False), encoding="utf-8")

            msgs = [SystemMessage(content=c) if kind == "SystemMessage" else HumanMessage(content=c)
                    for kind, c in captured["messages"]]
            budget = int(captured["kwargs"].get("max_tokens") or 4_500) + THINKING_ROOM
            t1 = time.time()
            llm = _build_from_config(UseCaseConfig(provider, model, reasoning), temperature=1.0, max_tokens=budget)
            raw = response_text(llm.invoke(msgs))
            sanitized, removed = qa_agent._sanitize_citations(raw, captured.get("rag_results", []))
            c_path.write_text(json.dumps({**base, "arm": "challenger", "answer": sanitized, "references": [],
                                          "seconds": round(time.time() - t1, 1), "max_tokens": budget,
                                          "citations_removed_by_sanitizer": removed},
                                         indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"q{qi:02d}: production {len(body.get('answer', '').split())} words, "
                  f"challenger {len(sanitized.split())} words ({round(time.time() - t1, 1)}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

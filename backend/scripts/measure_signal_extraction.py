"""Measure signal extraction (S-3.3.2) on the synthetic personas: cost, yield, drops.

Builds a scratch SQLite database (never the dev database), writes each
persona's notes and questions as a Studio tenant, and runs the real
extraction with the registry's model for ``echo_extract_signals``. Then it
adds the persona's held-out texts as new notes and runs again, which is the
incremental cost a user pays as they keep writing.

    cd backend
    ./venv/Scripts/python scripts/measure_signal_extraction.py --repeats 2 \
        --out ../docs/notes/2026-10-19-signal-extraction-cost.json

The personas are invented (tests/fixtures/echo_voice/personas.json), so the
output may name signal values. Run against real data only through a copy,
and publish aggregates only.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parent
FIXTURE = BACKEND / "tests" / "fixtures" / "echo_voice" / "personas.json"


def _setup_db() -> str:
    tmp = tempfile.mkdtemp(prefix="signals-measure-")
    os.environ["DATABASE_URL"] = f"sqlite:///{pathlib.Path(tmp, 'measure.db').as_posix()}"
    os.environ["ECHO_SIGNAL_EXTRACTION"] = "off"  # the hooks must not queue; the script runs extraction itself
    sys.path.insert(0, str(BACKEND))
    return tmp


def _one(persona_name: str, persona: dict) -> dict:
    from app.database import Base, SessionLocal, engine
    from app.models.job import Job
    from app.models.library_qa_exchange import LibraryQAExchange
    from app.services import auth_service, echo_signal_service, note_service
    from app.services import echo_signal_extraction as ex

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        user = auth_service.create_user(db, email=f"{persona_name}-{time.time_ns()}@example.com", password="pw" * 8)
        user.tier = "studio"
        job_id = f"job-{user.id[:8]}"
        db.add(Job(id=job_id, tenant_id=user.id, job_type="topic", topic="t", status="completed"))
        db.commit()
        for text in persona["notes"]:
            note_service.create_note(db, user.id, target_type="job", target_id=job_id, body_md=text)
        for q in persona["questions"]:
            db.add(LibraryQAExchange(tenant_id=user.id, question=q, answer="(answer)"))
        db.commit()
        words = sum(len(t.split()) for t in persona["notes"] + persona["questions"])

        t0 = time.perf_counter()
        first = ex.run(db, user.id)
        first_s = time.perf_counter() - t0

        for text in persona["held_out"]:
            note_service.create_note(db, user.id, target_type="job", target_id=job_id, body_md=text)
        t0 = time.perf_counter()
        second = ex.run(db, user.id)
        second_s = time.perf_counter() - t0

        rows = echo_signal_service.list_signals(db, user.id)
        by_origin: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for r in rows:
            by_origin[r.origin] = by_origin.get(r.origin, 0) + 1
            by_type[r.signal_type] = by_type.get(r.signal_type, 0) + 1
        return {
            "persona": persona_name,
            "inputs": len(persona["notes"]) + len(persona["questions"]),
            "words": words,
            "backlog_run": {**first.to_dict(), "seconds": round(first_s, 1)},
            "incremental_run": {**second.to_dict(), "seconds": round(second_s, 1), "new_inputs": len(persona["held_out"])},
            "signals_live": len(rows),
            "by_origin": by_origin,
            "by_type": by_type,
            "signals": [
                {"type": r.signal_type, "value": r.value, "weight": r.weight, "language": r.language,
                 "examples": len(json.loads(r.examples_json))}
                for r in rows
            ],
        }
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--out", type=pathlib.Path)
    args = ap.parse_args()
    _setup_db()
    from app.services.llm_routing import resolve_config

    cfg = resolve_config("echo_extract_signals")
    personas = json.loads(FIXTURE.read_text(encoding="utf-8"))["personas"]
    runs = []
    for rep in range(args.repeats):
        for name, persona in personas.items():
            result = _one(name, persona)
            result["repeat"] = rep + 1
            runs.append(result)
            b, i = result["backlog_run"], result["incremental_run"]
            print(
                f"{name} #{rep + 1}: {result['inputs']} inputs, {result['words']} words -> "
                f"backlog {b['batches']} batch(es) {b['tokens_in']}/{b['tokens_out']} tok ${b['cost_usd']:.5f} "
                f"{b['seconds']}s, {b['created']} created, {b['examples_dropped']} examples dropped; "
                f"incremental +{i['new_inputs']}: ${i['cost_usd']:.5f}, {i['merged']} merged / {i['created']} new; "
                f"live {result['signals_live']} {result['by_origin']}"
            )
    backlog_cost = sum(r["backlog_run"]["cost_usd"] for r in runs)
    backlog_inputs = sum(r["inputs"] for r in runs)
    backlog_words = sum(r["words"] for r in runs)
    inc_cost = sum(r["incremental_run"]["cost_usd"] for r in runs)
    inc_inputs = sum(r["incremental_run"]["new_inputs"] for r in runs)
    summary = {
        "model": f"{cfg.provider}:{cfg.model}:{cfg.reasoning}",
        "repeats": args.repeats,
        "backlog_cost_per_100_inputs_usd": round(100 * backlog_cost / backlog_inputs, 5),
        "backlog_cost_per_10k_words_usd": round(10_000 * backlog_cost / backlog_words, 5),
        "incremental_cost_per_100_inputs_usd": round(100 * inc_cost / inc_inputs, 5),
        "examples_dropped_total": sum(r["backlog_run"]["examples_dropped"] + r["incremental_run"]["examples_dropped"] for r in runs),
        "calls_failed_total": sum(r["backlog_run"]["calls_failed"] + r["incremental_run"]["calls_failed"] for r in runs),
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        args.out.write_text(json.dumps({"summary": summary, "runs": runs}, indent=2, ensure_ascii=False), encoding="utf-8")
        print("wrote", args.out)


if __name__ == "__main__":
    main()

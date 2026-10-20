"""Generate one book with and without the cohesion pass, for blind judging
(S-6.1.3). Works on a COPY of a library database, never the original.

Each level is a real generation through the book outputter, so the arms
differ only in ``parameters.cohesion``. Writes ``<label>_<level>.md`` (the
manuscript) and ``<label>_<level>.usage.json`` (the output's ``usage_json``:
per-call model, tokens and cost) into ``--out``, and prints one summary line
per arm. Judge the pair with ``scripts/judge_pair.py --rubric book``.

Usage (from backend/, inside the venv):
    python scripts/book_cohesion_trial.py --source-db ../data/videoresearchpro.db \\
        --tenant <user id> --jobs <job id>,<job id> --title "A book" --label book1 \\
        --out ./trial --env-file ../.env

``--env-file`` is read for API keys and LLM_* settings only (machine-wide
variables can shadow the app's .env, so keys are never taken from the
process environment). The copy, its reports and its outputs live in --out.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-db", required=True, help="the library database to COPY (opened read-only)")
    ap.add_argument("--tenant", required=True, help="user id that owns the runs")
    ap.add_argument("--jobs", required=True, help="comma-separated job ids, in the user's chapter order")
    ap.add_argument("--title", required=True)
    ap.add_argument("--label", required=True, help="file prefix for this book")
    ap.add_argument("--levels", default="none,full")
    ap.add_argument("--out", required=True)
    ap.add_argument("--env-file", default=str(BACKEND / ".env"))
    ap.add_argument("--no-qa", action="store_true", help="leave each run's Q&A out (the UI includes it)")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    copy = out / "trial.db"
    if not copy.exists():
        source = sqlite3.connect(f"file:{Path(args.source_db).resolve().as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        source.backup(target)
        source.close()
        target.close()

    from dotenv import dotenv_values

    for key, value in (dotenv_values(args.env_file) or {}).items():
        if value is not None and (key.endswith("_API_KEY") or key.startswith("LLM_")):
            os.environ[key] = value
    os.environ["DATABASE_URL"] = "sqlite:///" + copy.as_posix()
    os.environ["OUTPUTS_DIR"] = str(out / "outputs")
    os.environ["AUTHOR_PDF_ENGINE"] = "off"
    sys.path.insert(0, str(BACKEND))

    from app.config import settings
    from app.database import Base, SessionLocal
    import app.models  # noqa: F401 — every table on the metadata
    from app.models.job import Job
    from app.models.user import User
    from app.services import output_service
    from app.services.schema_init_service import ensure_schema_at_head
    import app.services.outputters  # noqa: F401 — registers the book outputter

    ensure_schema_at_head(settings.DATABASE_URL, Base.metadata)
    job_ids = [j.strip() for j in args.jobs.split(",") if j.strip()]
    reports = out / "reports"
    reports.mkdir(exist_ok=True)

    db = SessionLocal()
    try:
        user = db.get(User, args.tenant)
        if user is None:
            raise SystemExit(f"no user {args.tenant} in the copy")
        for jid in job_ids:
            job = db.query(Job).filter(Job.id == jid, Job.tenant_id == user.id).first()
            if job is None or not job.report_path:
                raise SystemExit(f"run {jid} is not this user's, or has no report")
            # Reports (and the Markdown cache written beside them) move into
            # --out, so the original library's files are only ever read.
            here = reports / Path(job.report_path.replace("\\", "/")).name
            if not here.exists():
                original = Path(job.report_path)
                if not original.is_absolute():
                    original = Path(args.source_db).resolve().parent.parent / job.report_path
                shutil.copyfile(original, here)
            job.report_path = str(here)
        db.commit()

        for level in [lv.strip() for lv in args.levels.split(",") if lv.strip()]:
            row = output_service.create_output(
                db, user_id=user.id, kind="book", title=args.title, source_ids=job_ids,
                parameters={"include_qa": not args.no_qa, "cohesion": level, "formats": []},
            )
            t0 = time.time()
            with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
                row = output_service.run_generation(db, user, row)
            usage = json.loads(row.usage_json) if row.usage_json else None
            (out / f"{args.label}_{level}.md").write_text(row.content_text or "", encoding="utf-8")
            (out / f"{args.label}_{level}.usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
            print(json.dumps({
                "label": args.label, "level": level, "status": row.status, "error": row.error_message,
                "words": len((row.content_text or "").split()), "seconds": round(time.time() - t0, 1),
                "applied": (usage or {}).get("cohesion", {}).get("applied", "none"),
                "input_tokens": (usage or {}).get("input_tokens"), "output_tokens": (usage or {}).get("output_tokens"),
                "cost_usd": (usage or {}).get("cost_usd"),
            }), flush=True)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

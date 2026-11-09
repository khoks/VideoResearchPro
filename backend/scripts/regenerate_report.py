"""Regenerate a completed job's report through the shipped pipeline.

Rebuilds the job's chunks from `transcript_cache` (no YouTube traffic),
runs `run_report_agent` exactly as the Celery worker does, and writes the
HTML to a file of your choosing. The job's stored report is NOT replaced
unless `--save` is passed, so this is safe for before/after measurement.

Every approved document of the job is read, whatever its source type: they
are picked by `document_id` through the job's `job_documents` rows, as the
worker picks them (T-8.8.6.9, D-070). A document with no cached text is
left out, and the log counts those by source type.

    ./venv/Scripts/python scripts/regenerate_report.py --job 0d4db8c3-... --out /tmp/after.html

Costs the same as the job's original report phase (~$12 on the 200-video
reference corpus, ~50 minutes).

Writes to live data unless `--no-era` is passed: each document with no
discussed era yet gets one (R3), one model call each, for every source type.
The era is written to the document's `discussed_era_json` and, for a document
already embedded, stamped on its stored Chroma chunks (metadata only, no
re-embed, T-1.17.3.3), as a job does. `--no-era` skips both.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def approved_documents(db, job_id: str) -> list:
    """The job's approved documents, of every source type.

    Joined on ``document_id`` through the job's ``job_documents`` rows, as
    ``resume_job_after_approval`` joins them. The legacy ``video_id`` is NULL
    for a PDF, a pasted page, a thread or a podcast episode, so the join on it
    that this script made until T-8.8.6.9 left every one of them out (D-070).
    """
    from app.models.document import Document
    from app.models.job_video import JobVideo

    return (
        db.query(Document)
        .join(JobVideo, JobVideo.document_id == Document.document_id)
        .filter(JobVideo.job_id == job_id, JobVideo.approved.is_(True))
        .all()
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True, help="job id (prefix accepted)")
    ap.add_argument("--out", type=Path, required=True, help="where to write the regenerated HTML")
    ap.add_argument("--save", action="store_true", help="also replace the job's stored report")
    ap.add_argument("--limit", type=int, default=0, help="only the first N approved documents (smoke runs)")
    ap.add_argument(
        "--no-era", action="store_true",
        help="skip discussed-era extraction for undated documents: no model call for it, "
             "and no era written to the documents or their stored Chroma chunks",
    )
    ap.add_argument(
        "--persist-intermediates", action="store_true",
        help="store this run's map/reduce intermediates under the job (S-1.14.6), "
             "as a new run next to the job's original one",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("regenerate_report")

    from app.config import settings
    from app.database import SessionLocal
    from app.models.job import Job
    from app.services import llm_service
    from app.tasks.job_tasks import (
        _build_video_metadata,
        _ensure_era,
        _load_cached_segments,
        _persist_report_intermediates,
    )
    from app.utils import tiktoken_cache
    from app.utils.chunking import chunk_transcript
    from app.utils.html_builder import build_report_html, save_report

    # T-8.8.6.6: the encoding in TIKTOKEN_ENCODINGS_DIR, as the API and the worker keep it.
    tiktoken_cache.use_app_folder(settings.TIKTOKEN_ENCODINGS_DIR)

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id.like(f"{args.job}%")).first()
        if job is None:
            log.error("no job matching %r", args.job)
            return 2
        docs = approved_documents(db, job.id)
        if args.limit:
            docs = docs[: args.limit]
        log.info("job %s (%s): %d approved documents", job.id, job.topic, len(docs))

        chunks: list[dict] = []
        missing: Counter[str] = Counter()
        started = time.monotonic()
        for i, doc in enumerate(docs, 1):
            # The cache's key first, the only one a non-video document has;
            # the legacy video_id is the fallback, as in the worker.
            cached = _load_cached_segments(doc.video_id, doc.document_id)
            if cached is None:
                missing[doc.source_type or "video"] += 1
                continue
            segments, language = cached
            if not args.no_era:
                _ensure_era(db, doc, segments, job.id)
            chunks.extend(chunk_transcript(
                segments,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
                video_metadata=_build_video_metadata(doc, language),
            ))
            if i % 25 == 0:
                log.info("chunked %d/%d documents (%d chunks)", i, len(docs), len(chunks))
        unread = sum(missing.values())
        log.info(
            "%d chunks from %d documents (%d without cached text%s) in %.0fs",
            len(chunks), len(docs) - unread, unread,
            "".join(f", {n} {kind}" for kind, n in sorted(missing.items())),
            time.monotonic() - started,
        )

        from app.agents.report_agent import run_report_agent

        started = time.monotonic()
        intermediates: dict | None = {} if args.persist_intermediates else None
        with llm_service.byok_context(job.tenant_id, db):
            statistics, body = run_report_agent(
                job_type=job.job_type,
                topic=job.topic or "Channel Collection",
                transcript_chunks=chunks,
                output_length=job.output_length,
                intermediates_out=intermediates,
            )
        log.info("report agent finished in %.0f min", (time.monotonic() - started) / 60)
        if intermediates is not None:
            n = _persist_report_intermediates(db, job.id, intermediates)
            log.info("persisted %d intermediate row(s)", n)

        title = f"Research Report: {job.topic}" if job.job_type == "topic" else "Channel Collection Report"
        html = build_report_html(title=title, job_type=job.job_type, statistics=statistics, report_body=body)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
        log.info("wrote %s (%d chars)", args.out, len(html))
        if args.save:
            path = save_report(job.id, html)
            job.report_path = path
            db.commit()
            log.info("replaced the job's stored report at %s", path)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

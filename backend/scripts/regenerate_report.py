"""Regenerate a completed job's report through the shipped pipeline.

Rebuilds the job's chunks from `transcript_cache` (no YouTube traffic),
runs `run_report_agent` exactly as the Celery worker does, and writes the
HTML to a file of your choosing. The job's stored report is NOT replaced
unless `--save` is passed, so this is safe for before/after measurement.

    ./venv/Scripts/python scripts/regenerate_report.py --job 0d4db8c3-... --out /tmp/after.html

Costs the same as the job's original report phase (~$12 on the 200-video
reference corpus, ~50 minutes). Era extraction (R3) runs for any document
that has none yet and is persisted, which is the normal ingest behaviour.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True, help="job id (prefix accepted)")
    ap.add_argument("--out", type=Path, required=True, help="where to write the regenerated HTML")
    ap.add_argument("--save", action="store_true", help="also replace the job's stored report")
    ap.add_argument("--limit", type=int, default=0, help="only the first N approved documents (smoke runs)")
    ap.add_argument("--no-era", action="store_true", help="skip discussed-era extraction for undated documents")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("regenerate_report")

    from app.config import settings
    from app.database import SessionLocal
    from app.models.document import Document
    from app.models.job import Job
    from app.models.job_video import JobVideo
    from app.services import llm_service
    from app.tasks.job_tasks import _build_video_metadata, _ensure_era, _load_cached_segments
    from app.utils.chunking import chunk_transcript
    from app.utils.html_builder import build_report_html, save_report

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id.like(f"{args.job}%")).first()
        if job is None:
            log.error("no job matching %r", args.job)
            return 2
        docs = (
            db.query(Document)
            .join(JobVideo, JobVideo.video_id == Document.video_id)
            .filter(JobVideo.job_id == job.id, JobVideo.approved.is_(True))
            .all()
        )
        if args.limit:
            docs = docs[: args.limit]
        log.info("job %s (%s): %d approved documents", job.id, job.topic, len(docs))

        chunks: list[dict] = []
        missing = 0
        started = time.monotonic()
        for i, video in enumerate(docs, 1):
            cached = _load_cached_segments(video.video_id)
            if cached is None:
                missing += 1
                continue
            segments, language = cached
            if not args.no_era:
                _ensure_era(db, video, segments, job.id)
            chunks.extend(chunk_transcript(
                segments,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
                video_metadata=_build_video_metadata(video, language),
            ))
            if i % 25 == 0:
                log.info("chunked %d/%d documents (%d chunks)", i, len(docs), len(chunks))
        log.info(
            "%d chunks from %d documents (%d without a cached transcript) in %.0fs",
            len(chunks), len(docs) - missing, missing, time.monotonic() - started,
        )

        from app.agents.report_agent import run_report_agent

        started = time.monotonic()
        with llm_service.byok_context(job.tenant_id, db):
            statistics, body = run_report_agent(
                job_type=job.job_type,
                topic=job.topic or "Channel Collection",
                transcript_chunks=chunks,
                output_length=job.output_length,
            )
        log.info("report agent finished in %.0f min", (time.monotonic() - started) / 60)

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

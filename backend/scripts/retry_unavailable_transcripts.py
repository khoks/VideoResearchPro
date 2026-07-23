"""Re-fetch transcripts for a job's unavailable documents — S-1.11.9 / D-051.

The 200-video test run (job 0d4db8c3) lost 63 videos to an IP-block
cascade: 36 exceeded the (then-unsplit) 25 MB Whisper cap and 27 hit
yt-dlp 403s. With the E-1.11 resilience fixes in place (segmented
Whisper, yt-dlp client ladder, circuit breaker), most of those become
recoverable — this script retries exactly the ``transcript_status =
'unavailable'`` documents of a job, and on success:

1. updates the Document row (status / language / word_count / source /
   transcripted_at / embedded_in_chroma),
2. chunks the transcript with the same chunker the orchestrator uses,
3. embeds the chunks into the global Chroma collection.

The job's existing HTML report is NOT regenerated (it reflects the
corpus at generation time). Job-scoped and library-wide Q&A see the
recovered content immediately. Use the UI's "Re-run" to produce a fresh
report if wanted — recovered transcripts are cache hits there.

Usage:
    cd backend
    ./venv/Scripts/python scripts/retry_unavailable_transcripts.py --job <job_id>
    ./venv/Scripts/python scripts/retry_unavailable_transcripts.py --job <job_id> --limit 10
    ./venv/Scripts/python scripts/retry_unavailable_transcripts.py --job <job_id> --dry-run
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.job_video import JobVideo  # noqa: E402
from app.services import chroma_service  # noqa: E402
from app.sources import connector_for  # noqa: E402
from app.sources.types import Candidate  # noqa: E402
from app.tasks.job_tasks import _build_video_metadata  # noqa: E402
from app.utils.chunking import chunk_transcript  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, help="Job ID to recover")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max documents to retry (0 = all unavailable)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List the would-be-retried documents and exit",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == args.job).first()
        if job is None:
            print(f"Job {args.job} not found")
            return 1

        rows = (
            db.query(Document)
            .join(JobVideo, JobVideo.video_id == Document.video_id)
            .filter(
                JobVideo.job_id == args.job,
                JobVideo.approved.is_(True),
                Document.transcript_status == "unavailable",
            )
            .all()
        )
        if args.limit > 0:
            rows = rows[: args.limit]

        print(f"Job {args.job}: {len(rows)} unavailable document(s) to retry")
        if args.dry_run:
            for d in rows:
                print(f"  - {d.source_type}:{d.source_id}  {(d.title or '')[:70]}")
            return 0

        recovered = 0
        still_unavailable = 0
        for idx, doc in enumerate(rows, start=1):
            title_preview = (doc.title or "")[:60]
            print(f"[{idx}/{len(rows)}] {doc.source_id}  '{title_preview}' ...", flush=True)
            connector = connector_for(doc.source_type)
            try:
                extracted = connector.fetch_text(
                    Candidate(
                        source_type=doc.source_type,
                        source_id=doc.source_id,
                        title=doc.title,
                        source_url=doc.source_url or doc.url,
                    ),
                    job_id=args.job,
                    query=job.topic or "",
                )
            except Exception as e:
                print(f"    fetch raised: {e}")
                extracted = None

            if not extracted:
                still_unavailable += 1
                print("    still unavailable")
                continue

            doc.transcript_status = "fetched"
            doc.transcript_word_count = extracted.word_count
            doc.transcript_language = extracted.language
            if hasattr(doc, "transcripted_at"):
                doc.transcripted_at = datetime.now(timezone.utc)
            if hasattr(doc, "transcript_source"):
                doc.transcript_source = extracted.text_source

            chunks = chunk_transcript(
                extracted.segments,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
                video_metadata=_build_video_metadata(doc, extracted.language),
            )
            chroma_service.insert_chunks(chunks)
            if hasattr(doc, "embedded_in_chroma"):
                doc.embedded_in_chroma = True
            db.commit()
            recovered += 1
            print(
                f"    RECOVERED via {extracted.text_source}: "
                f"{extracted.word_count} words -> {len(chunks)} chunks"
            )

        print()
        print(
            f"Done: {recovered} recovered, {still_unavailable} still unavailable "
            f"(of {len(rows)} attempted)"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

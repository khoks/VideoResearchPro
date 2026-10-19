"""Replay one job's chunks through the report agent with and without visual
annotations — the controlled A/B for S-1.18.3 (R1 visual understanding).

Why a replay rather than two jobs: discovery is not deterministic, so two
searches would not give the same corpus. Here both arms share the videos, the
cached transcript text, the chunker and the models; the only difference is
whether `[VISUAL @ mm:ss — …]` spans are merged in (D-067). The protocol and
the pre-registered decision rule live in
docs/notes/2026-10-18-r1-visual-measurement.md.

Usage (from backend/, inside the venv):
    python scripts/replay_visual_ab.py --job-id <id> --out ../data/r1_ab/<run>

Writes on.html / off.html, their statistics, the annotated transcript the
judges verify against, and a manifest with frame + chunk counts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# OS-level OPENAI_API_KEY / GOOGLE_API_KEY shadow backend/.env under
# pydantic-settings precedence (found 2026-07-29). Load .env first and let it win.
from dotenv import dotenv_values  # noqa: E402

for _k, _v in (dotenv_values(BACKEND / ".env") or {}).items():
    if _v is not None and (_k.endswith("_API_KEY") or _k.startswith(("LLM_", "VISUAL_", "CHUNK_"))):
        os.environ[_k] = _v

from app.agents.report_agent import run_report_agent  # noqa: E402
from app.agents.visual_agent import _existing_frames  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.job_video import JobVideo  # noqa: E402
from app.services.visual_service import annotate_segments  # noqa: E402
from app.tasks.job_tasks import _build_video_metadata, _load_cached_segments  # noqa: E402
from app.utils.chunking import chunk_transcript  # noqa: E402

MARKER = "[VISUAL @"


def _log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def build_arms(db, job_id: str) -> tuple[dict, list[dict], list[dict], list[str]]:
    """Return (manifest, chunks_on, chunks_off, annotated_transcript_blocks)."""
    links = (
        db.query(JobVideo)
        .filter(JobVideo.job_id == job_id, JobVideo.approved.is_(True))
        .all()
    )
    if not links:
        sys.exit(f"no approved videos for job {job_id}")

    chunks_on: list[dict] = []
    chunks_off: list[dict] = []
    transcript_blocks: list[str] = []
    videos: list[dict] = []
    frames_total = frames_informative = frames_done = 0

    for link in links:
        doc = db.query(Document).filter(Document.document_id == link.document_id).first()
        if doc is None or not doc.video_id:
            _log(f"skip link {link.document_id}: no document / video_id")
            continue
        cached = _load_cached_segments(doc.video_id)
        if cached is None:
            _log(f"skip {doc.video_id}: no cached transcript")
            continue
        segments, language = cached
        frames = _existing_frames(db, doc.video_id)
        done = [f for f in frames if f.status == "described" or (f.description and f.status not in ("failed", "skipped"))]
        informative = [f for f in done if f.informative]
        frames_total += len(frames)
        frames_done += len(done)
        frames_informative += len(informative)

        meta = _build_video_metadata(doc, language)
        annotated = annotate_segments(segments, frames)
        on = chunk_transcript(annotated, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP, video_metadata=meta)
        off = chunk_transcript(segments, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP, video_metadata=meta)
        chunks_on.extend(on)
        chunks_off.extend(off)

        n_marked = sum(1 for c in on if MARKER in (c.get("text") or ""))
        videos.append({
            "video_id": doc.video_id,
            "title": doc.title,
            "frames": len(frames),
            "frames_described": len(done),
            "frames_informative": len(informative),
            "chunks": len(off),
            "chunks_with_visual": n_marked,
        })
        header = f"=== {doc.title} (https://www.youtube.com/watch?v={doc.video_id}) ==="
        body = "\n".join((s.get("text") or "") for s in annotated)
        transcript_blocks.append(f"{header}\n{body}\n")
        _log(f"{doc.video_id}: {len(frames)} frames ({len(informative)} informative) -> {n_marked}/{len(on)} chunks annotated")

    manifest = {
        "job_id": job_id,
        "videos": videos,
        "video_count": len(videos),
        "frames_total": frames_total,
        "frames_described": frames_done,
        "frames_informative": frames_informative,
        "chunks_on": len(chunks_on),
        "chunks_off": len(chunks_off),
        "chunks_with_visual": sum(v["chunks_with_visual"] for v in videos),
        "chunk_size": settings.CHUNK_SIZE,
        "chunk_overlap": settings.CHUNK_OVERLAP,
    }
    return manifest, chunks_on, chunks_off, transcript_blocks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--arms", default="on,off", help="comma list of arms to generate (on,off)")
    ap.add_argument("--topic", default=None, help="override the job's topic string")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == args.job_id).first()
        if job is None:
            sys.exit(f"job {args.job_id} not found")
        topic = args.topic or job.topic or "untitled"
        manifest, chunks_on, chunks_off, blocks = build_arms(db, args.job_id)
        manifest["topic"] = topic
        manifest["job_type"] = job.job_type
        manifest["output_length"] = getattr(job, "output_length", None)
    finally:
        db.close()

    (out / "transcript_annotated.txt").write_text("\n".join(blocks), encoding="utf-8")
    if manifest["chunks_with_visual"] == 0:
        _log("WARNING: no chunk carries a visual span; the ON arm equals the OFF arm")

    for arm in arms:
        chunks = chunks_on if arm == "on" else chunks_off
        _log(f"running report agent for arm={arm} over {len(chunks)} chunks ...")
        t0 = time.time()
        stats, html = run_report_agent(manifest["job_type"], topic, chunks, output_length=manifest["output_length"])
        secs = round(time.time() - t0, 1)
        (out / f"{arm}.html").write_text(html or "", encoding="utf-8")
        (out / f"{arm}.statistics.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
        manifest[f"{arm}_seconds"] = secs
        manifest[f"{arm}_html_chars"] = len(html or "")
        _log(f"arm={arm} done in {secs}s, {len(html or '')} chars")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    _log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

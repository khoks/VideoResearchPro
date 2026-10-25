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

``--env-file`` names the .env whose API keys and LLM_* / VISUAL_* / CHUNK_*
settings to use (default backend/.env beside this script) — a worktree has
none of its own. Like judge_pair.py, it is read before the app is imported.
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


def _env_file_from_argv(argv: list[str]) -> Path:
    """``--env-file`` read before the app is imported: settings are built at import time."""
    for i, arg in enumerate(argv):
        if arg == "--env-file" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--env-file="):
            return Path(arg.split("=", 1)[1])
    return BACKEND / ".env"


for _k, _v in (dotenv_values(_env_file_from_argv(sys.argv)) or {}).items():
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


class _FrameProxy:
    """A stored frame with its description swapped for another model's.

    `annotate_segments` only reads timestamp_seconds / description /
    informative / status, so a proxy lets the ON arm be rebuilt from a
    re-tier run (retier_vision.py output) without touching the database.
    """

    def __init__(self, frame, description: str | None, informative) -> None:
        self.timestamp_seconds = frame.timestamp_seconds
        self.status = frame.status
        self.description = description
        self.informative = informative


def load_descriptions(path: str | Path) -> dict[str, dict]:
    """frame_id -> {description, informative} from a retier_vision.py JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for rec in data.get("describe", []):
        if rec.get("description"):
            out[rec["frame_id"]] = {"description": rec["description"], "informative": rec.get("informative")}
    return out


def build_arms(db, job_id: str, descriptions: dict[str, dict] | None = None) -> tuple[dict, list[dict], list[dict], list[str]]:
    """Return (manifest, chunks_on, chunks_off, annotated_transcript_blocks).

    ``descriptions`` substitutes each frame's description (and informative
    flag) by frame_id; frames absent from the map are dropped from the ON
    arm, so a re-tier run with a failed describe call never silently falls
    back to the stored text.
    """
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
        if descriptions is not None:
            frames = [
                _FrameProxy(f, descriptions[f.frame_id]["description"], descriptions[f.frame_id]["informative"])
                for f in frames if f.frame_id in descriptions
            ]
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
    ap.add_argument("--descriptions", default=None, help="retier_vision.py JSON whose descriptions replace the stored ones in the ON arm")
    ap.add_argument("--env-file", default=str(BACKEND / ".env"), help="read before import; see the module docstring")
    args = ap.parse_args()
    descriptions = load_descriptions(args.descriptions) if args.descriptions else None

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == args.job_id).first()
        if job is None:
            sys.exit(f"job {args.job_id} not found")
        topic = args.topic or job.topic or "untitled"
        manifest, chunks_on, chunks_off, blocks = build_arms(db, args.job_id, descriptions)
        manifest["topic"] = topic
        manifest["descriptions_from"] = args.descriptions
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
        intermediates: dict = {}
        stats, html = run_report_agent(manifest["job_type"], topic, chunks, output_length=manifest["output_length"],
                                       intermediates_out=intermediates)
        if intermediates:
            (out / f"{arm}.intermediates.json").write_text(json.dumps(intermediates, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
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

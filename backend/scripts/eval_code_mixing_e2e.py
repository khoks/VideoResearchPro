"""End-to-end check of N-002 on held-out sources (S-1.16.2, T-1.16.2.6).

Runs the PRODUCTION report map stage (real model) over held-out sources twice:

- "before": chunks stripped of their `code_mix_*` metadata — what every
  chunk looked like before T-1.16.2.5, so no source header names its
  language or quote form;
- "after": chunks as `chunk_transcript` writes them today.

The honest failure mode is Hinglish passed through as English, so the
first metric is how many extracted items still carry non-English text
(Devanagari script, or a measured Hindi share above the borrowing
threshold). The second is whether quotable wording survives: items with
`original`, whether that wording is verbatim from the source, and its script.

Optionally composes the Key Facts section from the "after" items with the
production composer, to see the quote forms on the page.

    ./venv/Scripts/python scripts/eval_code_mixing_e2e.py --env-file ../../backend/.env \\
        --db ../../backend/data/videoresearchpro.db --video QSlta0EnGJo \\
        --comments comments.json:GSA8jvzIjjQ --out e2e.json --compose
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_REDUCE_KEYS = ("facts", "comments", "conclusions", "references", "speakers")


def load_env(env_file: Path) -> None:
    """Provider keys from the .env file; OS-level vars shadow it on the dev box."""
    from dotenv import dotenv_values

    env = dotenv_values(env_file)
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        if env.get(k):
            os.environ[k] = env[k]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text or "")).strip().lower()


def item_metrics(items: list[dict], source_text: str) -> dict:
    from app.config import settings
    from app.services import code_mixing_service as cm
    from app.services import language_service as ls

    src = _norm(source_text)
    passthrough, originals, verbatim, scripts = [], 0, 0, {}
    for it in items:
        content = str(it.get("content") or "")
        p = cm.profile_text(content)
        if ls.needs_translation(content) or p["hi_share"] > settings.CODE_MIX_BORROWING_MAX_SHARE:
            passthrough.append(content[:140])
        orig = str(it.get("original") or "").strip()
        if orig:
            originals += 1
            if _norm(orig) and _norm(orig) in src:
                verbatim += 1
            s = ls.dominant_script(orig) or "none"
            scripts[s] = scripts.get(s, 0) + 1
    return {
        "items": len(items),
        "non_english_items": len(passthrough),
        "non_english_examples": passthrough[:5],
        "items_with_original": originals,
        "originals_verbatim": verbatim,
        "original_scripts": scripts,
    }


def run_map(chunks: list[dict], topic: str) -> list[dict]:
    from app.agents import report_agent

    out = report_agent.map_chunks({"job_type": "topic", "transcript_chunks": chunks, "topic": topic})
    items = []
    for summary in out.get("chunk_summaries") or []:
        if isinstance(summary, dict):
            for k in _REDUCE_KEYS:
                items.extend(i for i in summary.get(k) or [] if isinstance(i, dict))
    return items


def strip_code_mix(chunks: list[dict]) -> list[dict]:
    cs = copy.deepcopy(chunks)
    for c in cs:
        c["metadata"] = {k: v for k, v in c["metadata"].items() if not k.startswith("code_mix")}
    return cs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--video", action="append", default=[], help="transcript_cache video_id")
    ap.add_argument("--comments", action="append", default=[],
                    help="<comments.json>:<video_id> — a comment thread as one document")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--compose", action="store_true",
                    help="compose Key Facts from the first source's 'after' items")
    args = ap.parse_args()
    load_env(args.env_file)

    from app.utils.chunking import chunk_transcript

    sources = []
    db = sqlite3.connect(args.db)
    for vid in args.video:
        segs = json.loads(db.execute(
            "select segments_json from transcript_cache where video_id=?", (vid,)
        ).fetchone()[0])
        title = db.execute("select title from documents where video_id=?", (vid,)).fetchone()[0]
        sources.append((vid, title, segs))
    for spec in args.comments:
        path, vid = spec.rsplit(":", 1)
        comments = json.loads(Path(path).read_text(encoding="utf-8"))[vid]
        segs = [{"text": c, "start": float(i), "duration": 1.0} for i, c in enumerate(comments)]
        sources.append((f"comments-{vid}", f"Viewer comments on {vid}", segs))

    report: dict = {}
    for sid, title, segs in sources:
        chunks = chunk_transcript(segs, video_metadata={
            "video_id": sid, "document_id": f"doc-{sid}", "title": title, "channel_name": "held-out",
            "url": f"https://www.youtube.com/watch?v={sid}",
        })
        source_text = " ".join(s.get("text", "") for s in segs)
        profile = {k: v for k, v in chunks[0]["metadata"].items() if k.startswith("code_mix")}
        entry = {"title": title, "chunks": len(chunks), "profile": profile}
        for cond, cs in (("before", strip_code_mix(chunks)), ("after", chunks)):
            items = run_map(cs, title)
            entry[cond] = item_metrics(items, source_text)
            entry[f"{cond}_items"] = items
            print(sid, cond, {k: v for k, v in entry[cond].items() if k != "non_english_examples"}, flush=True)
        report[sid] = entry
        if args.compose and "composed_key_facts" not in report:
            from app.agents import report_agent

            facts = [i for i in entry["after_items"] if i.get("original")][:12]
            facts += [i for i in entry["after_items"] if not i.get("original")][:8]
            html = report_agent.compose_report({
                "job_type": "topic", "topic": title, "statistics": {"video_count": 1},
                "chunk_summaries": [{"facts": facts}], "transcript_chunks": chunks,
            })["final_html"]
            report["composed_key_facts"] = {"source": sid, "html": html}
            print("composed", len(html), "chars", flush=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

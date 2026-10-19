"""Re-run the two vision use cases on a finished job with a different model and
record real token usage — the S-1.18.5 cost re-measurement for R1.

Describes the job's already-captured frames again (same images, same transcript
windows, same prompt) and re-selects moments on the same transcripts, so the only
variable is the model. Nothing is written back to the database; results go to a
JSON file for comparison and for the image-grounded grading pass.

One candidate per process: the registry is resolved from settings at import, so
the override is placed in the environment before ``app`` is imported, which is
why all app imports live inside ``main``.

Usage (from backend/, inside the venv):
    python scripts/retier_vision.py --job-id <id> --model openai:gpt-5.6-luna:off --out data/r1_ab/retier/luna.json
    python scripts/retier_vision.py --job-id <id> --model openai:gpt-5.5:low --out data/r1_ab/retier/baseline.json --skip-select
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def usage_of(resp) -> dict:
    """Normalised {input_tokens, output_tokens} from a LangChain response.

    Prefers ``usage_metadata`` (set by every provider adapter in use), falls
    back to the raw ``response_metadata`` shapes, and reports zeros rather
    than failing when a provider sends nothing — a zero is visible in the
    totals, a crash would lose the run.
    """
    u = getattr(resp, "usage_metadata", None) or {}
    if not u:
        meta = getattr(resp, "response_metadata", None) or {}
        u = meta.get("token_usage") or meta.get("usage") or {}
    return {
        "input_tokens": int(u.get("input_tokens") or u.get("prompt_tokens") or 0),
        "output_tokens": int(u.get("output_tokens") or u.get("completion_tokens") or 0),
    }


def price_of(model: str, pricing: dict | None = None) -> tuple[float | None, float | None]:
    """(input, output) $ per million tokens from the pricing table, or (None, None)."""
    if pricing is None:
        from app.services.model_pricing import MODEL_PRICING

        pricing = MODEL_PRICING
    p = pricing.get(model)
    if p is None:
        return None, None
    return float(p.input_per_m), float(p.output_per_m)


def selection_overlap(stored: list[float], candidate: list[float], window: float = 20.0) -> int:
    """How many stored timestamps have a candidate moment within ``window`` seconds."""
    return sum(1 for s in stored if any(abs(s - t) <= window for t in candidate))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--model", required=True, help="provider:model:reasoning for BOTH vision use cases")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-select", action="store_true")
    ap.add_argument("--skip-describe", action="store_true")
    ap.add_argument("--limit-frames", type=int, default=0, help="0 = all frames")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sys.path.insert(0, str(BACKEND))

    from dotenv import dotenv_values

    for k, v in (dotenv_values(BACKEND / ".env") or {}).items():
        if v is not None and (k.endswith("_API_KEY") or k.startswith(("LLM_", "VISUAL_"))):
            os.environ[k] = v
    # Highest-precedence knob (CLAUDE.md § LLM configuration); must precede app.config.
    os.environ["LLM_USE_CASE_CONFIG"] = f"visual_select_moments={args.model},visual_describe_frame={args.model}"

    from langchain_core.messages import HumanMessage

    from app.agents import visual_agent as va
    from app.agents.prompts.visual_prompts import SELECT_MOMENTS_PROMPT, describe_frame_prompt
    from app.config import settings
    from app.database import SessionLocal
    from app.models.channel import Channel
    from app.models.document import Document
    from app.models.job_video import JobVideo
    from app.models.visual_frame import VisualFrame
    from app.services.llm_routing import resolve_config
    from app.services.llm_service import get_llm_for, response_text
    from app.services.visual_service import format_timestamp
    from app.tasks.job_tasks import _load_cached_segments

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg_sel = resolve_config("visual_select_moments")
    cfg_desc = resolve_config("visual_describe_frame")
    _log(f"resolved: select={cfg_sel.provider}:{cfg_sel.model}:{cfg_sel.reasoning} describe={cfg_desc.provider}:{cfg_desc.model}:{cfg_desc.reasoning}")
    if cfg_desc.model not in args.model:
        sys.exit("override did not take effect; LLM_USE_CASE_CONFIG must be set before app.config loads")

    db = SessionLocal()
    try:
        links = db.query(JobVideo).filter(JobVideo.job_id == args.job_id, JobVideo.approved.is_(True)).all()
        docs = [d for d in (db.query(Document).filter(Document.document_id == l.document_id).first() for l in links) if d is not None and d.video_id]
        result: dict = {"model": args.model, "job_id": args.job_id, "describe": [], "select": []}

        if not args.skip_describe:
            frames_dir = Path(settings.VISUAL_FRAMES_DIR)
            n_done = 0
            for d in docs:
                cached = _load_cached_segments(d.video_id)
                segments = cached[0] if cached else []
                frames = db.query(VisualFrame).filter(VisualFrame.video_id == d.video_id, VisualFrame.image_path.isnot(None)).order_by(VisualFrame.timestamp_seconds).all()
                for fr in frames:
                    if args.limit_frames and n_done >= args.limit_frames:
                        break
                    path = Path(fr.image_path)
                    if not path.is_absolute():
                        path = frames_dir / path
                    b64 = va._encode_image(str(path))
                    if b64 is None:
                        _log(f"missing image {path}")
                        continue
                    prompt = describe_frame_prompt(
                        video_title=d.title or "Unknown",
                        timestamp_label=format_timestamp(fr.timestamp_seconds),
                        selection_reason=fr.selection_reason or "",
                        expected_content="",
                        transcript_window=va.transcript_window(segments, fr.timestamp_seconds),
                    )
                    msg = HumanMessage(content=[{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}])
                    t0 = time.time()
                    rec = {"frame_id": fr.frame_id, "video_id": d.video_id, "timestamp_seconds": fr.timestamp_seconds, "image_path": str(path), "baseline_description": fr.description, "baseline_informative": fr.informative}
                    try:
                        llm = get_llm_for("visual_describe_frame", temperature=0.0, max_tokens=1_500)
                        resp = llm.invoke([msg])
                        parsed = va._parse_description(response_text(resp)) or {}
                        rec.update({"description": parsed.get("description"), "informative": parsed.get("informative"), "usage": usage_of(resp), "seconds": round(time.time() - t0, 1)})
                    except Exception as e:
                        rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                    result["describe"].append(rec)
                    n_done += 1
                _log(f"{d.video_id}: described {sum(1 for r in result['describe'] if r['video_id'] == d.video_id)} frames")

        if not args.skip_select:
            for d in docs:
                cached = _load_cached_segments(d.video_id)
                if not cached:
                    continue
                segments, _lang = cached
                ch = db.query(Channel).filter(Channel.channel_id == d.channel_id).first() if d.channel_id else None
                prompt = SELECT_MOMENTS_PROMPT.format(
                    video_title=d.title or "Unknown", channel_name=(ch.name if ch else "") or "Unknown",
                    duration_label=format_timestamp(d.duration_seconds) if d.duration_seconds else "unknown",
                    transcript=va._transcript_with_timestamps(segments), max_frames=settings.VISUAL_MAX_FRAMES_PER_VIDEO,
                    min_gap=int(settings.VISUAL_MIN_GAP_SECONDS),
                )
                stored = [fr.timestamp_seconds for fr in db.query(VisualFrame).filter(VisualFrame.video_id == d.video_id).all()]
                rec = {"video_id": d.video_id, "title": d.title, "stored_timestamps": stored}
                t0 = time.time()
                try:
                    llm = get_llm_for("visual_select_moments", temperature=0.0, max_tokens=4_000)
                    resp = llm.invoke([HumanMessage(content=prompt)])
                    moments = va._enforce_spacing_and_cap(va._parse_moments(response_text(resp)), max_frames=settings.VISUAL_MAX_FRAMES_PER_VIDEO, min_gap=settings.VISUAL_MIN_GAP_SECONDS, duration=d.duration_seconds)
                    ts = [float(m.get("timestamp_seconds", m.get("timestamp", 0)) or 0) for m in moments]
                    rec.update({"moments": moments, "candidate_timestamps": ts, "stored_within_20s_of_candidate": selection_overlap(stored, ts), "usage": usage_of(resp), "seconds": round(time.time() - t0, 1)})
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                result["select"].append(rec)
                _log(f"{d.video_id}: selected {len(rec.get('candidate_timestamps', []))} moments; {rec.get('stored_within_20s_of_candidate')}/{len(stored)} stored within 20s")
    finally:
        db.close()

    pin, pout = price_of(cfg_desc.model)
    runs = result["describe"] + result["select"]
    tot_in = sum((r.get("usage") or {}).get("input_tokens", 0) for r in runs)
    tot_out = sum((r.get("usage") or {}).get("output_tokens", 0) for r in runs)
    # Per-video figures divide by the videos that actually produced usage,
    # not by the approved count: an approved video with no transcript has no
    # frames and no selection call, and counting it understated cost by 1/12
    # on the first run.
    n_videos = len({r["video_id"] for r in runs if "usage" in r}) or 1
    cost = (tot_in / 1e6 * pin + tot_out / 1e6 * pout) if pin is not None else None
    described = [r for r in result["describe"] if "usage" in r]
    result["totals"] = {
        "videos": len(docs), "frames_described": len(described),
        "describe_errors": sum(1 for r in result["describe"] if "error" in r),
        "input_tokens": tot_in, "output_tokens": tot_out,
        "price_per_m": {"input": pin, "output": pout},
        "cost_usd": round(cost, 4) if cost is not None else None,
        "cost_per_video_usd": round(cost / n_videos, 4) if cost is not None else None,
        "informative_rate": (sum(1 for r in described if r.get("informative")) / len(described)) if described else None,
        "selection_overlap": (sum(r.get("stored_within_20s_of_candidate", 0) for r in result["select"]) / max(1, sum(len(r["stored_timestamps"]) for r in result["select"]))) if result["select"] else None,
    }
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    _log(f"wrote {out}: {json.dumps(result['totals'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

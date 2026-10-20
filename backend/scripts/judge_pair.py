"""Blind pairwise judging of two report artifacts — the E-1.14 method as a
reusable script (D-055: coin-flipped labels, several judge families, claims
checked against the corpus, decision rule fixed before the run).

Each judge gets the two reports under labels A/B chosen by an independent coin
flip, plus the transcript to verify against. Scores are unblinded only in the
summary. First used for S-1.18.3 (visual on vs off); intended for T-7.1.1.5
(trust weights) and S-1.16.2 (code-mixing) next.

Usage (from backend/, inside the venv):
    python scripts/judge_pair.py --x on.html --y off.html --labels on,off \
        --transcript transcript_annotated.txt --out ./judging \
        --judges openai:gpt-5.5:medium,anthropic:claude-sonnet-5:medium,google:gemini-3.1-pro:medium

    # S-6.1.3: two editions of a book (no corpus: the chapters are in both)
    python scripts/judge_pair.py --rubric book --x full.md --y none.md --labels full,none \
        --out ./judging/book1 --env-file ../../backend/.env

``--env-file`` names the .env whose API keys and LLM_* settings to use (default
backend/.env beside this script). Keys are read from the file, never from the
process environment, because machine-wide variables can shadow it.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from dotenv import dotenv_values  # noqa: E402


def _env_file_from_argv(argv: list[str]) -> Path:
    """``--env-file`` read before the app is imported: settings are built at
    import time, so keys loaded afterwards would be ignored."""
    for i, arg in enumerate(argv):
        if arg == "--env-file" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--env-file="):
            return Path(arg.split("=", 1)[1])
    return BACKEND / ".env"


for _k, _v in (dotenv_values(_env_file_from_argv(sys.argv)) or {}).items():
    if _v is not None and (_k.endswith("_API_KEY") or _k.startswith("LLM_")):
        os.environ[_k] = _v

from app.services.llm_routing import UseCaseConfig  # noqa: E402
from app.services.llm_service import _build_from_config, response_text  # noqa: E402

# Judging a truncated document was the S-1.14.15 mistake; refuse by default.
DEFAULT_MAX_CHARS = 600_000

RUBRIC = """You are one of several independent judges comparing two research reports, labelled A and B, generated from the same set of video transcripts. You do not know how either was produced. Judge the TEXT, not the length: assume the longer report may be padded until its extra material proves specific and verifiable.

The transcript below is the corpus. Spans written as [VISUAL @ mm:ss — ...] are machine descriptions of what was ON SCREEN at that moment; they were never spoken. A report may legitimately use them as visual evidence ("the chart shown at 12:40 ...") but must not attribute them to the speaker as something said.

Score each report 1-10 on:
1. substance — density of specific, checkable claims per 100 words (numbers, named tools, concrete steps), verified against the transcript.
2. visual_use — correct use of information that could only come from the screen, attributed as shown rather than said. A report with no visual claims scores 5 (neutral), not 1.

Then list, for each report:
- attribution_errors: every place screen content is presented as speech or speech as screen content. Quote the sentence.
- fabrications: claims that appear in neither the speech nor the visual spans. Quote the sentence.

Finally state preferred_on_substance: "A", "B" or "tie" — which report a researcher would learn more verified facts from per minute of reading.

Return ONLY a JSON object with keys: substance_A, substance_B, visual_use_A, visual_use_B, attribution_errors_A (list of strings), attribution_errors_B (list), fabrications_A (list), fabrications_B (list), preferred_on_substance, rationale (<= 120 words).
"""


BOOK_RUBRIC = """You are one of several independent judges comparing two editions of the same book, labelled A and B. Both are assembled from the same research reports, one report per chapter, and the chapter texts are the same in both, although their order and numbering may differ. One edition may add framing written by an editor: an introduction, short bridge paragraphs before chapters, parts, a conclusion, a glossary. You do not know how either edition was produced. Judge the BOOK as a reader would, not its length: framing earns credit only where it helps the reader.

Spans written as [VISUAL @ mm:ss — ...] inside chapters are machine descriptions of what was on screen in a source video; they are part of the chapters in both editions.

Score each edition 1-10 on:
1. cohesion — does it read as one book with a purpose and a path, rather than a stack of separate reports?
2. orientation — how well a newcomer is oriented: what the book covers, why this order, what each chapter adds, the key terms.
3. accuracy_of_framing — every statement in framing text (anything that is not a chapter's own report text) is supported by the chapters. An edition with no framing scores 10.

Then list, for each edition:
- unsupported_claims: every sentence of framing text that states something the chapters do not support. Quote it.
- misframings: framing that misrepresents a chapter (a wrong summary, wrong emphasis, or an invented connection presented as fact). Quote it.

Finally state preferred_overall: "A", "B" or "tie" — which edition you would hand a reader who wants to learn this subject.

Return ONLY a JSON object with keys: cohesion_A, cohesion_B, orientation_A, orientation_B, accuracy_of_framing_A, accuracy_of_framing_B, unsupported_claims_A (list of strings), unsupported_claims_B (list), misframings_A (list), misframings_B (list), preferred_overall, rationale (<= 120 words).
"""


# What each rubric scores, lists and prefers; the unblinding and the summary
# are driven by this, so a new rubric cannot forget to unblind a field.
RUBRICS: dict[str, dict] = {
    "report": {
        "text": RUBRIC,
        "doc": "REPORT",
        "scores": ("substance", "visual_use"),
        "lists": ("attribution_errors", "fabrications"),
        "preference": "preferred_on_substance",
        "needs_corpus": True,
    },
    "book": {
        "text": BOOK_RUBRIC,
        "doc": "EDITION",
        "scores": ("cohesion", "orientation", "accuracy_of_framing"),
        "lists": ("unsupported_claims", "misframings"),
        "preference": "preferred_overall",
        "needs_corpus": False,
    },
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_judge_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in judge output")
    return json.loads(raw[start:end + 1])


def unblind(parsed: dict, a_name: str, b_name: str, rubric: str = "report") -> dict:
    """Map a judge's A/B answers back to the real arm names."""
    spec = RUBRICS[rubric]

    def by_name(key_prefix: str) -> dict:
        return {a_name: parsed.get(f"{key_prefix}_A"), b_name: parsed.get(f"{key_prefix}_B")}

    out = {key: by_name(key) for key in (*spec["scores"], *spec["lists"])}
    pref = parsed.get(spec["preference"])
    out[spec["preference"]] = {"A": a_name, "B": b_name}.get(pref, "tie")
    return out


def summarise(results: list[dict], name_x: str, name_y: str, rubric: str = "report") -> dict:
    """Totals over every judge that returned a verdict, by real arm name."""
    spec = RUBRICS[rubric]
    ok = [r for r in results if "unblinded" in r]
    prefs = [r["unblinded"][spec["preference"]] for r in ok]
    arms = (name_x, name_y)

    def mean(key: str, arm: str):
        values = [r["unblinded"][key].get(arm) for r in ok]
        values = [v for v in values if isinstance(v, (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    summary = {
        "rubric": rubric,
        "judges_ok": len(ok),
        "judges_total": len(results),
        spec["preference"]: {n: prefs.count(n) for n in (*arms, "tie")},
        "totals": {key: {n: sum(len(r["unblinded"][key].get(n) or []) for r in ok) for n in arms} for key in spec["lists"]},
        "means": {key: {n: mean(key, n) for n in arms} for key in spec["scores"]},
    }
    if rubric == "report":  # the keys earlier runs were read with
        summary["attribution_errors_total"] = summary["totals"]["attribution_errors"]
        summary["fabrications_total"] = summary["totals"]["fabrications"]
        summary["mean_substance"] = {n: (mean("substance", n) or 0) if ok else None for n in arms}
    return summary


def _cfg(spec: str) -> UseCaseConfig:
    parts = spec.split(":")
    if len(parts) == 2:
        parts.append("medium")
    if len(parts) != 3:
        raise SystemExit(f"bad judge spec {spec!r}; want provider:model[:reasoning]")
    return UseCaseConfig(parts[0], parts[1], parts[2])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--x", required=True, help="first artifact (HTML or text)")
    ap.add_argument("--y", required=True, help="second artifact (HTML or text)")
    ap.add_argument("--labels", default="x,y", help="real names of --x and --y, e.g. on,off (used only when unblinding)")
    ap.add_argument("--transcript", help="the corpus to verify against (required by the report rubric)")
    ap.add_argument("--rubric", choices=sorted(RUBRICS), default="report")
    ap.add_argument("--env-file", default=str(BACKEND / ".env"), help="read before import; see the module docstring")
    ap.add_argument("--out", required=True)
    ap.add_argument("--judges", default="openai:gpt-5.5:medium,anthropic:claude-sonnet-5:medium,google:gemini-3.1-pro:medium")
    ap.add_argument("--max-tokens", type=int, default=16_000, help="completion budget; reasoning tokens count toward it on OpenAI")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument("--allow-truncate", action="store_true")
    ap.add_argument("--seed", type=int, default=None, help="only for reproducing a run; omit for a fresh coin")
    args = ap.parse_args()

    spec = RUBRICS[args.rubric]
    if spec["needs_corpus"] and not args.transcript:
        raise SystemExit(f"--transcript is required for the {args.rubric} rubric")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name_x, name_y = [s.strip() for s in args.labels.split(",")]

    def load(p: str) -> str:
        raw = Path(p).read_text(encoding="utf-8", errors="replace")
        return html_to_text(raw) if "<html" in raw[:2000].lower() or "<body" in raw[:5000].lower() else raw

    text_x, text_y = load(args.x), load(args.y)
    transcript = Path(args.transcript).read_text(encoding="utf-8", errors="replace") if args.transcript else ""
    total = len(text_x) + len(text_y) + len(transcript)
    if total > args.max_chars:
        msg = f"inputs total {total:,} chars > {args.max_chars:,}"
        if not args.allow_truncate:
            raise SystemExit(msg + "; refusing to judge a truncated document (pass --allow-truncate to override)")
        print("WARNING:", msg, "— truncating transcript", flush=True)
        transcript = transcript[: max(0, args.max_chars - len(text_x) - len(text_y))]

    rng = random.Random(args.seed if args.seed is not None else int.from_bytes(os.urandom(8), "big"))
    results = []
    for judge in [s.strip() for s in args.judges.split(",") if s.strip()]:
        cfg = _cfg(judge)
        flip = rng.random() < 0.5
        a_name, b_name = (name_y, name_x) if flip else (name_x, name_y)
        text_a, text_b = (text_y, text_x) if flip else (text_x, text_y)
        doc = spec["doc"]
        prompt = (
            spec["text"]
            + f"\n\n===== {doc} A =====\n" + text_a
            + f"\n\n===== {doc} B =====\n" + text_b
            + ("\n\n===== TRANSCRIPT (corpus) =====\n" + transcript if transcript else "")
        )
        t0 = time.time()
        rec: dict = {"judge": judge, "rubric": args.rubric, "mapping": {"A": a_name, "B": b_name}}
        try:
            # Temperature 1.0 throughout: Anthropic rejects anything else with thinking on,
            # and reasoning models are not deterministic at 0 either. Built inside the
            # try so a missing provider SDK costs one judge, not the run.
            llm = _build_from_config(cfg, temperature=1.0, max_tokens=args.max_tokens)
            raw = response_text(llm.invoke(prompt))
            rec["seconds"] = round(time.time() - t0, 1)
            rec["raw"] = raw
            parsed = parse_judge_json(raw)
            rec["parsed"] = parsed
            rec["unblinded"] = unblind(parsed, a_name, b_name, args.rubric)
            print(f"{judge}: prefers {rec['unblinded'][spec['preference']]} "
                  f"({spec['scores'][0]} {rec['unblinded'][spec['scores'][0]]}, {rec['seconds']}s)", flush=True)
        except Exception as e:  # keep the other judges running
            rec["error"] = f"{type(e).__name__}: {e}"
            print(f"{judge}: ERROR {rec['error'][:200]}", flush=True)
        results.append(rec)
        (out / f"judge_{re.sub(r'[^a-z0-9]+', '_', judge.lower())}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

    # Aggregate over every judge file in --out, so a judge re-run on its own
    # (after a crash or a missing SDK) joins the earlier verdicts.
    results = []
    for f in sorted(out.glob("judge_*.json")):
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"skipping unreadable {f.name}: {e}", flush=True)
    ok = [r for r in results if "unblinded" in r]
    summary = summarise(results, name_x, name_y, args.rubric)
    summary["inputs"] = {"x": args.x, "y": args.y, "labels": [name_x, name_y], "chars": total}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

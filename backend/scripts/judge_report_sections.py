"""Split a report into sections for judging, with no document-level cap.

T-1.14.15.4. The E-1.14 judging harness normalised each report to plain
text and capped it at 180,000 characters so neither side of a blind pair
could win on length. Production reports outgrew that cap (S-1.14.8 made
length scale with the corpus), so the last rounds judged a truncated
document. This script replaces the cap with SECTION-BY-SECTION judging:
each <h2> section is rendered to text on its own, so a judge reads every
section in full and nothing is silently cut.

Usage (prepare only — writes one text file per section plus a manifest):

    ./venv/Scripts/python scripts/judge_report_sections.py report.html --out judged/

Usage (prepare + judge each section with a model of your choice):

    ./venv/Scripts/python scripts/judge_report_sections.py report.html \\
        --out judged/ --judge --provider anthropic --model claude-sonnet-5 \\
        --lens coverage

Two reports can be judged with the same lens and compared section by
section afterwards. Orientation blinding (which report is which) is the
caller's job, as in the original harness: pass the two files under
coin-flipped names.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)

LENSES = {
    "coverage": (
        "Judge COVERAGE and BREADTH: how much of the corpus's material this "
        "section represents, whether specific figures, names and versions are "
        "preserved, and whether whole debates or sources appear to be missing."
    ),
    "rigour": (
        "Judge FACTUAL RIGOUR: are claims attributed and dated, are time-"
        "sensitive claims written 'as of' their source's date, does the section "
        "contradict the report's own verified figures, and are any claims "
        "unsupported by a cited source?"
    ),
    "synthesis": (
        "Judge SYNTHESIS and INSIGHT: does the section explain mechanism and "
        "trajectory rather than enumerate sources, does it surface tensions "
        "between sources and say which claims are superseded, and would a "
        "reader learn something the sources do not say individually?"
    ),
}


def split_sections(html: str) -> list[tuple[str, str]]:
    """[(title, plain_text)] for every <h2> section. No length cap."""
    html = _SCRIPT_STYLE.sub("", html)
    marks = list(_H2.finditer(html))
    if not marks:
        return [("Document", _normalise(_TAG.sub(" ", html)))]
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        title = _normalise(_TAG.sub("", m.group(1))) or f"Section {i + 1}"
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        body = html[m.end():end]
        sections.append((title, _normalise(_TAG.sub(" ", body))))
    return sections


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _safe_name(title: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "section"
    return f"{index:02d}-{slug}.txt"


def judge_section(title: str, text: str, lens: str, provider: str, model: str, reasoning: str) -> str:
    from langchain_core.messages import HumanMessage

    from app.services.llm_routing import UseCaseConfig
    from app.services.llm_service import _build_from_config, response_text

    cfg = UseCaseConfig(provider=provider, model=model, reasoning=reasoning)  # type: ignore[arg-type]
    llm = _build_from_config(cfg, temperature=0.0, max_tokens=2_000)
    prompt = (
        f"You are judging ONE section of a research report. Section: {title}\n\n"
        f"{LENSES[lens]}\n\n"
        "Score 1-10 and justify in at most 150 words, citing specific passages. "
        "Then list up to five concrete defects, each as one line.\n\n"
        f"=== SECTION TEXT ({len(text):,} characters, complete, not truncated) ===\n{text}"
    )
    return response_text(llm.invoke([HumanMessage(content=prompt)]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path, help="HTML report to split")
    ap.add_argument("--out", type=Path, required=True, help="directory for per-section text + manifest")
    ap.add_argument("--judge", action="store_true", help="also call a judge model per section")
    ap.add_argument("--lens", choices=sorted(LENSES), default="rigour")
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--reasoning", default="medium")
    args = ap.parse_args()

    html = args.report.read_text(encoding="utf-8")
    sections = split_sections(html)
    args.out.mkdir(parents=True, exist_ok=True)

    manifest = []
    for i, (title, text) in enumerate(sections, 1):
        name = _safe_name(title, i)
        (args.out / name).write_text(text, encoding="utf-8")
        entry = {"index": i, "title": title, "file": name, "chars": len(text), "words": len(text.split())}
        if args.judge:
            verdict = judge_section(title, text, args.lens, args.provider, args.model, args.reasoning)
            (args.out / name.replace(".txt", f".{args.lens}.judge.md")).write_text(verdict, encoding="utf-8")
            entry["judged_with"] = f"{args.provider}:{args.model}:{args.reasoning}"
            entry["lens"] = args.lens
        manifest.append(entry)
        print(f"[{i:02d}] {title}: {entry['chars']:,} chars, {entry['words']:,} words")

    total = sum(e["chars"] for e in manifest)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{len(manifest)} sections, {total:,} characters in total — none truncated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Check and repair cross-doc anchor links against GitHub's heading slugs — E-4.8 / T-4.8.5.

GitHub's slugger (github-slugger) lowercases the heading, drops every
character that is not a letter, number, mark, space, hyphen or underscore,
and then turns EACH space into a hyphen. It never collapses runs of hyphens
and never strips a trailing one. So:

    "D-063 — Per-user isolation"        -> d-063--per-user-isolation
    "E-5.10 🟡 Per-user isolation (R2)" -> e-510--per-user-isolation-r2
    "L4 — Curated source ranking ⚪"     -> l4--curated-source-ranking-
    "D-001 — Rebrand to Pratidhvani (प्रतिध्वनि)" keeps the Devanagari

The first version of this script (PR #179, 2026-05-06) assumed the opposite
and rewrote `--` to `-` in 132 links, which broke them. Verified 2026-10-18
against the rendered HTML of docs/initiatives.md and docs/decisions.md
(contents API, `html` media type: id="user-content-…").

Usage (from backend/, inside the venv):
    python scripts/fix_anchor_links.py --check   # report only, exit 1 if any link is broken
    python scripts/fix_anchor_links.py           # rewrite links whose heading can be identified

A broken anchor is repaired only when exactly one heading in the target doc
matches it once hyphen runs and trailing hyphens are ignored on both sides;
anything else is reported, not guessed.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import unicodedata

DOCS = [
    "docs/decisions.md",
    "docs/initiatives.md",
    "docs/feature-roadmap.md",
    "docs/saas-roadmap.md",
    "docs/branding.md",
    "docs/architecture.md",
    "docs/source-types.md",
    "docs/personal-brain.md",
    "docs/vision.md",
    "docs/inventions.md",
]
LINK_SOURCES = DOCS + ["CHANGELOG.md", "README.md", "CLAUDE.md"]

_TARGETS = "|".join(pathlib.Path(d).stem for d in DOCS)
LINK_RE = re.compile(r"\((?:docs/)?(" + _TARGETS + r")\.md#([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def github_slug(heading: str) -> str:
    """Reproduce github-slugger for a heading's text."""
    out = []
    for ch in heading.lower():
        if ch == " ":
            out.append("-")
        elif ch in "-_" or unicodedata.category(ch)[0] in ("L", "N", "M"):
            out.append(ch)
    return "".join(out)


def _loose(slug: str) -> str:
    """Comparison key that ignores the two things the old script got wrong."""
    return re.sub(r"-+", "-", slug).strip("-")


def heading_slugs(text: str) -> set[str]:
    return {github_slug(h) for h in HEADING_RE.findall(text)}


def repair_anchor(anchor: str, valid: set[str]) -> str | None:
    """Return the one valid slug that matches ``anchor`` loosely, else None."""
    if anchor in valid:
        return anchor
    key = _loose(anchor)
    matches = sorted(s for s in valid if _loose(s) == key)
    return matches[0] if len(matches) == 1 else None


def run(root: pathlib.Path, check: bool = False, out=None) -> tuple[int, int]:
    """Walk the docs under ``root``. Returns (rewrites, still_broken)."""
    out = out or sys.stdout  # resolved per call so pytest's capture sees it
    anchors_by_doc: dict[str, set[str]] = {}
    for d in DOCS:
        p = root / d
        if p.exists():
            anchors_by_doc[pathlib.Path(d).stem] = heading_slugs(p.read_text(encoding="utf-8"))

    rewrites = 0
    broken: list[str] = []
    per_file: dict[str, int] = {}
    for d in LINK_SOURCES:
        p = root / d
        if not p.exists():
            continue
        original = p.read_text(encoding="utf-8")
        count = 0

        def fix(m: re.Match) -> str:
            nonlocal count
            target, anchor = m.group(1), m.group(2)
            valid = anchors_by_doc.get(target, set())
            repaired = repair_anchor(anchor, valid)
            if repaired is None:
                broken.append(f"{d}: {target}.md#{anchor}")
                return m.group(0)
            if repaired != anchor:
                count += 1
                return m.group(0).replace(f"#{anchor})", f"#{repaired})")
            return m.group(0)

        new_text = LINK_RE.sub(fix, original)
        if count:
            per_file[d] = count
            rewrites += count
            if not check:
                p.write_text(new_text, encoding="utf-8")

    verb = "would rewrite" if check else "rewrote"
    print(f"{verb} {rewrites} link(s)", file=out)
    for f in sorted(per_file):
        print(f"  {per_file[f]:>4}  {f}", file=out)
    print(f"unrepairable: {len(broken)}", file=out)
    for b in broken:
        print(f"  {b}", file=out)
    return rewrites, len(broken)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--report", action="store_true", dest="check",
                    help="report only; write nothing; exit 1 if any link would change or cannot be repaired")
    ap.add_argument("--root", default=None, help="repository root (default: two levels above this script)")
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve() if args.root else pathlib.Path(__file__).resolve().parent.parent.parent
    rewrites, broken = run(root, check=args.check)
    if args.check:
        return 1 if (rewrites or broken) else 0
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())

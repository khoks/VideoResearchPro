"""One-shot script to batch-fix cross-doc anchor links — E-4.8.

121 cross-doc anchor links use `--` (double hyphen) where GitHub's
slugifier produces `-` (single hyphen). Pattern: when a heading
contains ` — ` (em-dash with surrounding spaces), GitHub strips the
em-dash entirely and collapses whitespace to a single dash; the docs
in this repo write `--` for the same gap, which renders as broken on
github.com.

This script walks every cross-doc link in a fixed set of docs and,
when the anchor doesn't resolve against the target doc's headings
under GitHub's slug rule, tries collapsing `-+ → -` and re-checks. If
the candidate matches a real heading, we rewrite the link.

Idempotent — re-running on already-fixed docs is a no-op.

Usage:
    cd backend
    ./venv/Scripts/python scripts/fix_anchor_links.py
"""
from __future__ import annotations

import os
import pathlib
import re
import sys


def github_slug(heading: str) -> str:
    """Reproduce GitHub's heading slug generation. Close-enough for our
    docs — drop emoji + Unicode, lowercase, dashes only."""
    s = heading.lower()
    # Drop everything except ASCII letters/digits/spaces/dashes.
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    os.chdir(repo_root)

    # Build slug index: target_doc → set of valid anchors.
    docs_to_scan = [
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
    target_anchors: dict[str, set[str]] = {}
    for d in docs_to_scan:
        p = pathlib.Path(d)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        anchors = set()
        for h in re.findall(r"^#+\s+(.+)$", text, flags=re.MULTILINE):
            anchors.add(github_slug(h))
        target_anchors[d] = anchors

    # Walk every doc that has links + try to fix.
    docs_to_edit = [
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
        "CHANGELOG.md",
        "README.md",
        "CLAUDE.md",
    ]
    edits_total = 0
    edits_per_file: dict[str, int] = {}

    pattern = re.compile(
        r"\((decisions|initiatives|feature-roadmap|saas-roadmap|branding|architecture|source-types|personal-brain|vision|inventions)\.md#([a-z0-9-]+)\)"
    )

    for d in docs_to_edit:
        p = pathlib.Path(d)
        if not p.exists():
            continue
        original = p.read_text(encoding="utf-8")
        local_edits = [0]  # cell for closure mutation

        def fix_link(m: re.Match) -> str:
            target = m.group(1)
            anchor = m.group(2)
            target_doc = f"docs/{target}.md"
            valid = target_anchors.get(target_doc, set())
            if anchor in valid:
                return m.group(0)
            # Try the collapsed candidate.
            candidate = re.sub(r"-+", "-", anchor).strip("-")
            if candidate in valid and candidate != anchor:
                local_edits[0] += 1
                return f"({target}.md#{candidate})"
            return m.group(0)

        new_text = pattern.sub(fix_link, original)
        if new_text != original:
            p.write_text(new_text, encoding="utf-8")
            edits_per_file[d] = local_edits[0]
            edits_total += local_edits[0]

    print(f"Total link rewrites: {edits_total}")
    for f in sorted(edits_per_file):
        print(f"  {edits_per_file[f]:>4}  {f}")

    # Final sanity check: count any still-broken cross-doc anchors.
    still_broken = 0
    for d in docs_to_edit:
        p = pathlib.Path(d)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            target = m.group(1)
            anchor = m.group(2)
            target_doc = f"docs/{target}.md"
            valid = target_anchors.get(target_doc, set())
            if anchor not in valid:
                still_broken += 1

    print(f"Still-broken after rewrite: {still_broken}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

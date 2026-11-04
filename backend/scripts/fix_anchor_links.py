"""Check and repair Markdown anchor links against GitHub's heading ids (E-4.8 / T-4.8.5).

GitHub lowercases a heading's rendered text, drops every character that is not
a letter, digit, mark, space, hyphen or underscore, and then turns EACH space
into a hyphen. It never collapses runs of hyphens and never strips a trailing
one. A repeated heading gets `-1`, `-2` and so on. So:

    "D-063 — Per-user isolation"        -> d-063--per-user-isolation
    "E-5.10 🟡 Per-user isolation (R2)" -> e-510--per-user-isolation-r2
    "L4 — Curated source ranking ⚪"     -> l4--curated-source-ranking-
    "D-001 — Rebrand to Pratidhvani (प्रतिध्वनि)" keeps the Devanagari

The first version of this script (PR #179, 2026-05-06) assumed the opposite
and rewrote `--` to `-` in 132 links, which broke them. The rules here were
verified against GitHub's rendered HTML (contents API, `html` media type:
id="user-content-…"), most recently on 2026-11-04 for every doc in the repo.

Every Markdown file in the repository is scanned, and every inline or
reference link with a fragment: `other.md#x`, `../CLAUDE.md#x`, and `#x` within
the same file. Code blocks, code spans and HTML comments are not links.

Headings are read in document order, because the `-1` numbering runs across all
of them: ATX (`## x`), setext (`x` over `===` or `---`), and either inside a
blockquote. Front matter is not one. Two forms GitHub also gives ids to are NOT
read, and a good link to one fails --check as unrepairable: a heading inside a
list item (`- ## x`), and raw HTML (`<h2>x</h2>`). Each also shifts the
numbering of a later repeat of its text. No doc uses either.

Usage (from backend/, stdlib only, no venv needed):
    python scripts/fix_anchor_links.py            # dry run: say what --write would do
    python scripts/fix_anchor_links.py --check    # same, and exit 1 on any bad link (CI)
    python scripts/fix_anchor_links.py --write    # rewrite the links that can be repaired

A broken anchor is repaired only when exactly one heading in the target doc
matches it once hyphen runs and trailing hyphens are ignored on both sides;
anything else is reported, not guessed.
"""
from __future__ import annotations

import argparse
import dataclasses
import html
import itertools
import os
import pathlib
import re
import sys
import unicodedata
import urllib.parse
from collections.abc import Iterator

# Directories that hold no docs of ours: dependencies, build output, runtime
# data, test fixtures, and .claude, whose worktrees are whole copies of this
# repository.
SKIP_DIRS = {
    ".claude", ".git", ".pytest_cache", ".ruff_cache", ".venv", "__fixtures__",
    "__pycache__", "data", "dist", "fixtures", "node_modules", "test-results",
    "venv",
}

FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r" {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
SETEXT_RE = re.compile(r" {0,3}(?:=+|-+)[ \t]*$")
RULE_RE = re.compile(r" {0,3}(?:[-*_][ \t]*){3,}$")
# A list item, a table row or an HTML block: an underline after one is a rule.
NO_SETEXT_RE = re.compile(r" {0,3}(?:[-*+][ \t]|\d{1,9}[.)][ \t]|\||<)")
QUOTE_RE = re.compile(r" {0,3}> ?")
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(?:.*?\r?\n)??---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
# <a name="x"> and <a id="x"> are link targets on GitHub too.
HTML_ANCHOR_RE = re.compile(r"<a\s[^>]*?\b(?:id|name)=[\"']([^\"']+)[\"']", re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
CODE_SPAN_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# ](target#anchor) with an optional title, or a [ref]: target#anchor definition.
LINK_RE = re.compile(
    r"\]\(\s*<?(?P<path>[^()\s<>#]*)#(?P<anchor>[^()\s<>]+)>?(?:\s+\"[^\"]*\")?\s*\)"
    r"|^ {0,3}\[[^\]]+\]:\s+<?(?P<ref_path>[^()\s<>#]*)#(?P<ref_anchor>[^()\s<>]+)>?",
    re.MULTILINE,
)
URL_SCHEME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
_IMAGE_OR_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)|!?\[([^\]]*)\]\[[^\]]*\]")
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_EMPHASIS_RE = re.compile(r"(\*{1,3}|~~)(?=\S)(.+?)(?<=\S)\1|(?<![^\W_])_{1,3}(?=\S)(.+?)(?<=\S)_{1,3}(?![^\W_])")


@dataclasses.dataclass(frozen=True)
class BadLink:
    source: str          # repo-relative file holding the link
    line: int
    target: str          # repo-relative file it points at
    anchor: str
    repaired: str | None  # the real slug, when exactly one heading matches
    start: int = 0       # offsets of the anchor text inside the source file
    end: int = 0

    def __str__(self) -> str:
        where = f"{self.source}:{self.line}: {self.target}#{self.anchor}"
        return f"{where} -> #{self.repaired}" if self.repaired else where


@dataclasses.dataclass
class Report:
    files: int = 0
    links: int = 0
    repairable: list[BadLink] = dataclasses.field(default_factory=list)
    broken: list[BadLink] = dataclasses.field(default_factory=list)

    @property
    def bad(self) -> int:
        return len(self.repairable) + len(self.broken)


def github_slug(heading: str) -> str:
    """Slug of a heading's text, before any `-1` suffix for a repeated heading."""
    out = []
    for ch in heading.lower():
        if ch == " ":
            out.append("-")
        elif ch in "-_" or unicodedata.category(ch)[0] in ("L", "N", "M"):
            out.append(ch)
    return "".join(out)


def _rendered_text(markdown: str) -> str:
    """A heading's text as GitHub renders it: inline Markdown gone, code kept."""
    markdown = _IMAGE_OR_LINK_RE.sub(lambda m: m.group(1) or m.group(2) or "", markdown)
    parts = []
    pos = 0
    for m in CODE_SPAN_RE.finditer(markdown):
        parts.append(_strip_inline(markdown[pos:m.start()]))
        parts.append(m.group(2).strip())
        pos = m.end()
    parts.append(_strip_inline(markdown[pos:]))
    return "".join(parts)


def _strip_inline(text: str) -> str:
    text = _TAG_RE.sub("", text)
    previous = None
    while text != previous:  # emphasis nests: **_x_**
        previous = text
        text = _EMPHASIS_RE.sub(lambda m: m.group(2) or m.group(3) or "", text)
    return html.unescape(re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", text))


def _spaces(text: str) -> str:
    """Spaces in place of text, line breaks kept, so offsets and line numbers survive."""
    return re.sub(r"[^\r\n]", " ", text)


def mask_fences(text: str) -> str:
    """The text with HTML comments and fenced code blocks blanked, same length."""
    lines = COMMENT_RE.sub(lambda m: _spaces(m.group(0)), text).split("\n")
    fence: str | None = None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                lines[i] = _spaces(line)
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not line[m.end():].strip():
                fence = None
            lines[i] = _spaces(line)
    return "\n".join(lines)


def _heading_texts(masked: str) -> Iterator[str]:
    """Each heading's inline Markdown in document order, blockquotes included."""
    for quoted, run in itertools.groupby(masked.split("\n"), key=lambda line: bool(QUOTE_RE.match(line))):
        lines = [line.rstrip("\r") for line in run]
        if quoted:
            # One quote at a time: a code block opened in a quote ends with it,
            # and an underline belongs to the paragraph of its own quote.
            yield from _heading_texts(mask_fences("\n".join(QUOTE_RE.sub("", line, count=1) for line in lines)))
            continue
        paragraph: list[str] = []
        closed = False  # in a block that an underline cannot turn into a heading
        for line in lines:
            if not line.strip():
                paragraph, closed = [], False
            elif m := HEADING_RE.match(line):
                paragraph = []
                yield m.group(1)
            elif paragraph and SETEXT_RE.match(line):
                yield "\n".join(paragraph)  # GitHub drops the break: no hyphen
                paragraph = []
            elif RULE_RE.match(line):
                paragraph, closed = [], False
            elif NO_SETEXT_RE.match(line):
                paragraph, closed = [], True
            elif not closed and (paragraph or not line.startswith("    ")):
                paragraph.append(line.strip())


def heading_slugs(text: str) -> set[str]:
    """Every anchor a Markdown file offers, as GitHub numbers them."""
    masked = mask_fences(FRONT_MATTER_RE.sub(lambda m: _spaces(m.group(0)), text, count=1))
    seen: dict[str, int] = {}
    slugs: set[str] = set()
    for heading in _heading_texts(masked):
        base = slug = github_slug(_rendered_text(heading))
        while slug in seen:
            seen[base] += 1
            slug = f"{base}-{seen[base]}"
        seen[slug] = 0
        slugs.add(slug)
    slugs.update(HTML_ANCHOR_RE.findall(masked))
    return slugs


def _loose(slug: str) -> str:
    """Comparison key that ignores the two things the old script got wrong."""
    return re.sub(r"-+", "-", slug).strip("-")


def repair_anchor(anchor: str, valid: set[str]) -> str | None:
    """Return the one valid slug that matches ``anchor`` loosely, else None."""
    if anchor in valid:
        return anchor
    key = _loose(anchor)
    matches = sorted(s for s in valid if _loose(s) == key)
    return matches[0] if len(matches) == 1 else None


def markdown_files(root: pathlib.Path) -> list[pathlib.Path]:
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found.extend(pathlib.Path(folder) / f for f in files if f.lower().endswith(".md"))
    return sorted(found)


def _read(path: pathlib.Path) -> str:
    # newline="" keeps CRLF, so --write changes only the anchors.
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: pathlib.Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def scan(root: pathlib.Path, skip_sources: tuple[str, ...] = ()) -> Report:
    """Find every bad anchor link under ``root``. Reads only.

    Links IN a ``skip_sources`` file are left out. Links TO it are still checked.
    """
    root = root.resolve()
    report = Report()
    anchors: dict[pathlib.Path, set[str]] = {}

    def anchors_of(path: pathlib.Path) -> set[str]:
        if path not in anchors:
            anchors[path] = heading_slugs(_read(path))
        return anchors[path]

    for source in markdown_files(root):
        if _relative(source, root) in skip_sources:
            continue
        report.files += 1
        text = _read(source)
        masked = CODE_SPAN_RE.sub(lambda m: _spaces(m.group(0)), mask_fences(text))
        for m in LINK_RE.finditer(masked):
            group = "anchor" if m.group("anchor") is not None else "ref_anchor"
            raw_path = m.group("path") if group == "anchor" else m.group("ref_path")
            raw_anchor = m.group(group)
            if raw_path and (URL_SCHEME_RE.match(raw_path) or not raw_path.lower().endswith(".md")):
                continue  # a web address, or a file with no headings to check
            report.links += 1
            anchor = urllib.parse.unquote(raw_anchor)
            target = source if not raw_path else (source.parent / urllib.parse.unquote(raw_path)).resolve()
            line = text.count("\n", 0, m.start()) + 1
            try:
                target_name = _relative(target, root)
            except ValueError:
                target_name = raw_path  # points outside the repository
            valid = anchors_of(target) if target.is_file() else set()
            repaired = repair_anchor(anchor, valid)
            if repaired == anchor:
                continue
            bad = BadLink(_relative(source, root), line, target_name, anchor, repaired,
                          m.start(group), m.end(group))
            (report.repairable if repaired else report.broken).append(bad)
    return report


def apply(root: pathlib.Path, report: Report) -> None:
    """Rewrite every repairable link. ``report`` must be fresh from ``scan``."""
    root = root.resolve()
    for source in sorted({b.source for b in report.repairable}):
        path = root / source
        text = _read(path)
        for b in sorted((b for b in report.repairable if b.source == source),
                        key=lambda b: b.start, reverse=True):
            text = text[:b.start] + b.repaired + text[b.end:]
        _write(path, text)


def run(root: pathlib.Path, write: bool = False, out=None, skip_sources: tuple[str, ...] = ()) -> Report:
    """Scan ``root``, print what was found, and rewrite when asked."""
    out = out or sys.stdout  # resolved per call so pytest's capture sees it
    report = scan(root, skip_sources)
    print(f"scanned {report.links} anchor link(s) in {report.files} Markdown file(s)", file=out)
    print(f"{'rewrote' if write else 'would rewrite'} {len(report.repairable)} link(s)", file=out)
    for b in report.repairable:
        print(f"  {b}", file=out)
    print(f"unrepairable: {len(report.broken)}", file=out)
    for b in report.broken:
        print(f"  {b}", file=out)
    if report.broken:
        print("  (not read as headings: raw HTML like <h2>x</h2>, and a heading inside a list item)", file=out)
    if write:
        apply(root, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="say what --write would change; write nothing (the default)")
    mode.add_argument("--check", action="store_true",
                      help="write nothing; exit 1 if any link is bad, repairable or not")
    mode.add_argument("--write", action="store_true", help="rewrite the links that can be repaired")
    ap.add_argument("--root", default=None, help="repository root (default: two levels above this script)")
    ap.add_argument("--skip-source", action="append", default=[], metavar="FILE",
                    help="repo-relative file whose own links are left out; links to it are still checked (repeatable)")
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve() if args.root else pathlib.Path(__file__).resolve().parent.parent.parent
    report = run(root, write=args.write, skip_sources=tuple(args.skip_source))
    if args.check:
        return 1 if report.bad else 0
    return 1 if args.write and report.broken else 0


if __name__ == "__main__":
    raise SystemExit(main())

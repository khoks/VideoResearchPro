"""fix_anchor_links.py must agree with GitHub, not with its own slug function.

The expected slugs below were read from GitHub's rendered HTML of the repo's
docs (id="user-content-…"), which is the only oracle that matters: 2026-10-18
for the first eight, and 2026-11-04 for the headings with inline Markdown,
when every doc's headings were compared with `heading_slugs` (1,181 ids, no
difference). The T-4.8.5 board entry names the cases marked below.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fix_anchor_links.py"
sys.path.insert(0, str(SCRIPT.parent))

import fix_anchor_links as fal  # noqa: E402


@pytest.mark.parametrize(
    "heading,slug",
    [
        # T-4.8.5: every dropped em dash or emoji leaves two hyphens.
        ("D-063 — Per-user isolation: shared cache, private catalogue (2026-07-31)",
         "d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31"),
        ("E-5.10 🟡 Per-user isolation (R2)", "e-510--per-user-isolation-r2"),
        ("E-2.5 🟢 Marketing landing page (warm-editorial)", "e-25--marketing-landing-page-warm-editorial"),
        ("L4 — Curated source ranking ⚪", "l4--curated-source-ranking-"),
        ("I-1 🟡 Multi-source ingest — original scope closed 2026-05-03",
         "i-1--multi-source-ingest--original-scope-closed-2026-05-03"),
        ("D-001 — Rebrand to Pratidhvani (प्रतिध्वनि) (2026-04-24)",
         "d-001--rebrand-to-pratidhvani-प्रतिध्वनि-2026-04-24"),
        ("Open questions parking lot", "open-questions-parking-lot"),
        ("7. Hosted UX", "7-hosted-ux"),
    ],
)
def test_github_slug_matches_rendered_ids(heading, slug):
    assert fal.github_slug(heading) == slug


@pytest.mark.parametrize(
    "heading,slug",
    [
        ("### One-click restart — [`c48c7fb`](https://github.com/x/y/commit/c48c7fb)",
         "one-click-restart--c48c7fb"),
        ("### `GET /api/v1/usage`", "get-apiv1usage"),
        ("### D-012 — Capture ideas in `inventions.md` (2026-04-25)",
         "d-012--capture-ideas-in-inventionsmd-2026-04-25"),
        ("## **Bold** and *emphasis* in `snake_case`", "bold-and-emphasis-in-snake_case"),
        ("## Q&amp;A with <b>markup</b>", "qa-with-markup"),
        ("## Closing hashes ##", "closing-hashes"),
    ],
)
def test_inline_markdown_comes_off_as_github_renders_it(heading, slug):
    assert fal.heading_slugs(heading + "\n") == {slug}


def test_a_repeated_heading_is_numbered_as_github_numbers_it():
    text = "## Scope\n\n## Scope\n\n## Scope-1\n\n## Scope\n"
    assert fal.heading_slugs(text) == {"scope", "scope-1", "scope-1-1", "scope-2"}


def test_a_comment_in_a_code_block_is_not_a_heading():
    text = "# Real\n\n```bash\n# not a heading\n```\n\n~~~\n## neither\n~~~\n"
    assert fal.heading_slugs(text) == {"real"}


FORMS = SCRIPT.parents[1] / "tests" / "fixtures" / "anchors" / "heading_forms.md"


def test_heading_forms_match_what_github_rendered():
    """The expected ids are GitHub's, read from the rendered file (contents API,
    `html` media type): re-read them when the fixture changes. Numbering runs in
    document order across every form, so a form this missed would shift `repeat-…`.
    GitHub also rendered `raw-heading`, `heading-in-a-list` and
    `heading-in-an-ordered-list`, the two forms the script says it does not read."""
    expected = {
        "atx-one", "setext-one", "setext-two", "two-linesof-setext",
        "quoted-atx", "quoted-setext", "nested-quote", "quote-with-no-space",
        "repeat", "repeat-1", "repeat-2", "repeat-3",
        "atx-then-a-rule", "spaces-after-the-underline", "inline-code-here", "between-two-rules",
    }
    assert fal.heading_slugs(FORMS.read_text(encoding="utf-8")) == expected


@pytest.mark.parametrize(
    "text,slugs",
    [
        ("Title\n=====\n", {"title"}),
        ("Title\n-----\n", {"title"}),
        ("Title\n-\n", {"title"}),
        ("One\ntwo\n---\n", {"onetwo"}),  # GitHub drops the break: no hyphen
        ("Title\r\n---\r\n", {"title"}),
    ],
)
def test_a_setext_heading_is_a_heading(text, slugs):
    assert fal.heading_slugs(text) == slugs


@pytest.mark.parametrize(
    "text",
    [
        "Text\n\n---\n",           # a blank line first: a rule
        "- item\n---\n",           # a list item
        "1. item\n---\n",
        "| a |\n|---|\n| 1 |\n---\n",  # a table
        "<div>\n---\n</div>\n",      # an HTML block
        "    code\n    ---\n",     # indented code
        "Text\n    ---\n",         # four spaces: more paragraph
        "> quoted\n---\n",          # a rule after the quote
        "Text\n> ---\n",            # the same the other way round
        "```\nTitle\n---\n```\n",   # a code block
    ],
)
def test_an_underline_with_no_paragraph_of_its_own_is_not_a_heading(text):
    assert fal.heading_slugs(text) == set()


@pytest.mark.parametrize(
    "text,slugs",
    [
        ("> ## Note\n", {"note"}),
        (">## Note\n", {"note"}),
        ("   > ## Note\n", {"note"}),
        ("> > ### Deep\n", {"deep"}),
        ("> Note\n> ---\n", {"note"}),
        ("> Note\n> ===\n", {"note"}),
        ("> ## Note\r\n", {"note"}),
    ],
)
def test_a_heading_in_a_blockquote_is_a_heading(text, slugs):
    assert fal.heading_slugs(text) == slugs


def test_a_code_block_in_a_blockquote_is_not_a_heading():
    assert fal.heading_slugs("> ```\n> # not a heading\n> ```\n") == set()


def test_a_code_block_opened_in_a_blockquote_ends_with_it():
    assert fal.heading_slugs("> ```\n> code\n\n## Real\n") == {"real"}


def test_repeated_headings_number_in_document_order_across_forms():
    text = "Scope\n=====\n\n## Scope\n\n> ### Scope\n\nScope\n-----\n\n## Scope\n"
    assert fal.heading_slugs(text) == {"scope", "scope-1", "scope-2", "scope-3", "scope-4"}


def test_front_matter_is_not_a_heading():
    text = "---\ntitle: x\nstatus: y\n---\n\n# Real\n"
    assert fal.heading_slugs(text) == {"real"}
    assert fal.heading_slugs(text.replace("\n", "\r\n")) == {"real"}


def test_check_accepts_a_good_link_to_every_heading_form(tmp_path):
    # The review's reproduction: three correct links, "unrepairable: 3", exit 1.
    (tmp_path / "a.md").write_text(
        "One\n===\n\nTwo\n---\n\n> ## Three\n\n[1](#one) [2](#two) [3](#three)\n",
        encoding="utf-8",
    )
    result = _cli(tmp_path, "--check")
    assert result.returncode == 0, result.stdout
    assert "unrepairable: 0" in result.stdout


def test_a_failure_names_the_heading_forms_it_cannot_see(tmp_path):
    (tmp_path / "a.md").write_text("<h2>Raw</h2>\n\n- ## Listed\n\n[x](#raw)\n", encoding="utf-8")
    result = _cli(tmp_path, "--check")
    assert result.returncode == 1
    assert "raw HTML" in result.stdout and "list item" in result.stdout


def test_a_clean_run_says_nothing_about_heading_forms(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n[x](#a)\n", encoding="utf-8")
    assert "raw HTML" not in _cli(tmp_path, "--check").stdout


def test_an_anchor_tag_is_a_link_target():
    assert fal.heading_slugs('# Real\n\n<a id="kept-name"></a>\n') == {"real", "kept-name"}


def test_repair_rewrites_the_collapsed_form_back_to_the_real_slug():
    # T-4.8.5: PR #179 rewrote `#d-063--per-user-…` to `#d-063-per-user-…`.
    valid = {"d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31", "l4--curated-source-ranking-"}
    assert fal.repair_anchor("d-063-per-user-isolation-shared-cache-private-catalogue-2026-07-31", valid) == \
        "d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31"
    assert fal.repair_anchor("l4-curated-source-ranking", valid) == "l4--curated-source-ranking-"
    assert fal.repair_anchor("l4--curated-source-ranking-", valid) == "l4--curated-source-ranking-"


def test_repair_refuses_to_guess_when_nothing_or_too_much_matches():
    valid = {"e-25--marketing-landing-page-sections", "e-25--marketing-landing-page-warm-editorial"}
    assert fal.repair_anchor("e-25-marketing-landing-page", valid) is None
    assert fal.repair_anchor("does-not-exist", valid) is None


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "decisions.md").write_text(
        "# Decisions\n\n## D-063 — Per-user isolation (2026-07-31)\n\ntext\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "initiatives.md").write_text(
        "# Work\n\nSee [D-063](decisions.md#d-063-per-user-isolation-2026-07-31) and "
        "[missing](decisions.md#d-999-nope) and [ok](decisions.md#d-063--per-user-isolation-2026-07-31).\n",
        encoding="utf-8",
    )
    return tmp_path


def _cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _anchors(report: fal.Report) -> tuple[list[str], list[str]]:
    return [b.anchor for b in report.repairable], [b.anchor for b in report.broken]


def test_the_default_is_a_dry_run_that_writes_nothing_and_exits_zero(tmp_path):
    # T-4.8.5: the first version had no dry run and rewrote the docs on every call.
    root = _repo(tmp_path)
    before = (root / "docs" / "initiatives.md").read_bytes()
    result = _cli(root)
    assert result.returncode == 0, result.stderr
    assert (root / "docs" / "initiatives.md").read_bytes() == before
    assert "would rewrite 1 link(s)" in result.stdout
    assert "d-999-nope" in result.stdout


def test_check_writes_nothing_and_exits_non_zero_on_a_bad_link(tmp_path):
    root = _repo(tmp_path)
    before = (root / "docs" / "initiatives.md").read_bytes()
    assert _cli(root, "--check").returncode == 1
    assert (root / "docs" / "initiatives.md").read_bytes() == before


def test_check_passes_once_every_link_is_good(tmp_path):
    root = _repo(tmp_path)
    (root / "docs" / "initiatives.md").write_text(
        "[ok](decisions.md#d-063--per-user-isolation-2026-07-31)\n", encoding="utf-8"
    )
    result = _cli(root, "--check")
    assert result.returncode == 0, result.stdout
    assert "unrepairable: 0" in result.stdout


def test_a_repairable_link_alone_still_fails_check(tmp_path):
    root = _repo(tmp_path)
    (root / "docs" / "initiatives.md").write_text(
        "[d](decisions.md#d-063-per-user-isolation-2026-07-31)\n", encoding="utf-8"
    )
    assert _cli(root, "--check").returncode == 1


def test_an_unknown_flag_rewrites_nothing(tmp_path):
    # T-4.8.5: `--report` used to be ignored, and the files were rewritten.
    root = _repo(tmp_path)
    before = (root / "docs" / "initiatives.md").read_bytes()
    assert _cli(root, "--report").returncode == 2
    assert (root / "docs" / "initiatives.md").read_bytes() == before


def test_write_rewrites_only_the_repairable_link_and_is_idempotent(tmp_path):
    root = _repo(tmp_path)
    first = _cli(root, "--write")
    assert first.returncode == 1, "an unrepairable link remains, and the exit code says so"
    text = (root / "docs" / "initiatives.md").read_text(encoding="utf-8")
    assert text.count("decisions.md#d-063--per-user-isolation-2026-07-31") == 2
    assert "decisions.md#d-999-nope" in text
    assert _anchors(fal.scan(root)) == ([], ["d-999-nope"])


def test_write_changes_only_the_anchor_and_keeps_crlf(tmp_path):
    root = _repo(tmp_path)
    path = root / "docs" / "initiatives.md"
    path.write_bytes("line\r\n\r\n[d](decisions.md#d-063-per-user-isolation-2026-07-31) end\r\n".encode())
    fal.run(root, write=True)
    assert path.read_bytes() == \
        "line\r\n\r\n[d](decisions.md#d-063--per-user-isolation-2026-07-31) end\r\n".encode()


def test_a_report_says_where_each_bad_link_is(tmp_path):
    root = _repo(tmp_path)
    report = fal.scan(root)
    assert [(b.source, b.line, b.target) for b in report.broken] == \
        [("docs/initiatives.md", 3, "docs/decisions.md")]


def test_a_link_within_the_same_file_is_checked(tmp_path):
    (tmp_path / "a.md").write_text("# Good heading\n\n[y](#good-heading) [n](#gone-heading)\n", encoding="utf-8")
    assert _anchors(fal.scan(tmp_path)) == ([], ["gone-heading"])


def test_a_path_resolves_from_the_file_holding_the_link(tmp_path):
    # CHANGELOG.md held `decisions.md#…`, which is docs/decisions.md only from
    # inside docs/. The old script matched on the file's stem and passed it.
    root = _repo(tmp_path)
    (root / "docs" / "initiatives.md").unlink()
    (root / "CHANGELOG.md").write_text(
        "[bad](decisions.md#d-063--per-user-isolation-2026-07-31)\n"
        "[good](docs/decisions.md#d-063--per-user-isolation-2026-07-31)\n",
        encoding="utf-8",
    )
    (root / "docs" / "plans").mkdir()
    (root / "docs" / "plans" / "x.md").write_text(
        "[up](../decisions.md#d-063--per-user-isolation-2026-07-31)\n", encoding="utf-8"
    )
    report = fal.scan(root)
    assert [(b.source, b.target, b.repaired) for b in report.broken] == [("CHANGELOG.md", "decisions.md", None)]
    assert report.links == 3


@pytest.mark.parametrize(
    "line",
    [
        "`[x](a.md#gone)` in a code span",
        "<!-- [x](a.md#gone) -->",
        "[x](https://example.com/a.md#gone)",
        "[x](notes.json#gone)",
    ],
)
def test_what_is_not_a_link_to_a_doc_is_not_checked(tmp_path, line):
    (tmp_path / "a.md").write_text(f"# A\n\n{line}\n", encoding="utf-8")
    assert fal.scan(tmp_path).links == 0


def test_a_link_in_a_code_block_is_not_checked(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n```\n[x](a.md#gone)\n```\n", encoding="utf-8")
    assert fal.scan(tmp_path).links == 0


def test_a_percent_encoded_anchor_is_compared_decoded(tmp_path):
    (tmp_path / "a.md").write_text(
        "# प्रतिध्वनि\n\n[x](#%E0%A4%AA%E0%A5%8D%E0%A4%B0%E0%A4%A4%E0%A4%BF%E0%A4%A7%E0%A5%8D%E0%A4%B5%E0%A4%A8%E0%A4%BF)\n",
        encoding="utf-8",
    )
    assert fal.scan(tmp_path).bad == 0


def test_a_reference_link_is_checked(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n[x][r]\n\n[r]: a.md#gone\n", encoding="utf-8")
    assert _anchors(fal.scan(tmp_path)) == ([], ["gone"])


def test_a_link_to_a_file_that_does_not_exist_is_bad(tmp_path):
    (tmp_path / "a.md").write_text("[x](missing.md#anything)\n", encoding="utf-8")
    assert _anchors(fal.scan(tmp_path)) == ([], ["anything"])


def test_skip_source_leaves_out_links_in_a_file_but_not_links_to_it(tmp_path):
    root = _repo(tmp_path)
    (root / "README.md").write_text("[x](docs/initiatives.md#stale)\n", encoding="utf-8")
    report = fal.scan(root, skip_sources=("docs/initiatives.md",))
    assert [(b.source, b.target, b.anchor) for b in report.broken] == [("README.md", "docs/initiatives.md", "stale")]
    assert report.repairable == [], "the skipped file's own links are left out"
    result = _cli(root, "--check", "--skip-source", "docs/initiatives.md", "--skip-source", "README.md")
    assert result.returncode == 0, result.stdout


def test_a_fixture_or_a_dependency_is_not_a_doc(tmp_path):
    for folder in ("node_modules", "__fixtures__", ".claude"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "a.md").write_text("[x](#gone)\n", encoding="utf-8")
    assert fal.scan(tmp_path).files == 0

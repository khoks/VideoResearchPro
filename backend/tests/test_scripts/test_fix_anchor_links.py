"""fix_anchor_links.py must agree with GitHub, not with its own slug function.

The expected slugs below were read from GitHub's rendered HTML of
docs/initiatives.md and docs/decisions.md on 2026-10-18
(id="user-content-…"), which is the only oracle that matters.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fix_anchor_links as fal  # noqa: E402


@pytest.mark.parametrize(
    "heading,slug",
    [
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


def test_repair_rewrites_the_collapsed_form_back_to_the_real_slug():
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


def test_check_mode_reports_and_writes_nothing(tmp_path, capsys):
    root = _repo(tmp_path)
    before = (root / "docs" / "initiatives.md").read_text(encoding="utf-8")
    rewrites, broken = fal.run(root, check=True)
    assert (rewrites, broken) == (1, 1)
    assert (root / "docs" / "initiatives.md").read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "would rewrite 1" in out and "d-999-nope" in out


def test_fix_mode_rewrites_only_the_repairable_link_and_is_idempotent(tmp_path):
    root = _repo(tmp_path)
    assert fal.run(root) == (1, 1)
    text = (root / "docs" / "initiatives.md").read_text(encoding="utf-8")
    assert text.count("decisions.md#d-063--per-user-isolation-2026-07-31") == 2
    assert "decisions.md#d-999-nope" in text
    assert fal.run(root) == (0, 1)

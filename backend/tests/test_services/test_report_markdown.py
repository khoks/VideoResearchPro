"""S-6.1.2 — the Markdown source of a report.

Round-trips three REAL stored reports (``tests/fixtures/reports``: a
three-video topic run, an eighty-citation run, and a run with no
transcripts) plus one synthetic report built by the production template, and
asserts what the book, the site index and the ``.md`` route depend on:
headings keep their levels as ATX, every ``&t=`` citation link survives with
its href, tables survive as tables, the statistics grid becomes a table, no
stylesheet or tag text leaks, and ``[VISUAL @ …]`` spans pass through
verbatim. Then the cache beside the HTML, and the book outputter reading it.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import report_service
from app.services.report_service import html_to_markdown, report_markdown
from app.utils.html_builder import build_report_html

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "reports"
REAL_REPORTS = sorted(FIXTURES.glob("*.html"))

_SEPARATOR_ROW = re.compile(r"\|(\s*-{3,}\s*\|)+")
_TAG = re.compile(r"</?(div|p|h[1-6]|a|span|table|tr|td|th|ul|ol|li|strong|em|section)\b", re.I)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", REAL_REPORTS, ids=[p.stem for p in REAL_REPORTS])
def test_real_report_round_trips(path):
    html = _read(path)
    md = html_to_markdown(html)

    # Headings: the H1 and every H2/H3 of the HTML appear as ATX headings.
    for level, tag in ((1, "h1"), (2, "h2"), (3, "h3")):
        titles = [re.sub(r"\s+", " ", t).strip() for t in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.S)]
        titles = [re.sub(r"<[^>]+>", "", t) for t in titles]
        for title in titles:
            title = title.replace("&amp;", "&")
            assert f"{'#' * level} {title}" in md, f"{path.name}: lost heading {title!r}"

    # Every citation link keeps its href, including the `&t=` timestamp.
    hrefs = re.findall(r'<a href="([^"]*&t=[^"]*)"', html)
    md_hrefs = re.findall(r"\]\(([^)]*&t=[^)]*)\)", md)
    assert len(md_hrefs) == len(hrefs), f"{path.name}: {len(hrefs)} links in, {len(md_hrefs)} out"
    assert sorted(md_hrefs) == sorted(h.replace("&amp;", "&") for h in hrefs)

    # Tables survive as tables: one separator row per HTML table, plus one
    # for the statistics grid.
    separators = [ln for ln in md.splitlines() if _SEPARATOR_ROW.fullmatch(ln)]
    assert len(separators) == html.count("<table") + 1
    assert "| Videos Analyzed | Transcripts Fetched | Total Words | Total Minutes |" in md

    # Chrome gone: no stylesheet, no document title line, no tags.
    assert "font-family" not in md and "box-sizing" not in md
    assert not _TAG.search(md), f"{path.name}: tag left in Markdown"
    assert md.startswith("# Research Report:")
    assert md.endswith("\n") and "\n\n\n" not in md


def test_conversion_is_deterministic():
    html = _read(REAL_REPORTS[0])
    assert html_to_markdown(html) == html_to_markdown(html)


def test_synthetic_report_keeps_visual_spans_links_and_table():
    body = (
        "<h2>Executive Summary</h2>"
        "<p>The speaker says rates will fall. [VISUAL @ 01:23 - slide titled \"Q3 outlook\" with a bar chart] "
        "Then she cites <a href=\"https://www.youtube.com/watch?v=abc123&amp;t=83\" target=\"_blank\">1:23</a>.</p>"
        "<h3>Key numbers</h3>"
        "<ul><li>Inflation at 3.2% <em>as of</em> June</li><li>rate_cuts * expected</li></ul>"
        "<table><thead><tr><th>Metric</th><th>Value</th></tr></thead>"
        "<tbody><tr><td>CPI</td><td>3.2%</td></tr></tbody></table>"
    )
    stats = {
        "video_count": 2, "transcript_count": 2, "total_words": 1234, "total_minutes": 56,
        "channel_breakdown": [{"channel_name": "Macro Minute", "video_count": 2, "word_count": 1234, "minutes": 56}],
    }
    html = build_report_html("Rates", "topic", stats, body)
    md = html_to_markdown(html)

    assert "# Research Report: Rates" not in md and md.startswith("# Rates")
    assert "## Statistics" in md and "## Executive Summary" in md and "### Key numbers" in md
    assert "| Videos Analyzed | Transcripts Fetched | Total Words | Total Minutes |\n| --- | --- | --- | --- |\n| 2 | 2 | 1,234 | 56 |" in md
    assert "| Channel | Videos | Words | Minutes |" in md and "| Macro Minute | 2 | 1,234 | 56 |" in md
    assert "| Metric | Value |" in md and "| CPI | 3.2% |" in md
    assert "[1:23](https://www.youtube.com/watch?v=abc123&t=83)" in md
    assert '[VISUAL @ 01:23 - slide titled "Q3 outlook" with a bar chart]' in md
    assert "- Inflation at 3.2% *as of* June" in md
    assert "rate_cuts * expected" in md  # prose is not escaped
    assert "font-family" not in md and "<" not in md.replace("<=", "")


def test_fragment_without_report_chrome_still_converts():
    assert html_to_markdown("<h1>Tariffs Report</h1><p>Body content here.</p>") == "# Tariffs Report\n\nBody content here.\n"
    assert html_to_markdown("") == ""


# ---------------------------------------------------------------------------
# report_markdown(job): the cache beside the HTML
# ---------------------------------------------------------------------------


def _job_with_report(tmp_path: Path, html: str) -> SimpleNamespace:
    report = tmp_path / "report_job1.html"
    report.write_text(html, encoding="utf-8")
    return SimpleNamespace(report_path=str(report), topic="Job one")


def test_report_markdown_caches_beside_the_html(tmp_path):
    job = _job_with_report(tmp_path, "<h1>T</h1><p>one</p>")
    md = report_markdown(job)
    cache = Path(report_service.markdown_path_for(job.report_path))
    assert md == "# T\n\none\n"
    assert cache.read_text(encoding="utf-8") == md

    # A fresh cache is served without reconverting: tamper with it and read.
    cache.write_text("# cached\n", encoding="utf-8")
    assert report_markdown(job) == "# cached\n"

    # Newer HTML invalidates the cache.
    time.sleep(0.05)
    Path(job.report_path).write_text("<h1>T</h1><p>two</p>", encoding="utf-8")
    os.utime(job.report_path, None)
    assert report_markdown(job) == "# T\n\ntwo\n"
    assert cache.read_text(encoding="utf-8") == "# T\n\ntwo\n"

    # force=True rewrites even a fresh cache.
    cache.write_text("# stale\n", encoding="utf-8")
    assert report_markdown(job, force=True) == "# T\n\ntwo\n"


def test_report_markdown_returns_none_without_a_report(tmp_path):
    assert report_markdown(SimpleNamespace(report_path=None)) is None
    assert report_markdown(SimpleNamespace(report_path=str(tmp_path / "missing.html"))) is None


def test_report_markdown_survives_an_unwritable_cache(monkeypatch):
    """The book tests patch `get_report_html` with a path that does not exist
    on disk; the conversion must still be returned when the cache cannot
    be written."""
    job = SimpleNamespace(report_path="/nonexistent/dir/report.html")
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<h1>X</h1><p>Body.</p>")
    assert report_markdown(job) == "# X\n\nBody.\n"


def test_delete_report_removes_the_cached_markdown(tmp_path):
    job = _job_with_report(tmp_path, "<h1>T</h1>")
    report_markdown(job)
    cache = Path(report_service.markdown_path_for(job.report_path))
    assert cache.exists()
    assert report_service.delete_report(job.report_path) is True
    assert not Path(job.report_path).exists() and not cache.exists()

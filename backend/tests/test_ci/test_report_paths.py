"""T-8.8.6.4 — no test leaves a report's Markdown at the filesystem root.

``report_service.report_markdown`` caches its conversion beside the report, and
a test that patches ``get_report_html`` needs no real file. So ``"/r.html"`` was
enough to write ``D:\\r.html.md`` on every run, and on a Linux runner to log a
refused write and pass. conftest turns that into a failure wherever the path
comes from. These tests hold the guard to it, through the production caller.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import report_service
from app.services.outputters import book_markdown


@pytest.fixture
def stored_report(monkeypatch):
    monkeypatch.setattr(report_service, "get_report_html", lambda path: "<h1>T</h1><p>Body.</p>")


@pytest.mark.parametrize("path", ["/r.html", "/a.html", Path("/").resolve() / "r.html"])
def test_a_report_at_the_filesystem_root_fails_the_test(stored_report, path) -> None:
    with pytest.raises(pytest.fail.Exception, match="tmp_path"):
        report_service.report_markdown(SimpleNamespace(report_path=str(path)))


def test_a_book_chapter_cannot_swallow_the_failure(stored_report) -> None:
    """The book catches every Exception around the conversion and prints a
    placeholder chapter, which would pass most tests."""
    job = SimpleNamespace(id="j", topic="T", report_path="/r.html")
    with pytest.raises(pytest.fail.Exception, match="tmp_path"):
        book_markdown._job_report_markdown(job)


def test_a_report_in_a_folder_is_cached_beside_it(stored_report, tmp_path) -> None:
    report = tmp_path / "r.html"
    assert report_service.report_markdown(SimpleNamespace(report_path=str(report))) == "# T\n\nBody.\n"
    assert (tmp_path / "r.html.md").is_file()
    assert report_service.markdown_path_for("r.html") == "r.html.md", "a relative path is not at the root"

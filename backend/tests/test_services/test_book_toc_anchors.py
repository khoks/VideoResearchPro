"""T-8.8.4.2 — a book's contents links land on the headings they name.

Slugging each title on its own gets the id wrong whenever an earlier heading
took it: a report's own "Conclusion" keeps the plain id, the book's Conclusion
is `conclusion-2`, and the link goes to the wrong chapter without being dead.
These tests read the ids back from what was rendered, in the Markdown, the
EPUB and the PDF. The reader runs a different parser, so it is checked against
the same manuscript in `frontend/src/components/reader/__tests__/bookContents.test.tsx`,
through the fixture this file keeps current.

The site outputter is not here: it renders each report on its own page and
never reads a book's manuscript or its contents section.
"""
from __future__ import annotations

import os
import re
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from lxml import etree

from app.config import settings
from app.models.job import Job
from app.services import auth_service, output_artifacts
from app.services.outputters import book_cohesion, book_epub, book_html, book_markdown, book_pdf
from tests.test_services.test_book_endnotes import _generate

LINK = re.compile(r"\[((?:\\.|[^\]\\])*)\]\(#([^)]*)\)")
XHTML = "{http://www.w3.org/1999/xhtml}"
NS = {"x": "http://www.w3.org/1999/xhtml", "epub": "http://www.idpf.org/2007/ops"}
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/components/reader/__tests__/fixtures/book-contents.manuscript.txt"
)


@pytest.fixture(autouse=True)
def quiet_progress():
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


def _run(db, user_id: str, topic: str, html: str = "<h1>T</h1><p>Body.</p>") -> Job:
    job = Job(id=str(uuid.uuid4()), tenant_id=user_id, job_type="topic", status="completed", topic=topic,
              report_path=f"/{uuid.uuid4()}.html")
    db.add(job)
    db.commit()
    _REPORTS[job.report_path] = html
    return job


_REPORTS: dict[str, str] = {}


@pytest.fixture
def reports(monkeypatch):
    from app.services import report_service

    _REPORTS.clear()
    monkeypatch.setattr(report_service, "get_report_html", lambda path: _REPORTS[path])


@pytest.fixture
def user(db):
    return auth_service.create_user(db, email=f"toc-{uuid.uuid4().hex[:8]}@x.com", password="pw" * 6)


def _cohesion(chapters: int, **fields) -> book_cohesion.Cohesion:
    return book_cohesion.Cohesion(level="full", order=list(range(1, chapters + 1)), **fields)


def _toc_links(nav) -> list:
    return nav.xpath("//x:nav[@epub:type='toc']//x:a", namespaces=NS)


def _contents(md: str) -> str:
    return md.split("## Table of Contents\n", 1)[1].split("\n## ", 1)[0]


def _landings(md: str) -> list[tuple[str, book_html.Heading]]:
    """Every contents link, with the heading it lands on in the rendered book.
    A link to an id nothing has fails here."""
    by_id = {h.id: h for h in book_html.render_book_html(md, title="t").headings}
    out = []
    for label, anchor in LINK.findall(_contents(md)):
        assert anchor in by_id, f"dead link: [{label}](#{anchor})"
        out.append((re.sub(r"\\(.)", r"\1", label), by_id[anchor]))
    return out


# ---------------------------------------------------------------------------
# Through the outputter, from a real generation
# ---------------------------------------------------------------------------


def test_the_books_own_conclusion_is_not_the_reports(db, user, reports, monkeypatch):
    """The bug: the contents went to the first chapter's own Conclusion."""
    report = "<h1>T</h1><h2>Conclusion</h2><p>The report's ending.</p>"
    a, b = _run(db, user.id, "First run", report), _run(db, user.id, "Second run", report)
    monkeypatch.setattr(book_cohesion, "plan", lambda digests, title, level, progress=None: _cohesion(
        2, introduction="Opening.", conclusion="The book's ending.", glossary=[("term", "meaning")], applied="full"
    ))
    md = _generate(db, user, [a.id, b.id], formats=[], cohesion="full", include_qa=False).content_text

    assert "- [Conclusion](#conclusion-3)" in md, "two reports' Conclusions come first"
    landings = _landings(md)
    assert [label for label, _ in landings] == ["Introduction", "First run", "Second run", "Conclusion", "Glossary"]
    assert all(heading.level == 2 for _, heading in landings), "every entry lands on a book heading"
    end = next(h for label, h in landings if label == "Conclusion")
    assert md.split("\n")[end.line] == "## Conclusion"
    assert md.split("\n")[end.line + 2] == "The book's ending."


@pytest.mark.parametrize(
    ("topic", "shown"),
    [
        ("AT&T <draft>", "AT&T <draft>"),
        ("a ] b", "a ] b"),
        ("[bracketed] plan", "[bracketed] plan"),
        ("What is C #", "What is C #"),
        ("C# and F#", "C# and F#"),
        ("snake_case_names and *stars*", "snake_case_names and *stars*"),
        ("AT&amp;T", "AT&amp;T"),
        ("`code` ~~gone~~", "`code` ~~gone~~"),
        ("back\\slash", "back\\slash"),
        ("two\nlines   of  topic", "two lines of topic"),
        ("हिंदी पुस्तक — भाग १", "हिंदी पुस्तक — भाग १"),
        ("Café: déjà vu?", "Café: déjà vu?"),
    ],
)
def test_a_typed_topic_is_shown_as_typed_and_linked(db, user, reports, topic, shown):
    job = _run(db, user.id, topic)
    out = _generate(db, user, [job.id], formats=["epub"], include_qa=False)

    [(label, heading)] = _landings(out.content_text)
    assert label == shown
    assert (heading.level, heading.text) == (2, f"1. {shown}")

    with zipfile.ZipFile(output_artifacts.artifact_file(out, "epub")) as z:
        nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
        chapter = etree.fromstring(z.read("OEBPS/part-001.xhtml"))
    [link] = _toc_links(nav)
    assert link.get("href") == f"part-001.xhtml#{heading.id}"
    assert "".join(link.itertext()).strip() == f"1. {shown}"
    assert heading.id in {el.get("id") for el in chapter.iter() if isinstance(el.tag, str)}


def test_every_format_lands_on_the_same_heading(db, user, reports, monkeypatch):
    """Colliding headings, in the EPUB: each contents entry opens the file
    holding the book's heading, not the chapter that took the plain id."""
    report = "<h1>T</h1><h2>Glossary</h2><p>Terms.</p><h2>Endnotes</h2><p>The report's notes.</p>"
    job = _run(db, user.id, "Only run", report)
    monkeypatch.setattr(book_cohesion, "plan", lambda digests, title, level, progress=None: _cohesion(
        1, conclusion="End.", glossary=[("term", "meaning")], applied="full"
    ))
    out = _generate(db, user, [job.id], formats=["epub"], cohesion="full", include_qa=False)
    landings = dict(_landings(out.content_text))
    assert landings["Glossary"].id == "glossary-2"

    with zipfile.ZipFile(output_artifacts.artifact_file(out, "epub")) as z:
        nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
        parts = {n: etree.fromstring(z.read(n)) for n in z.namelist() if n.startswith("OEBPS/part-")}
    links = {"".join(a.itertext()).strip(): a.get("href") for a in _toc_links(nav)}
    file, _, anchor = links["Glossary"].partition("#")
    assert anchor == "glossary-2"
    target = next(el for el in parts[f"OEBPS/{file}"].iter() if el.get("id") == anchor)
    assert target.tag == f"{XHTML}h2" and "".join(target.itertext()) == "Glossary"
    assert len(parts) == 3, "the chapter, the Conclusion, the Glossary: no section is lost"


def test_a_pdf_contents_entry_opens_the_books_heading(db, user, reports, monkeypatch):
    fitz = pytest.importorskip("fitz")
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "auto")
    book_pdf.reset_probes()
    try:
        if book_pdf.pdf_engine() is None:
            pytest.skip(f"no PDF engine here: {book_pdf.unavailable_message()}")
        report = "<h1>T</h1><h2>Conclusion</h2><p>The report's ending.</p>"
        job = _run(db, user.id, "Only run", report)
        monkeypatch.setattr(book_cohesion, "plan", lambda digests, title, level, progress=None: _cohesion(
            1, conclusion="The book's ending.", applied="full"
        ))
        out = _generate(db, user, [job.id], formats=["pdf"], cohesion="full", include_qa=False)
        doc = fitz.open(output_artifacts.artifact_file(out, "pdf"))
        pages = {title: page for _level, title, page in doc.get_toc() if _level == 2}
        toc_page = doc[pages["Table of Contents"] - 1]
        targets = sorted(link["page"] + 1 for link in toc_page.get_links() if link.get("page") is not None)
        assert targets == [pages["1. Only run"], pages["Conclusion"]]
    finally:
        book_pdf.reset_probes()


# ---------------------------------------------------------------------------
# The assembly, where a chapter is awkward
# ---------------------------------------------------------------------------


def test_a_heading_the_old_line_scan_could_not_see_still_counts():
    """A quoted heading and a Setext heading take ids too, and a chapter with
    Windows line endings keeps its lines straight."""
    body = "> #### Conclusion\r\n\r\nSetext\r\n---\r\n\r\n#### Conclusion\r\n"
    md = book_markdown._assemble("B", [(1, "One", body)], [], _cohesion(1, conclusion="End."), include_toc=True)
    landings = dict(_landings(md))
    assert landings["Conclusion"].id == "conclusion-3" and landings["Conclusion"].level == 2


def test_an_unclosed_fence_leaves_a_plain_entry_not_a_dead_link():
    """A code fence a chapter never closes swallows the next chapter's
    heading. The entry stays, as text."""
    md = book_markdown._assemble("B", [(1, "One", "```\ncode"), (2, "Two", "body")], [], _cohesion(2), include_toc=True)
    assert "1. [One](#1-one)" in md
    assert "\n2. Two\n" in md
    assert "(#)" not in md


def test_headings_know_their_line_and_leave_no_trace_in_the_html():
    book = book_html.render_book_html("# A\r\n\r\n> ## B\n\ntext\n\n- ### C\n", title="t")
    assert [(h.text, h.line) for h in book.headings] == [("A", 0), ("B", 2), ("C", 6)]
    assert "data-source-line" not in book.body


def test_the_epub_finds_its_sections_by_text_when_their_ids_were_taken():
    """A report's own "Endnotes" takes the plain id, and so does a book called
    "Table of Contents". The sections are still the contents and the endnotes."""
    book = book_html.render_book_html(
        "# Table of Contents\n\n## Table of Contents\n\n1. [One](#1-one)\n\n"
        "## 1. One\n\n#### Endnotes\n\nThe report's.\n\n## Endnotes\n\nThe book's.\n",
        title="Table of Contents",
    )
    parts = book_epub._split(book)
    assert [p.kind for p in parts] == ["titlepage", "chapter", "endnotes"]
    assert parts[-1].heading_id == "endnotes-2"
    assert "Table of Contents" not in [p.heading_text for p in parts], "nav.xhtml replaces the manuscript's own"


# ---------------------------------------------------------------------------
# The manuscript the reader is tested against
# ---------------------------------------------------------------------------


def _reader_manuscript() -> str:
    """The cases where two renderers could disagree: a title equal to a heading,
    typed punctuation, Devanagari, repeats, a heading in a quote, a part."""
    chapters = [
        (1, "AT&T <draft> ] notes", "#### Conclusion\n\nThe report's ending.\n\n> #### Glossary\n\nQuoted."),
        (2, "हिंदी पुस्तक — भाग १", "#### Conclusion\n\nAnother ending.\n\n#### 1. AT&T\n\nA report's own numbering."),
    ]
    cohesion = _cohesion(
        2, parts=[("Beginnings & ends", [1, 2])], introduction="Opening.", conclusion="The book's ending.",
        glossary=[("term", "meaning")], applied="full",
    )
    md = book_markdown._assemble("Introduction", chapters, [], cohesion, include_toc=True)
    return re.sub(r"Author Studio — \d{4}-\d{2}-\d{2}", "Author Studio — 2026-01-01", md)


def test_the_readers_fixture_is_what_the_outputter_writes():
    """Regenerate with UPDATE_BOOK_FIXTURE=1 after an intended change to the
    manuscript, and run the frontend's `bookContents.test.tsx`."""
    written = _reader_manuscript()
    if os.environ.get("UPDATE_BOOK_FIXTURE"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(written, encoding="utf-8", newline="\n")
    assert FIXTURE.read_text(encoding="utf-8").replace("\r\n", "\n") == written
    assert [label for label, _ in _landings(written)] == [
        "Introduction", "Part I: Beginnings & ends", "AT&T <draft> ] notes", "हिंदी पुस्तक — भाग १", "Conclusion", "Glossary",
    ]

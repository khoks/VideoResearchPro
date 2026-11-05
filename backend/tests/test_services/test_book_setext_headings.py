"""T-8.8.6.2 — a Setext heading is a heading.

`Text` over `---` renders as an `h2`, and `h2` is the book's own level: the EPUB
cuts a new file at each one, and calls the last one the book's endnotes when it
is named Endnotes. Only ATX headings were demoted, so a stored answer that wrote
its heading the other way could still do both. The first tests go through a real
generation, the way an answer reaches the EPUB. The rest pin the line between a
heading and what only looks like one, which the parser decides, not a pattern.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from lxml import html as lxml_html

from app.models.document import Document
from app.models.job import Job
from app.models.qa_exchange import QAExchange
from app.services import auth_service, output_artifacts
from app.services.outputters import book_cohesion, book_epub, book_html, book_markdown
from tests.test_services.test_book_cohesion import OUTLINE, PROSE, FakeModel
from tests.test_services.test_book_endnotes import _generate, _smoke_run
from tests.test_services.test_book_formats import _assert_valid_epub
from tests.test_services.test_book_toc_anchors import _chapters
from tests.test_services.test_site_outputter import _files, _site

EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
XHTML = "{http://www.w3.org/1999/xhtml}"


@pytest.fixture(autouse=True)
def quiet_progress():
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


@pytest.fixture
def user(db):
    return auth_service.create_user(db, email=f"setext-{uuid.uuid4().hex[:8]}@x.com", password="pw" * 6)


@pytest.fixture
def report_run(db, user, tmp_path):
    def make(topic: str = "Only run") -> Job:
        report = tmp_path / f"{uuid.uuid4()}.html"
        report.write_text("<h1>T</h1><p>Body.</p>", encoding="utf-8")
        job = Job(id=str(uuid.uuid4()), tenant_id=user.id, job_type="topic", status="completed", topic=topic,
                  report_path=str(report))
        db.add(job)
        db.commit()
        return job

    return make


def _ask(db, job: Job, answer: str, question: str = "What next?") -> None:
    db.add(QAExchange(job_id=job.id, tenant_id=job.tenant_id, question=question, answer=answer))
    db.commit()


def _section_types(out) -> list[str]:
    return [chapter.find(f".//{XHTML}section").get(EPUB_TYPE) for chapter in _chapters(out).values()]


def _chapter_text(out) -> str:
    [chapter] = _chapters(out).values()
    return "".join(chapter.itertext())


# ---------------------------------------------------------------------------
# Through the outputters, from a real generation
# ---------------------------------------------------------------------------


def test_an_answers_setext_heading_stays_in_its_chapter(db, user, report_run):
    job = report_run()
    _ask(db, job, "Before.\n\nA section\n---\n\nInside it.\n\nA title\n===\n\nInside that.")
    out = _generate(db, user, [job.id], formats=["epub"])

    assert "\n##### A section\n" in out.content_text
    assert "\n#### A title\n" in out.content_text
    assert list(_chapters(out)) == ["OEBPS/part-001.xhtml"], "an answer adds no chapter"
    assert "Inside it." in _chapter_text(out) and "Inside that." in _chapter_text(out)
    _assert_valid_epub(output_artifacts.artifact_file(out, "epub").read_bytes())


def test_an_answers_endnotes_are_not_the_books_backmatter(db, user, report_run):
    """No citations, so the book writes no Endnotes of its own and the answer's
    was the last `h2`, which the EPUB marks as backmatter."""
    job = report_run()
    _ask(db, job, "Endnotes\n---\n\nThe answer's own notes.")
    out = _generate(db, user, [job.id], formats=["epub"])

    assert _section_types(out) == ["chapter"]
    assert "The answer's own notes." in _chapter_text(out)


def test_an_answers_contents_are_not_taken_out_of_the_book(db, user, report_run):
    job = report_run()
    _ask(db, job, "Table of Contents\n---\n\nThe answer's own list.")
    out = _generate(db, user, [job.id], formats=["epub"])

    assert list(_chapters(out)) == ["OEBPS/part-001.xhtml"]
    assert "The answer's own list." in _chapter_text(out)


def test_the_books_outline_does_not_list_an_answers_setext_heading(db, user, report_run):
    job = report_run()
    _ask(db, job, "Conclusion\n---\n\nThe answer's own ending.")
    md = _generate(db, user, [job.id], formats=[]).content_text

    h2s = [h.text for h in book_html.render_book_html(md, title="t").headings if h.level == 2]
    assert h2s == ["Table of Contents", "1. Only run"]


@pytest.mark.parametrize("question", ["Which is it?\n---", "Which is it?\n\n## Endnotes", "Which is it?\n===\nAnd more"])
def test_a_multi_line_question_cannot_make_a_heading(db, user, report_run, question):
    """A question is typed text, at the start of a block in the same chapter.
    It has no level to be demoted to, so it stays on one line."""
    job = report_run()
    _ask(db, job, "An answer.", question=question)
    out = _generate(db, user, [job.id], formats=["epub"])

    assert _section_types(out) == ["chapter"]
    assert f"**Q1.** {' '.join(question.split())}\n" in out.content_text


def test_a_sites_knowledge_report_is_demoted_too(db, user, tmp_path):
    """A source page puts a stored knowledge report under its own heading,
    through the same function, and a model wrote that report."""
    job = _smoke_run(db, user.id, tmp_path)
    doc = db.query(Document).first()
    doc.knowledge_report_md = "Report title\n===\n\nA section\n---\n\nThe knowledge.\n"
    db.commit()

    out = _site(db, user, [job.id])
    assert out.status == "completed", out.error_message
    files = _files(out)
    page = next(lxml_html.fromstring(body) for name, body in files.items()
                if name.startswith("sources/") and b"The knowledge." in body)
    assert [h.text_content() for h in page.xpath("//h3")] == ["A section"]
    assert "Report title" not in page.text_content()


def test_model_prose_keeps_the_heading_text_and_loses_the_underline(db, user, report_run, monkeypatch):
    """Cohesion prose never made a heading, because `clean_prose` runs a
    paragraph's lines together. It printed the underline instead."""
    a, b = report_run("First run"), report_run("Second run")
    prose = {**PROSE, "introduction": "Endnotes\n---\n\nThe opening.", "conclusion": "Last words\n===\nThe ending."}
    monkeypatch.setattr(book_cohesion, "_default_invoke", FakeModel(OUTLINE, prose))
    md = _generate(db, user, [a.id, b.id], formats=[], cohesion="full").content_text

    assert "## Introduction\n\nEndnotes\n\nThe opening.\n" in md
    assert "## Conclusion\n\nLast words\n\nThe ending.\n" in md


# ---------------------------------------------------------------------------
# What is a heading, and what comes out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "md, offset, drop_h1, expected",
    [
        ("Title\n---\n\nBody", 3, False, "##### Title\n\nBody"),
        ("Title\n===\n\nBody", 3, False, "#### Title\n\nBody"),
        ("Title\n-\n\nBody", 3, False, "##### Title\n\nBody"),
        ("  Title  \n   ===   \n\nBody", 3, False, "#### Title\n\nBody"),
        ("Two\nlines\n---\n\nBody", 3, False, "##### Two lines\n\nBody"),
        ("Title\r\n---\r\nBody\r\n", 3, False, "##### Title\nBody"),
        ("Title\n---", 5, False, "###### Title"),
        ("The report\n===\n\nA part\n---\n\nBody", 2, True, "#### A part\n\nBody"),
        ("# The report\n\nSecond\n===\n\nBody", 2, True, "### Second\n\nBody"),
        ("Second\n===\n\n# Third\n\nBody", 2, True, "### Third\n\nBody"),
    ],
)
def test_a_setext_heading_is_demoted_like_an_atx_one(md, offset, drop_h1, expected):
    assert book_markdown._demote_headings(md, offset, drop_h1=drop_h1) == expected


@pytest.mark.parametrize(
    "md",
    [
        "A paragraph.\n\n---\n\nAnother.",
        "- an item\n---\nAfter.",
        "> a quote\n---\nAfter.",
        "```\nTitle\n---\n```",
        "~~~\n# Not a heading\n~~~",
        "| a | b |\n| --- | --- |\n| 1 | 2 |",
        "a | b\n--- | ---\n1 | 2",
        "Before.\n\n    Title\n---\n\nAfter.",
    ],
)
def test_what_only_looks_like_a_heading_is_left_alone(md):
    assert book_markdown._demote_headings(md, 3, drop_h1=False) == md


@pytest.mark.parametrize("md", ["> Quoted\n> ---\n\nAfter.", "- Item\n  ---\n\nAfter.", "> ## Quoted\n\nAfter."])
def test_a_heading_in_a_quote_or_a_list_is_not_a_section_of_the_book(md):
    """It keeps its level, as a quoted ATX heading always has: the EPUB reads
    only the top level, so it starts no file."""
    assert book_markdown._demote_headings(md, 3, drop_h1=False) == md
    book = book_html.render_book_html(f"# B\n\n## 1. One\n\n{md}\n\n## 2. Two\n", title="B")
    assert [p.heading_text for p in book_epub._split(book)[1:]] == ["1. One", "2. Two"]


@pytest.mark.parametrize(
    "md, expected",
    [
        ("## Plain", "##### Plain"),
        ("## Closed ##", "##### Closed ##"),
        ("##\tTabbed", "#####\tTabbed"),
        ("   ## Indented", "##### Indented"),
        ("#", "####"),
        ("###### Deep", "###### Deep"),
    ],
)
def test_atx_headings_come_out_as_they_did(md, expected):
    """All but the indented one and the bare `#`, headings the old first-column
    pattern did not see, which started EPUB files the same way."""
    assert book_markdown._demote_headings(md, 3, drop_h1=False) == expected


def test_a_setext_heading_keeps_a_trailing_hash():
    """On one line after `#`s, a final `#` would read as the closing marks."""
    out = book_markdown._demote_headings("Learning C #\n---", 3, drop_h1=False)
    assert [h.text for h in book_html.render_book_html(out, title="t").headings] == ["Learning C #"]


def test_lines_are_the_parsers_not_pythons():
    """`str.splitlines` also breaks on a form feed or a line separator, which
    the parser does not, and the two would disagree on every line after one."""
    md = "One\x0ctwo three\n\nTitle\n---\n\nBody"
    assert book_markdown._demote_headings(md, 3, drop_h1=False) == "One\x0ctwo three\n\n##### Title\n\nBody"


def test_top_level_headings_say_where_a_heading_ends():
    headings = book_html.top_level_headings("# A\n\nTwo\nlines\n---\n\n> ## Quoted\n")
    assert [(h.level, h.line, h.end, h.setext) for h in headings] == [(1, 0, 1, False), (2, 2, 5, True)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Head\n---\n\nBody.", "Head\n\nBody."),
        ("Head\n===\nBody.", "Head\n\nBody."),
        ("Head\n  ---  \n\nBody.", "Head\n\nBody."),
        ("Before.\n\n---\n\nAfter.", "Before.\n\nAfter."),
        ("A word - and = signs stay.", "A word - and = signs stay."),
    ],
)
def test_clean_prose_drops_the_underline(text, expected):
    assert book_cohesion.clean_prose(text, 50) == expected

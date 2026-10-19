"""BookMarkdownOutputter — I-6 / E-6.1.

Deterministic structural concatenation of selected job reports + their Q&A
history into a Markdown manuscript. No LLM; cohesion (ordering, transition
prose, introductions, glossary) is S-6.1.3.

Source IDs are Job IDs, resolved only within the requesting user's own
jobs (S-5.10.6 / T-5.10.1.4): an id that is not theirs reads exactly like an
id that does not exist. Each job contributes a chapter whose body is the report's Markdown source
(``report_service.report_markdown``, S-6.1.2) with its headings demoted under
the chapter heading.

Parameters (``output.parameters_json``):
- ``include_qa`` (bool, default True) — append the job's Q&A history as a
  "Questions & Answers" subsection per chapter.
- ``include_toc`` (bool, default True) — a top-of-document table of contents.
- ``formats`` (list, S-6.1.5) — files to build beside the Markdown: ``epub``
  and/or ``pdf``. Absent means EPUB, plus PDF when a PDF engine is installed;
  the router writes the resolved list back (``["md", "epub", "pdf"]``) so the
  row records what was built. An explicit ``pdf`` with no engine is refused
  before the row exists (501, with what to install).
- ``cohesion`` (``none`` | ``light`` | ``full``, S-6.1.3, default ``none``) —
  model-written framing around the unchanged chapters (`book_cohesion`):
  reading order, parts and bridges (``light``), plus introduction, conclusion
  and glossary (``full``). Usage and cost land in ``output.usage_json``.

The generated Markdown lands in ``output.content_text``; the EPUB and PDF are
artifacts under ``OUTPUTS_DIR`` (`output_artifacts`), and ``content_path``
points at the PDF when there is one, else the EPUB.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.output import Output
from app.models.qa_exchange import QAExchange
from app.models.user import User
from app.services import output_artifacts, output_citation_service, report_service, visibility_service
from app.services.output_service import OutputError, report_progress
from app.services.outputters import book_cohesion, book_epub, book_html, book_pdf

logger = logging.getLogger(__name__)

# Chapter headings are H2 (`## 1. Title`), so a report's own headings start
# two levels below: its H1 would otherwise compete with the book title.
_CHAPTER_HEADING_OFFSET = 2
_ATX_HEADING = re.compile(r"^(#{1,6})(\s+)(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").strip().lower())
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-") or "section"


def _demote_headings(md: str, offset: int = _CHAPTER_HEADING_OFFSET) -> str:
    """Push every ATX heading down ``offset`` levels (capped at H6), leaving
    fenced code untouched. The report's single H1 repeats the job topic the
    chapter heading already carries, so it is dropped."""
    out: list[str] = []
    in_fence = False
    dropped_h1 = False
    for line in md.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        m = None if in_fence else _ATX_HEADING.match(line)
        if m is None:
            out.append(line)
            continue
        level = len(m.group(1))
        if level == 1 and not dropped_h1:
            dropped_h1 = True
            continue
        out.append("#" * min(6, level + offset) + m.group(2) + m.group(3))
    return "\n".join(out).strip()


def _job_report_markdown(job: Job) -> str:
    """The chapter body for ``job``: its report's Markdown source, demoted,
    or a visible placeholder. A failed chapter is disclosed in the manuscript,
    never silently dropped (the D-056 posture)."""
    if not job.report_path:
        return f"_(Run ‘{job.topic}’ has no report; nothing to include.)_"
    try:
        md = report_service.report_markdown(job)
    except Exception:
        logger.exception("BookMarkdownOutputter: report conversion failed for job=%s", job.id)
        return f"_(Failed to read the report for ‘{job.topic}’.)_"
    if md is None:
        return f"_(The report file for ‘{job.topic}’ is missing.)_"
    return _demote_headings(md)


def _job_qa_markdown(
    db: Session, job_id: str, user_id: str, candidates: list[Document], start: int
) -> tuple[str, list[output_citation_service.CitationSpec]]:
    """The user's own Q&A exchanges on ``job_id`` as a Markdown subsection,
    with its citations numbered from ``start``.

    S-6.1.4 (T-6.1.4.2): an answer cites through the references stored with
    it, never through links parsed out of its prose; links in the prose are
    reduced to their text so the manuscript carries no second, unchecked set.
    """
    rows = (
        db.query(QAExchange)
        .filter(QAExchange.job_id == job_id, QAExchange.tenant_id == user_id)
        .order_by(QAExchange.created_at.asc())
        .all()
    )
    if not rows:
        return "", []
    out = ["### Questions & Answers", ""]
    specs: list[output_citation_service.CitationSpec] = []
    for i, r in enumerate(rows, start=1):
        out.append(f"**Q{i}.** {r.question.strip()}")
        out.append("")
        out.append(output_citation_service.strip_links((r.answer or "").strip()))
        try:
            references = json.loads(r.references or "[]")
        except (TypeError, ValueError):
            references = []
        sources, cited = output_citation_service.cite_references(
            references if isinstance(references, list) else [], candidates, start + len(specs)
        )
        specs.extend(cited)
        if sources:
            out.append("")
            out.append(sources)
        out.append("")
    return "\n".join(out).rstrip(), specs


def _chapter_documents(db: Session, user: User, job_id: str) -> list[Document]:
    """The run's documents the user can see: what a chapter's citations may
    resolve to (S-6.7.3). Never a document outside the tenant's visibility."""
    return (
        db.query(Document)
        .join(JobVideo, JobVideo.document_id == Document.document_id)
        .join(Job, Job.id == JobVideo.job_id)
        .filter(
            JobVideo.job_id == job_id,
            Job.tenant_id == user.id,
            Document.document_id.in_(visibility_service.visible_document_ids(db, user.id)),
        )
        .all()
    )


def _job_chapter(
    db: Session, user: User, job_id: str, *, include_qa: bool, start: int = 1
) -> tuple[str, str, list[output_citation_service.CitationSpec]]:
    """Return ``(chapter_title, chapter_body_markdown, citations)`` for one
    job; the body's citations are footnote references numbered from
    ``start`` (S-6.1.4)."""
    # Tenant is part of the lookup (T-5.10.1.4): another user's job id
    # renders exactly like a missing one. Before 2026-10-19 the filter was
    # the id alone, so a book could compile someone else's report.
    job = db.query(Job).filter(Job.id == job_id, Job.tenant_id == user.id).first()
    if job is None:
        return f"Unknown job {job_id}", "_(Job not found in your library.)_", []

    title = (job.topic or "Untitled").strip()
    candidates = _chapter_documents(db, user, job.id)
    report, specs = output_citation_service.cite_markdown(_job_report_markdown(job), candidates, start)
    parts = [report]
    if include_qa:
        qa_md, qa_specs = _job_qa_markdown(db, job.id, user.id, candidates, start + len(specs))
        specs.extend(qa_specs)
        if qa_md:
            parts.append(qa_md)
    return title, "\n\n".join(p for p in parts if p), specs


# S-6.1.5: files a book can be built as beside its Markdown, in build order.
FILE_FORMATS = ("epub", "pdf")


def requested_formats(params: dict[str, Any]) -> list[str]:
    """The files to build beside the Markdown. ``formats`` absent: EPUB, plus
    PDF when this process has an engine. Present: exactly those (``md`` is
    always produced and may be listed)."""
    raw = params.get("formats")
    if raw is None:
        return ["epub"] + (["pdf"] if book_pdf.pdf_engine() else [])
    if not isinstance(raw, list) or not all(isinstance(f, str) for f in raw):
        raise OutputError('parameters.formats must be a list of format names, e.g. ["epub", "pdf"].')
    wanted: set[str] = set()
    for name in raw:
        fmt = name.strip().lower()
        if fmt == "md":
            continue
        if fmt not in FILE_FORMATS:
            raise OutputError(f"A book can be downloaded as md, epub or pdf; {name!r} is not one of them.")
        wanted.add(fmt)
    return [f for f in FILE_FORMATS if f in wanted]


class BookMarkdownOutputter:
    """Deterministic-concatenation book outputter; one chapter per job."""

    kind = "book"

    def prepare_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        """Checked at POST time, before the row exists (S-6.1.5): resolve
        ``formats`` so the row records what will be built. A PDF with no
        engine raises ``OutputUnavailable`` (the router's 501)."""
        formats = requested_formats(params)
        if "pdf" in formats:
            book_pdf.require_engine()
        return {**params, "formats": ["md", *formats], "cohesion": book_cohesion.level_from(params)}

    def format_options(self) -> dict[str, Any]:
        """What ``GET /author/kinds`` reports for books: the formats this
        server can build, and why any other one cannot."""
        engine = book_pdf.pdf_engine()
        available = ["md", *FILE_FORMATS] if engine else ["md", "epub"]
        unavailable = {} if engine else {"pdf": book_pdf.unavailable_message()}
        return {"available": available, "unavailable": unavailable, "pdf_engine": engine}

    def _write_files(self, db: Session, output: Output, formats: list[str]) -> None:
        """Build the EPUB and/or PDF from the finished manuscript (S-6.1.5).
        A failure fails the whole output: the user asked for the file, and a
        book that silently lacks it would look complete."""
        if not formats:
            return
        book = book_html.render_book_html(output.content_text or "", title=output.title)
        if "epub" in formats:
            report_progress(db, output, 92, "Building the EPUB")
            epub = book_epub.build_epub(book, identifier=book_epub.book_identifier(output.id))
            output_artifacts.write_artifact(output, "epub", epub)
        if "pdf" in formats:
            report_progress(db, output, 95, "Printing the PDF")
            pdf = book_pdf.render_pdf(book_html.html_document(book))
            output_artifacts.write_artifact(output, "pdf", pdf)

    def estimate(self, db: Session, user: User, title: str, source_ids: list[str], params: dict[str, Any]) -> dict:
        """S-6.1.3 / T-6.1.3.5: what generating this book will cost, before
        it runs. Only the cohesion pass calls a model."""
        level = book_cohesion.level_from(params)
        return book_cohesion.estimate(_digests(db, user, source_ids), title, level)

    def generate(self, db: Session, user: User, output: Output) -> None:
        try:
            source_ids: list[str] = json.loads(output.source_ids_json or "[]")
            params: dict[str, Any] = json.loads(output.parameters_json or "{}")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OutputError(f"Malformed source_ids_json / parameters_json: {e}") from e

        if not source_ids:
            raise OutputError("Cannot generate a book with zero source IDs. Pass at least one job_id.")

        include_qa = bool(params.get("include_qa", True))
        include_toc = bool(params.get("include_toc", True))
        level = book_cohesion.level_from(params)
        # Before any chapter work: a PDF the worker cannot print fails now,
        # with what to install, not after the whole manuscript is built.
        formats = requested_formats(params)
        if "pdf" in formats:
            book_pdf.require_engine()

        # S-6.1.3: the cohesion pass reads digests of the chapters and may
        # reorder them; it never sees or rewrites the chapter bodies.
        cohesion = book_cohesion.plan(
            _digests(db, user, source_ids) if level != "none" else [],
            output.title,
            level,
            progress=lambda pct, message: report_progress(db, output, pct, message),
        )
        if level == "none":
            cohesion.order = list(range(1, len(source_ids) + 1))
        ordered_ids = [source_ids[n - 1] for n in cohesion.order]

        chapters: list[tuple[int, str, str]] = []  # (original number, title, body)
        citations: list[output_citation_service.CitationSpec] = []
        total = len(ordered_ids)
        for i, (number, jid) in enumerate(zip(cohesion.order, ordered_ids), start=1):
            # S-6.7.3 / S-6.1.4: chapters are written in reading order and
            # number their footnotes from where the previous one stopped, so
            # endnote n is output_citations position n.
            title, body, cited = _job_chapter(db, user, jid, include_qa=include_qa, start=len(citations) + 1)
            chapters.append((number, title, body))
            citations.extend(cited)
            # S-6.7.1: one progress step per chapter (10..90 %); also the
            # point where a user's cancel takes effect.
            report_progress(db, output, 10 + int(80 * i / total), f"Chapter {i} of {total}: {title}")

        output.content_text = _assemble(output.title, chapters, citations, cohesion, include_toc=include_toc)
        output.usage_json = json.dumps(cohesion.usage()) if cohesion.calls else None
        output_citation_service.record_citations(db, output, citations)
        self._write_files(db, output, formats)


# ---------------------------------------------------------------------------
# Manuscript assembly
# ---------------------------------------------------------------------------

_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
_LINK_IN_HEADING = re.compile(r"!?\[([^\]\n]*)\]\([^)\s]*\)")


def _digests(db: Session, user: User, source_ids: list[str]) -> list[book_cohesion.ChapterDigest]:
    """One digest per requested run, in the user's order. Same tenant scoping
    as the chapters themselves: another user's run reads as unknown."""
    out: list[book_cohesion.ChapterDigest] = []
    for n, jid in enumerate(source_ids, start=1):
        job = db.query(Job).filter(Job.id == jid, Job.tenant_id == user.id).first()
        if job is None:
            out.append(book_cohesion.digest(n, f"Unknown job {jid}", ""))
        else:
            out.append(book_cohesion.digest(n, (job.topic or "Untitled").strip(), _job_report_markdown(job)))
    return out


def _heading_text(line: str) -> str | None:
    m = _ATX_HEADING.match(line)
    if m is None:
        return None
    text = re.sub(r"\s+#+\s*$", "", m.group(3))
    return _LINK_IN_HEADING.sub(r"\1", text).strip()


def _heading_ids(lines: list[str], slug) -> dict[int, str]:
    """The id each heading line gets in the reader (and in the EPUB/PDF):
    the reader's slug with `-2`, `-3` for repeats, in document order, fenced
    code skipped. Keyed by line index."""
    ids: dict[int, str] = {}
    in_fence = False
    for idx, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        text = _heading_text(line)
        if text is not None:
            ids[idx] = slug(text)
    return ids


def _assemble(
    title: str,
    chapters: list[tuple[int, str, str]],
    citations: list[output_citation_service.CitationSpec],
    cohesion: "book_cohesion.Cohesion",
    *,
    include_toc: bool,
) -> str:
    """The manuscript. Chapter bodies go in untouched; everything a model
    wrote is framing around them and is disclosed in the front matter."""
    head: list[str] = [
        f"# {title}",
        "",
        f"_Authored by Pratidhvani Author Studio — {datetime.now(timezone.utc):%Y-%m-%d}_",
        "",
        f"_Compiled from {len(chapters)} source{'' if len(chapters) == 1 else 's'} in your library._",
        "",
    ]
    if cohesion.applied != "none":
        written = (
            "the introduction, chapter bridges, conclusion and glossary"
            if cohesion.applied == "full"
            else "the introduction, the chapter order and the chapter bridges"
        )
        head += [
            f"_About this edition: {written} were written by a model "
            f"({', '.join(cohesion.model_labels)}) from the chapters. Each chapter is its run's "
            "report, unchanged, with its own citations._",
            "",
        ]
    for note in cohesion.notes:
        head += [f"_Processing note: {note}_", ""]

    body: list[str] = []
    targets: list[tuple[str, int, str]] = []  # (kind, body line index, label)

    def heading(kind: str, text: str, label: str | None = None) -> None:
        targets.append((kind, len(body), label or text))
        body.extend([f"## {text}", ""])

    if cohesion.introduction:
        heading("extra", "Introduction")
        body.extend([cohesion.introduction, ""])

    part_of: dict[int, tuple[int, str]] = {}
    for p, (part_title, numbers) in enumerate(cohesion.parts):
        part_of[numbers[0]] = (p, part_title)

    for i, (number, ch_title, ch_body) in enumerate(chapters, start=1):
        if number in part_of:
            p, part_title = part_of[number]
            roman = _ROMAN[p] if p < len(_ROMAN) else str(p + 1)
            heading("part", f"Part {roman}: {part_title}")
        heading("chapter", f"{i}. {ch_title}", ch_title)
        bridge = cohesion.bridges.get(number)
        if bridge:
            body.extend([f"> {bridge}", ""])
        body.append(ch_body or "_(No content available for this source.)_")
        body.append("")

    if cohesion.conclusion:
        heading("extra", "Conclusion")
        body.extend([cohesion.conclusion, ""])
    if cohesion.glossary:
        heading("extra", "Glossary")
        body.extend([f"- **{term}** — {definition}" for term, definition in cohesion.glossary])
        body.append("")
    if citations:
        # GFM footnote definitions: the reader, GitHub and the EPUB/PDF
        # converters gather them into one numbered list under this heading.
        body.extend([f"## {book_html.ENDNOTES_HEADING}", ""])
        body.extend(output_citation_service.endnote_definitions(citations))
        body.append("")

    # Ids in document order, exactly as the reader assigns them (T-6.1.4.4):
    # the title, then the contents heading, then everything in the body. A
    # report's own "Conclusion" earlier in the book takes the plain id, so the
    # book's own sections cannot be linked by a guessed slug.
    slug = book_html.slugger()
    _heading_ids(head, slug)
    toc: list[str] = []
    if include_toc and chapters:
        slug(book_html.TOC_HEADING)
        ids = _heading_ids(body, slug)
        toc = [f"## {book_html.TOC_HEADING}", ""]
        chapter_no = 0
        # Chapters are one numbered list (its numbers continue across parts);
        # the book's own sections are bullets; a part is a bold line.
        previous = ""
        for kind, idx, label in targets:
            anchor = ids.get(idx, "")
            if kind != previous and toc[-1] != "":
                toc.append("")
            if kind == "chapter":
                chapter_no += 1
                toc.append(f"{chapter_no}. [{label}](#{anchor})")
            elif kind == "part":
                toc.extend([f"**[{label}](#{anchor})**", ""])
            else:
                toc.append(f"- [{label}](#{anchor})")
            previous = kind
        if toc[-1] != "":
            toc.append("")

    return "\n".join(head + toc + body).strip() + "\n"

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

The generated Markdown lands in ``output.content_text``. ``content_path``
stays None until PDF / EPUB (S-6.1.5).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.output import Output
from app.models.qa_exchange import QAExchange
from app.models.user import User
from app.services import report_service
from app.services.output_service import OutputError, report_progress

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


def _job_qa_markdown(db: Session, job_id: str, user_id: str) -> str:
    """The user's own Q&A exchanges on ``job_id`` as a Markdown subsection."""
    rows = (
        db.query(QAExchange)
        .filter(QAExchange.job_id == job_id, QAExchange.tenant_id == user_id)
        .order_by(QAExchange.created_at.asc())
        .all()
    )
    if not rows:
        return ""
    out = ["### Questions & Answers", ""]
    for i, r in enumerate(rows, start=1):
        out.append(f"**Q{i}.** {r.question.strip()}")
        out.append("")
        out.append((r.answer or "").strip())
        out.append("")
    return "\n".join(out).rstrip()


def _job_chapter(db: Session, user: User, job_id: str, *, include_qa: bool) -> tuple[str, str]:
    """Return ``(chapter_title, chapter_body_markdown)`` for one job."""
    # Tenant is part of the lookup (T-5.10.1.4): another user's job id
    # renders exactly like a missing one. Before 2026-10-19 the filter was
    # the id alone, so a book could compile someone else's report.
    job = db.query(Job).filter(Job.id == job_id, Job.tenant_id == user.id).first()
    if job is None:
        return f"Unknown job {job_id}", "_(Job not found in your library.)_"

    title = (job.topic or "Untitled").strip()
    parts = [_job_report_markdown(job)]
    if include_qa:
        qa_md = _job_qa_markdown(db, job.id, user.id)
        if qa_md:
            parts.append(qa_md)
    return title, "\n\n".join(p for p in parts if p)


class BookMarkdownOutputter:
    """Deterministic-concatenation book outputter; one chapter per job."""

    kind = "book"

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

        # Collect chapters first so the TOC can reference them.
        chapters: list[tuple[str, str, str]] = []
        total = len(source_ids)
        for i, jid in enumerate(source_ids, start=1):
            title, body = _job_chapter(db, user, jid, include_qa=include_qa)
            chapters.append((title, _slugify(title), body))
            # S-6.7.1: one progress step per chapter (10..90 %); also the
            # point where a user's cancel takes effect.
            report_progress(db, output, 10 + int(80 * i / total), f"Chapter {i} of {total}: {title}")

        manuscript: list[str] = [
            f"# {output.title}",
            "",
            f"_Authored by Pratidhvani Author Studio — {datetime.now(timezone.utc):%Y-%m-%d}_",
            "",
            f"_Compiled from {len(chapters)} source{'' if len(chapters) == 1 else 's'} in your library._",
            "",
        ]

        if include_toc and chapters:
            manuscript += ["## Table of Contents", ""]
            for i, (ch_title, ch_slug, _body) in enumerate(chapters, start=1):
                manuscript.append(f"{i}. [{ch_title}](#{ch_slug})")
            manuscript.append("")

        for i, (ch_title, _ch_slug, ch_body) in enumerate(chapters, start=1):
            manuscript += [f"## {i}. {ch_title}", ""]
            manuscript.append(ch_body or "_(No content available for this source.)_")
            manuscript.append("")

        output.content_text = "\n".join(manuscript).strip() + "\n"

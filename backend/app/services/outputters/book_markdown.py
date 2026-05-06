"""BookMarkdownOutputter — I-6 / E-6.1 v1.

Deterministic structural concatenation of selected job reports +
library Q&A history into a Markdown manuscript. No LLM involved in
v1 — this outputter validates the schema + lifecycle + REST surface
end-to-end. LLM-driven cohesion (chapter ordering, transition prose,
auto-generated introductions, glossary extraction) is a planned
follow-up under E-6.1.

Source IDs are interpreted as Job IDs (the user picks one or more
completed topic / channel jobs to assemble into the book). Each job
contributes a chapter; the chapter body is the job's report markdown
(or a stripped-down representation of its HTML report if no markdown
is on hand).

Parameters (``output.parameters_json``):
- ``include_qa`` (bool, default True) — append the job's Q&A history as
  a "Questions & Answers" subsection per chapter.
- ``include_toc`` (bool, default True) — generate a top-of-document
  table of contents.

The generated Markdown lands in ``output.content_text``. ``content_path``
is left None for v1 — PDF / EPUB conversion is a future PR.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.output import Output
from app.models.qa_exchange import QAExchange
from app.models.user import User
from app.services.output_service import OutputError

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").strip().lower())
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-") or "section"


def _strip_html_to_markdownish(html: str) -> str:
    """Best-effort HTML → Markdown-ish stripping. Not a real converter
    — for v1 we just remove the most common HTML tags so the output is
    readable as plain text. A future PR can swap in a real converter
    (markdownify / pandoc) when the LLM-cohesion step lands."""
    if not html:
        return ""
    # Drop scripts / styles entirely.
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Map common block tags to newline-bounded markers.
    s = re.sub(r"</?(p|div|section|article|li|tr|td|th|h[1-6])[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)  # remove remaining tags
    # Collapse whitespace runs.
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s.strip()


def _job_report_markdown(db: Session, job_id: str) -> str:
    """Best-effort extraction of a job's report content as
    Markdown-ish text. Today every job stores HTML at
    ``Job.report_path`` — we read it via ``report_service`` and strip
    HTML. Future: jobs can also persist a Markdown manuscript directly.
    """
    from app.models.job import Job
    from app.services import report_service

    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        return ""
    if not job.report_path:
        return f"_(Job ‘{job.topic}’ has no report; skipping.)_"
    try:
        html = report_service.get_report_html(job.report_path)
    except Exception:
        logger.exception(
            "BookMarkdownOutputter: failed to load report for job=%s",
            job_id,
        )
        return f"_(Failed to load report for job ‘{job.topic}’.)_"
    return _strip_html_to_markdownish(html)


def _job_qa_markdown(db: Session, job_id: str, user_id: str) -> str:
    """Format the user's Q&A exchanges for a given job as a
    Markdown-formatted Q&A section. Per-user filter so the book
    stays scoped to the requesting user's own questions."""
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


def _job_chapter(
    db: Session, user: User, job_id: str, *, include_qa: bool
) -> tuple[str, str]:
    """Return ``(chapter_title, chapter_body_markdown)`` for one job."""
    from app.models.job import Job

    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        return f"Unknown job {job_id}", "_(Job not found in your library.)_"

    title = (job.topic or "Untitled").strip()
    parts: list[str] = []
    parts.append(_job_report_markdown(db, job_id))
    if include_qa:
        qa_md = _job_qa_markdown(db, job_id, user.id)
        if qa_md:
            parts.append("")
            parts.append(qa_md)
    body = "\n\n".join(p for p in parts if p)
    return title, body


class BookMarkdownOutputter:
    """v1 deterministic-concatenation book outputter.

    Source IDs in ``output.source_ids_json`` are interpreted as Job
    IDs. Each job contributes one chapter.
    """

    kind = "book"

    def generate(
        self, db: Session, user: User, output: Output
    ) -> None:
        try:
            source_ids: list[str] = json.loads(output.source_ids_json or "[]")
            params: dict[str, Any] = json.loads(output.parameters_json or "{}")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OutputError(f"Malformed source_ids_json / parameters_json: {e}") from e

        if not source_ids:
            raise OutputError(
                "Cannot generate a book with zero source IDs. "
                "Pass at least one job_id."
            )

        include_qa = bool(params.get("include_qa", True))
        include_toc = bool(params.get("include_toc", True))

        # Collect chapters first so we can build a TOC referencing them.
        chapters: list[tuple[str, str, str]] = []
        for jid in source_ids:
            title, body = _job_chapter(db, user, jid, include_qa=include_qa)
            chapters.append((title, _slugify(title), body))

        manuscript: list[str] = []
        manuscript.append(f"# {output.title}")
        manuscript.append("")
        manuscript.append(f"_Authored by Pratidhvani Author Studio — {datetime.now(timezone.utc):%Y-%m-%d}_")
        manuscript.append("")
        manuscript.append(
            f"_Compiled from {len(chapters)} source"
            f"{'' if len(chapters) == 1 else 's'} in your library._"
        )
        manuscript.append("")

        if include_toc and chapters:
            manuscript.append("## Table of Contents")
            manuscript.append("")
            for i, (ch_title, ch_slug, _body) in enumerate(chapters, start=1):
                manuscript.append(f"{i}. [{ch_title}](#{ch_slug})")
            manuscript.append("")

        for i, (ch_title, ch_slug, ch_body) in enumerate(chapters, start=1):
            manuscript.append(f"## {i}. {ch_title}")
            manuscript.append("")
            manuscript.append(ch_body or "_(No content available for this source.)_")
            manuscript.append("")

        output.content_text = "\n".join(manuscript).strip() + "\n"

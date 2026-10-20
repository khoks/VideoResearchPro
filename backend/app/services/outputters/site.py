"""SiteOutputter — I-6 / E-6.2 (S-6.2.1): a static personal wiki, zipped.

``source_ids`` name shelves and runs: ``shelf:<id>``, ``job:<id>`` (a bare
id is a run). Everything resolves inside the caller's own library: their
shelves, their runs, the documents visible to them (D-063), their tags and
their Q&A. Another user's id reads like one that does not exist, and the
site says it was left out.

The zip holds plain HTML built in-process with Jinja2 (the plan rejects a Node
static-site generator inside the worker):

    index.html      contents: reports, tags, sources
    reports/*.html  one per run: its report and Q&A, citations as endnotes
                    that link both to the moment in the video and to the
                    source's own page
    sources/*.html  one per document: the reports citing it (backlinks), its
                    tags, its knowledge report when one was extracted
    tags/*.html     one per tag on the site's sources
    about.html, search.html
    assets/         one stylesheet, the search script, the search index

It opens from disk: links are relative, the search index is a script rather
than JSON (browsers will not load JSON from a page opened from disk), and nothing is loaded from
anywhere. The only absolute links go to the sources. No model is called.
"""
from __future__ import annotations

import io
import json
import logging
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.output import Output
from app.models.user import User
from app.services import output_artifacts, output_citation_service, report_service, shelf_service, tag_service, visibility_service
from app.services.output_service import OutputError, report_progress
from app.services.outputters import book_html
from app.services.outputters.book_markdown import _demote_headings, _job_qa_markdown

logger = logging.getLogger(__name__)

TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "site"
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\s]*\)")


def _ascii_slug(text: str, unique: str) -> str:
    """A file name every unzip tool accepts: ASCII letters and digits, plus a
    short id so two pages with the same title cannot collide."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    stem = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:50].strip("-")
    tail = re.sub(r"[^A-Za-z0-9]", "", unique)[:8].lower() or "x"
    return f"{stem}-{tail}" if stem else tail


def _plain(markdown: str) -> str:
    text = _LINK.sub(r"\1", markdown or "")
    text = re.sub(r"\[\^\d+\]", "", text)
    text = re.sub(r"[#*_>`|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class _Report:
    job: Job
    path: str
    markdown: str = ""
    specs: list[output_citation_service.CitationSpec] = field(default_factory=list)


@dataclass
class _Source:
    document: Document
    path: str
    channel: str = ""
    cited_in: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # report path -> [(clock, url)]


class SiteOutputter:
    kind = "site"

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _jobs(self, db: Session, user: User, source_ids: list[str]) -> tuple[list[Job], list[str]]:
        jobs: list[Job] = []
        notes: list[str] = []
        seen: set[str] = set()

        def add(job: Job | None, ref: str) -> None:
            if job is None:
                notes.append(f"{ref} is not in your library and was left out.")
                return
            if job.id in seen:
                return
            seen.add(job.id)
            if not job.report_path:
                notes.append(f"The run ‘{job.topic or job.id}’ has no report and was left out.")
                return
            jobs.append(job)

        for raw in source_ids:
            ref = str(raw).strip()
            if ref.startswith("shelf:"):
                shelf = shelf_service.get_shelf(db, ref[6:], user.id)
                if shelf is None:
                    notes.append(f"Shelf {ref[6:]} is not in your library and was left out.")
                    continue
                for job in shelf_service.shelf_jobs(db, shelf):
                    add(job if job.tenant_id == user.id else None, f"A run on ‘{shelf.name}’")
                continue
            jid = ref[4:] if ref.startswith("job:") else ref
            add(db.query(Job).filter(Job.id == jid, Job.tenant_id == user.id).first(), f"Run {jid}")
        return jobs, notes

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, db: Session, user: User, output: Output) -> None:
        try:
            source_ids: list[str] = json.loads(output.source_ids_json or "[]")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OutputError(f"Malformed source_ids_json: {e}") from e
        if not source_ids:
            raise OutputError("A site needs at least one shelf or run: source_ids is empty.")

        report_progress(db, output, 10, "Collecting the runs")
        jobs, notes = self._jobs(db, user, source_ids)
        if not jobs:
            raise OutputError("Nothing to publish: none of the chosen shelves or runs has a report in your library.")

        visible = visibility_service.visible_document_ids(db, user.id)  # a subquery, composed into IN
        reports = [_Report(job=j, path=f"reports/{_ascii_slug(j.topic or 'report', j.id)}.html") for j in jobs]
        documents: dict[str, Document] = {}
        for r in reports:
            for doc in (
                db.query(Document)
                .join(JobVideo, JobVideo.document_id == Document.document_id)
                .filter(JobVideo.job_id == r.job.id, Document.document_id.in_(visible))
                .all()
            ):
                documents.setdefault(doc.document_id, doc)
        channels = {c.channel_id: c.name for c in db.query(Channel).filter(
            Channel.channel_id.in_({d.channel_id for d in documents.values() if d.channel_id})).all()}
        sources = {
            doc_id: _Source(document=doc, path=f"sources/{_ascii_slug(doc.title, doc_id)}.html",
                            channel=channels.get(doc.channel_id, "") if doc.channel_id else "")
            for doc_id, doc in documents.items()
        }

        report_progress(db, output, 30, "Writing the report pages")
        candidates = list(documents.values())
        all_specs: list[output_citation_service.CitationSpec] = []
        for i, r in enumerate(reports, start=1):
            md = self._report_markdown(r.job)
            cited, specs = output_citation_service.cite_markdown(md, candidates, 1)
            qa_md, qa_specs = _job_qa_markdown(db, r.job.id, user.id, candidates, len(specs) + 1)
            if qa_md:
                cited += "\n\n" + qa_md.replace("### Questions & Answers", "## Questions & Answers", 1)
                specs += qa_specs
            r.markdown, r.specs = cited, specs
            all_specs.extend(specs)
            for spec in specs:
                if spec.document_id in sources:
                    clock = output_citation_service.clock(spec.seconds) if spec.seconds is not None else ""
                    moments = sources[spec.document_id].cited_in.setdefault(r.path, [])
                    if spec.url and (clock, spec.url) not in moments:
                        moments.append((clock, spec.url))
            report_progress(db, output, 30 + int(40 * i / len(reports)), f"Report {i} of {len(reports)}")

        report_progress(db, output, 75, "Writing the source and tag pages")
        tags = tag_service.tags_for_documents(db, user.id, list(sources))
        files = self._render(output, reports, sources, tags, notes)
        report_progress(db, output, 95, "Packing the site")
        output_artifacts.write_artifact(output, "zip", _zip(files))
        output.content_text = _contents_markdown(output.title, reports, sources, notes)
        output_citation_service.record_citations(db, output, all_specs)

    def _report_markdown(self, job: Job) -> str:
        try:
            md = report_service.report_markdown(job)
        except Exception:  # noqa: BLE001 — disclosed on the page
            logger.exception("SiteOutputter: report conversion failed for job=%s", job.id)
            return "_(The report could not be read.)_"
        if md is None:
            return "_(The report file is missing.)_"
        return _demote_headings(md, 0)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self, output: Output, reports: list[_Report], sources: dict[str, _Source],
                tags: dict[str, list[dict]], notes: list[str]) -> dict[str, bytes]:
        env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
        generated = f"{datetime.now(timezone.utc):%Y-%m-%d}"
        site_title = output.title
        files: dict[str, bytes] = {}

        def page(path: str, template: str, **ctx) -> None:
            depth = path.count("/")
            root = "../" * depth
            html = env.get_template(template).render(root=root, site_title=site_title, generated=generated, **ctx)
            files[path] = html.encode("utf-8")

        def rel(from_path: str, to_path: str) -> str:
            return posixpath.relpath(to_path, posixpath.dirname(from_path) or ".")

        tag_pages: dict[str, dict] = {}
        for doc_id, doc_tags in tags.items():
            for t in doc_tags:
                entry = tag_pages.setdefault(t["id"], {"name": t["name"], "path": f"tags/{_ascii_slug(t['name'], t['id'])}.html", "docs": []})
                entry["docs"].append(doc_id)

        search: list[dict] = []
        for r in reports:
            body_md = r.markdown + _site_endnotes(r, sources, rel)
            book = book_html.render_book_html(body_md, title=r.job.topic or "Report")
            n_docs = len({s.document_id for s in r.specs if s.document_id})
            meta = f"Research run of {r.job.created_at:%Y-%m-%d}" if r.job.created_at else "Research run"
            meta += f" · cites {n_docs} source{'' if n_docs == 1 else 's'}"
            page(r.path, "report.html", page_title=r.job.topic or "Report", title=r.job.topic or "Report", meta=meta, body=Markup(book.body))
            search.append({"t": r.job.topic or "Report", "u": r.path, "k": "report", "x": _plain(r.markdown)[:20_000]})

        for doc_id, s in sources.items():
            doc = s.document
            knowledge = ""
            if doc.knowledge_report_md:
                knowledge = book_html.render_book_html(_demote_headings(doc.knowledge_report_md, 1), title=doc.title).body
            report_title = {r.path: (r.job.topic or "Report") for r in reports}
            meta = ", ".join(x for x in (s.channel, f"published {doc.published_at:%Y-%m-%d}" if doc.published_at else "") if x)
            page(
                s.path, "source.html", page_title=doc.title, title=doc.title, meta=meta, url=doc.url,
                tags=[{"name": t["name"], "href": rel(s.path, tag_pages[t["id"]]["path"])} for t in tags.get(doc_id, [])],
                cited_in=[{"title": report_title[p], "href": rel(s.path, p),
                           "moments": [{"clock": c or "link", "url": u} for c, u in moments]}
                          for p, moments in s.cited_in.items()],
                knowledge=Markup(knowledge) if knowledge else "",
            )
            search.append({"t": doc.title, "u": s.path, "k": "source", "x": _plain((doc.knowledge_report_md or "")[:20_000])})

        for t in tag_pages.values():
            docs = sorted((sources[d] for d in t["docs"]), key=lambda s: s.document.title.lower())
            page(t["path"], "tag.html", page_title=t["name"], title=t["name"],
                 sources=[{"title": s.document.title, "href": rel(t["path"], s.path), "meta": s.channel} for s in docs])

        ordered_sources = sorted(sources.values(), key=lambda s: s.document.title.lower())
        page(
            "index.html", "index.html", page_title="Contents",
            lede=f"{len(reports)} report{'' if len(reports) == 1 else 's'} and {len(sources)} source{'' if len(sources) == 1 else 's'} from a personal research library.",
            notes=notes,
            reports=[{"title": r.job.topic or "Report", "href": r.path,
                      "meta": f"{r.job.created_at:%Y-%m-%d}" if r.job.created_at else ""} for r in reports],
            tags=[{"name": t["name"], "href": t["path"], "count": len(t["docs"])} for t in sorted(tag_pages.values(), key=lambda t: t["name"].lower())],
            sources=[{"title": s.document.title, "href": s.path, "meta": s.channel} for s in ordered_sources],
        )
        page("about.html", "about.html", page_title="About", report_count=len(reports), source_count=len(sources), notes=notes)
        page("search.html", "search.html", page_title="Search")

        css = book_html.stylesheet("book.css") + "\n" + (TEMPLATES / "assets" / "site-layout.css").read_text(encoding="utf-8")
        files["assets/site.css"] = css.encode("utf-8")
        files["assets/search.js"] = (TEMPLATES / "assets" / "search.js").read_bytes()
        index_js = "window.SITE_INDEX = " + json.dumps(search, ensure_ascii=False).replace("</", "<\\/") + ";\n"
        files["assets/search-index.js"] = index_js.encode("utf-8")
        return files


def _site_endnotes(report: _Report, sources: dict[str, _Source], rel) -> str:
    """GFM footnote definitions for a report page: the source's own page on
    this site, then the moment in the original."""
    if not report.specs:
        return ""
    lines = ["", "", f"## {book_html.ENDNOTES_HEADING}", ""]
    for n, spec in enumerate(report.specs, start=1):
        clock = output_citation_service.clock(spec.seconds) if spec.seconds is not None else ""
        if spec.document_id in sources:
            s = sources[spec.document_id]
            where = f" — {s.channel}" if s.channel else ""
            moment = f", [{clock}]({spec.url})" if clock and spec.url else (f", <{spec.url}>" if spec.url else "")
            lines.append(f"[^{n}]: [*{output_citation_service._md_text(s.document.title)}*]({rel(report.path, s.path)}){where}{moment}.")
        elif spec.url:
            title = output_citation_service._md_text(spec.title or spec.label)
            lines.append(f"[^{n}]: *{title}*{', ' + clock if clock else ''}. <{spec.url}>")
        else:
            lines.append(f"[^{n}]: Source not identified (cited as {output_citation_service._md_text(spec.label)}).")
    return "\n".join(lines) + "\n"


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files, key=lambda n: (n != "index.html", n)):
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), files[name], compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _contents_markdown(title: str, reports: list[_Report], sources: dict[str, _Source], notes: list[str]) -> str:
    """What the reading room shows for a site: its contents, as Markdown."""
    out = [f"# {title}", "", f"_A static site of {len(reports)} report{'' if len(reports) == 1 else 's'} and {len(sources)} source{'' if len(sources) == 1 else 's'}. Download the zip and open index.html._", ""]
    for note in notes:
        out += [f"_Processing note: {note}_", ""]
    out += ["## Reports", ""] + [f"- {r.job.topic or 'Report'} (`{r.path}`)" for r in reports] + [""]
    out += ["## Sources", ""] + [f"- [{s.document.title}]({s.document.url})" if s.document.url else f"- {s.document.title}"
                                  for s in sorted(sources.values(), key=lambda s: s.document.title.lower())]
    return "\n".join(out).strip() + "\n"

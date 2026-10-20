"""NewsletterOutputter — I-6 / E-6.4 (S-6.4.1): a digest of the user's library.

An issue covers a window ``(since, until]`` and lists, deterministically from
the database, what is new to THIS reader in it:

- ``library``: documents that entered their library (visibility grants, D-063,
  so a shared document counts when this reader first got it);
- ``knowledge``: knowledge reports extracted for their documents;
- ``questions``: questions they asked (job, library and history Q&A);
- ``saved_searches``: saved searches whose answer changed (S-8.3.3);
- ``outputs``: books, decks and sites they made.

One model call, ``author_newsletter_compose``, writes the ``featured``
deep-dive about ONE source from their own library. A report or knowledge
report from the window is preferred. Otherwise the least recently featured
one is resurfaced (the Readwise pattern the plan names: the digest brings the
reader's own library back). The call sees the source with its citations as
markers. Markers become links, and a section citing nothing it was given is
replaced by the source's own summary. A failed call is disclosed, never
fatal (D-056).

**Nothing new means no issue.** When every enabled list is empty the output
ends ``skipped`` (``OutputSkipped``), with the reason as its progress message.
A resurfaced featured item alone is not news.

Parameters: ``since`` / ``until`` (ISO 8601, UTC; ``since`` defaults to the
reader's last issue, else seven days back; ``until`` to now) and
``sections`` (a dict of the names above to booleans; unknown names are
refused). The resolved window and the featured source are written back into
the row's parameters so the row records what the issue covered.

Artifacts: ``content_text`` is the issue as Markdown (the reading room, the
email's plain-text part), and ``artifact.html`` is the email: table layout,
inline styles, no external CSS or images, links absolute to the app.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from lxml import html as lxml_html
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.agents.prompts import newsletter_prompts
from app.config import settings
from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.output import Output
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.models.saved_search import SavedSearch
from app.models.saved_search_run import SavedSearchRun
from app.models.user import User
from app.services import cost_estimator, output_artifacts, output_citation_service
from app.services.output_service import OutputError, OutputSkipped, report_progress
from app.services.outputters import book_cohesion, book_html
from app.services.outputters.book_markdown import _chapter_documents, _job_report_markdown
from app.services.outputters.deck import _marked

logger = logging.getLogger(__name__)

USE_CASE = "author_newsletter_compose"
SECTIONS = ("featured", "library", "knowledge", "questions", "saved_searches", "outputs")
LIST_SECTIONS = SECTIONS[1:]
DEFAULT_WINDOW = timedelta(days=7)
MAX_ITEMS = 20
EXCERPT_WORDS = 1_200
FEATURED_MAX_WORDS = 300
MAX_TOKENS = 6_000
OUTPUT_TOKENS_EST = 1_500  # calibrated on real issues; see estimate()
TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "newsletter"

_MARKER = re.compile(r"\s*\[S(\d+)\]")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\s]*\)")


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def _naive_utc(value: Any, name: str) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as e:
        raise OutputError(f"{name} must be an ISO 8601 date-time; got {value!r}.") from e
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def sections_from(params: dict[str, Any]) -> dict[str, bool]:
    raw = params.get("sections")
    out = {name: True for name in SECTIONS}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise OutputError('sections must be an object, e.g. {"featured": false}.')
    unknown = sorted(set(raw) - set(SECTIONS))
    if unknown:
        raise OutputError(f"Unknown newsletter sections {unknown}; known: {list(SECTIONS)}.")
    for name, on in raw.items():
        out[name] = bool(on)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _link(path: str) -> str:
    return settings.APP_BASE_URL.rstrip("/") + path


def _short(text: str | None, words: int) -> str:
    plain = _LINK.sub(r"\1", text or "")
    plain = re.sub(r"\[\^\d+\]|[#*_>`]", "", plain)
    parts = plain.split()
    return " ".join(parts[:words]) + (" …" if len(parts) > words else "")


def _md(text: str) -> str:
    return output_citation_service._md_text(text or "")


# ---------------------------------------------------------------------------
# What is new
# ---------------------------------------------------------------------------


@dataclass
class Item:
    title: str
    href: str
    detail: str = ""


@dataclass
class Section:
    key: str
    heading: str
    items: list[Item] = field(default_factory=list)
    total: int = 0


def _window(q, column, since: datetime, until: datetime):
    return q.filter(column > since, column <= until)


def _library(db: Session, user: User, since: datetime, until: datetime) -> Section:
    rows = (
        _window(db.query(Document, DocumentVisibility.created_at).join(
            DocumentVisibility, DocumentVisibility.document_id == Document.document_id
        ).filter(DocumentVisibility.tenant_id == user.id), DocumentVisibility.created_at, since, until)
        .order_by(DocumentVisibility.created_at.desc())
        .all()
    )
    channels = {c.channel_id: c.name for c in db.query(Channel).filter(
        Channel.channel_id.in_({d.channel_id for d, _ in rows if d.channel_id})).all()}
    items = []
    for doc, _at in rows[:MAX_ITEMS]:
        bits = [channels.get(doc.channel_id, "") if doc.channel_id else ""]
        if doc.published_at:
            bits.append(f"published {doc.published_at:%Y-%m-%d}")
        items.append(Item(doc.title, _link(f"/library?document={doc.document_id}"), ", ".join(b for b in bits if b)))
    return Section("library", "New in your library", items, len(rows))


def _knowledge(db: Session, user: User, since: datetime, until: datetime) -> Section:
    rows = (
        _window(db.query(Document).join(DocumentVisibility, DocumentVisibility.document_id == Document.document_id)
                .filter(DocumentVisibility.tenant_id == user.id, Document.knowledge_report_md.isnot(None)),
                Document.knowledge_extracted_at, since, until)
        .order_by(Document.knowledge_extracted_at.desc())
        .all()
    )
    items = [Item(d.title, _link(f"/library?document={d.document_id}&view=knowledge"), _short(d.knowledge_report_md, 24))
             for d in rows[:MAX_ITEMS]]
    return Section("knowledge", "New knowledge reports", items, len(rows))


def _questions(db: Session, user: User, since: datetime, until: datetime) -> Section:
    found: list[tuple[datetime, Item]] = []
    for ex, topic in (
        _window(db.query(QAExchange, Job.topic).join(Job, Job.id == QAExchange.job_id)
                .filter(QAExchange.tenant_id == user.id), QAExchange.created_at, since, until).all()
    ):
        found.append((ex.created_at, Item(ex.question.strip(), _link(f"/jobs/{ex.job_id}"),
                                          f"in “{topic or 'a run'}”: {_short(ex.answer, 30)}")))
    for ex in _window(db.query(LibraryQAExchange).filter(LibraryQAExchange.tenant_id == user.id),
                      LibraryQAExchange.created_at, since, until).all():
        found.append((ex.created_at, Item(ex.question.strip(), _link("/library/qa"), f"across your library: {_short(ex.answer, 30)}")))
    for ex in _window(db.query(QAHistoryExchange).filter(QAHistoryExchange.tenant_id == user.id),
                      QAHistoryExchange.created_at, since, until).all():
        found.append((ex.created_at, Item(ex.question.strip(), _link("/qa-history"), f"across your past answers: {_short(ex.answer, 30)}")))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return Section("questions", "Questions you asked", [i for _, i in found[:MAX_ITEMS]], len(found))


def _saved_searches(db: Session, user: User, since: datetime, until: datetime) -> Section:
    rows = (
        _window(db.query(SavedSearchRun, SavedSearch.question).join(SavedSearch, SavedSearch.id == SavedSearchRun.saved_search_id)
                .filter(SavedSearchRun.tenant_id == user.id, SavedSearch.tenant_id == user.id, SavedSearchRun.changed.is_(True)),
                SavedSearchRun.ran_at, since, until)
        .order_by(SavedSearchRun.ran_at.desc())
        .all()
    )
    items = [Item(question.strip(), _link(f"/saved-searches?search={run.saved_search_id}&run={run.id}"),
                  _short(run.diff_summary, 40)) for run, question in rows[:MAX_ITEMS]]
    return Section("saved_searches", "Saved searches with new answers", items, len(rows))


def _outputs(db: Session, user: User, since: datetime, until: datetime, exclude: str) -> Section:
    rows = (
        _window(db.query(Output).filter(Output.user_id == user.id, Output.status == "completed",
                                        Output.kind != "newsletter", Output.id != exclude), Output.updated_at, since, until)
        .order_by(Output.updated_at.desc())
        .all()
    )
    items = [Item(o.title, _link(f"/author/outputs/{o.id}"), o.kind) for o in rows[:MAX_ITEMS]]
    return Section("outputs", "What you made", items, len(rows))


# ---------------------------------------------------------------------------
# Featured
# ---------------------------------------------------------------------------


@dataclass
class Featured:
    ref: str  # "job:<id>" or "document:<id>"
    kind: str  # "report" | "knowledge report"
    title: str
    href: str
    text: str  # the source as the model sees it, with [S#] markers
    links: dict[int, tuple[str, str]]  # marker -> (label, url)
    specs: dict[int, output_citation_service.CitationSpec] = field(default_factory=dict)
    resurfaced: bool = False
    headline: str = ""
    body: str = ""
    written_by: str | None = None  # model, or None for the source's own summary
    note: str = ""
    cited: list[int] = field(default_factory=list)


def _featured_history(db: Session, user: User) -> dict[str, datetime]:
    """When each source was last featured, from the reader's past issues."""
    seen: dict[str, datetime] = {}
    for params, at in db.query(Output.parameters_json, Output.created_at).filter(
        Output.user_id == user.id, Output.kind == "newsletter", Output.status == "completed"
    ).all():
        try:
            ref = json.loads(params or "{}").get("featured_ref")
        except ValueError:
            continue
        if ref and (ref not in seen or at > seen[ref]):
            seen[ref] = at
    return seen


def _pick_featured(db: Session, user: User, since: datetime, until: datetime) -> Featured | None:
    reports = (
        db.query(Job).filter(Job.tenant_id == user.id, Job.status == "completed", Job.report_path.isnot(None))
        .order_by(Job.created_at.desc()).all()
    )
    knowledge = (
        db.query(Document).join(DocumentVisibility, DocumentVisibility.document_id == Document.document_id)
        .filter(DocumentVisibility.tenant_id == user.id, Document.knowledge_report_md.isnot(None))
        .order_by(Document.knowledge_extracted_at.desc()).all()
    )
    fresh = [("job", j, j.completed_at or j.created_at) for j in reports
             if (j.completed_at or j.created_at) and since < (j.completed_at or j.created_at) <= until]
    fresh += [("document", d, d.knowledge_extracted_at) for d in knowledge
              if d.knowledge_extracted_at and since < d.knowledge_extracted_at <= until]
    fresh.sort(key=lambda t: t[2], reverse=True)
    chosen = fresh[0] if fresh else None
    resurfaced = False
    if chosen is None:
        # Resurface: the source featured longest ago (never featured first,
        # then oldest), so a quiet week still brings something back.
        history = _featured_history(db, user)
        pool = [("job", j, history.get(f"job:{j.id}")) for j in reports]
        pool += [("document", d, history.get(f"document:{d.document_id}")) for d in knowledge]
        if not pool:
            return None
        pool.sort(key=lambda t: (t[2] is not None, t[2] or datetime.min))
        chosen, resurfaced = pool[0], True
    kind, obj, _ = chosen
    return _featured_source(db, user, kind, obj, resurfaced)


def _featured_source(db: Session, user: User, kind: str, obj, resurfaced: bool) -> Featured | None:
    if kind == "job":
        md = _job_report_markdown(obj)
        if md.startswith("_("):
            return None
        cited, specs = output_citation_service.cite_markdown(md, _chapter_documents(db, user, obj.id), 1)
        by_n = dict(enumerate(specs, start=1))
        marked = _marked(cited, by_n)
        text = book_cohesion.digest(1, obj.topic or "Report", marked).excerpt(EXCERPT_WORDS)
        links = {
            n: (output_citation_service.clock(s.seconds) if s.seconds is not None else "source", s.url)
            for n, s in by_n.items() if s.url
        }
        return Featured(ref=f"job:{obj.id}", kind="report", title=obj.topic or "Report", href=_link(f"/jobs/{obj.id}"),
                        text=text, links=links, specs={n: by_n[n] for n in links}, resurfaced=resurfaced)
    doc: Document = obj
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", doc.knowledge_report_md or "") if p.strip()]
    words, kept = 0, []
    for p in paragraphs:
        kept.append(f"{p} [S1]")
        words += len(p.split())
        if words >= EXCERPT_WORDS:
            break
    url = doc.url or _link(f"/library?document={doc.document_id}")
    spec = output_citation_service.CitationSpec(
        label=doc.title, href=url, url=url, seconds=None, document_id=doc.document_id,
        source_type=doc.source_type, source_id=doc.video_id, resolved_by="document", title=doc.title)
    return Featured(ref=f"document:{doc.document_id}", kind="knowledge report", title=doc.title,
                    href=_link(f"/library?document={doc.document_id}&view=knowledge"),
                    text="\n\n".join(kept), links={1: ("source", url)}, specs={1: spec}, resurfaced=resurfaced)


def _linkify(text: str, featured: Featured) -> tuple[str, list[int]]:
    """``[S4]`` markers to Markdown links; unknown markers dropped."""
    cited: list[int] = []

    def sub(m: re.Match) -> str:
        n = int(m.group(1))
        if n not in featured.links:
            return ""
        if n not in cited:
            cited.append(n)
        label, url = featured.links[n]
        return f" ([{label}]({url}))"

    return _MARKER.sub(sub, text), cited


def _fallback(featured: Featured) -> None:
    """The source's own summary, when the model's section is unusable: its
    first paragraph that cites something, so the fallback is sourced too."""
    paragraphs = [p for p in featured.text.split("\n") if p.strip() and not p.startswith("[")]
    first = next((p for p in paragraphs if _MARKER.search(p)), paragraphs[0] if paragraphs else "")
    words = first.split()
    text = " ".join(words[:120]) + (" …" if len(words) > 120 else "")
    featured.headline = featured.title
    featured.body, featured.cited = _linkify(text, featured)
    featured.written_by = None


def _compose(featured: Featured, invoke) -> book_cohesion.CallUsage | None:
    raw_text = ""

    def parse(text: str) -> dict:
        nonlocal raw_text
        raw_text = text
        return {"ok": True}

    _ok, call = book_cohesion._call(
        USE_CASE, newsletter_prompts.FEATURED_SYSTEM,
        newsletter_prompts.featured_user_prompt(featured.kind, featured.title, featured.text),
        MAX_TOKENS, invoke, parse=parse,
    )
    if not call.ok:
        featured.note = f"The featured section could not be written ({call.error}); it shows the {featured.kind}'s own summary instead."
        _fallback(featured)
        return call
    lines = [ln for ln in raw_text.strip().splitlines()]
    headline = book_cohesion._single_paragraph(re.sub(r"^#+\s*", "", lines[0] if lines else ""), 14)
    body_raw = "\n".join(lines[1:]) if len(lines) > 1 else ""
    # Clean everything but the markers, then turn markers into links.
    body = book_cohesion.clean_prose(body_raw, FEATURED_MAX_WORDS)
    linked, cited = _linkify(body, featured)
    if not cited:
        featured.note = f"The model's featured section cited nothing from the {featured.kind}, so it shows the {featured.kind}'s own summary instead."
        _fallback(featured)
        return call
    featured.headline = _MARKER.sub("", headline) or featured.title
    featured.body, featured.cited, featured.written_by = linked, cited, call.model
    return call


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Inline styles for the email, by tag (no <style> block survives every
# client). The palette is docs/branding.md's light theme.
_EMAIL_STYLES = {
    "h1": "font-family:Georgia,serif;font-size:26px;line-height:1.2;color:#1f1b16;margin:0 0 6px;",
    "h2": "font-family:Georgia,serif;font-size:19px;line-height:1.3;color:#7a2c1a;margin:26px 0 8px;",
    "h3": "font-family:Georgia,serif;font-size:16px;color:#1f1b16;margin:18px 0 6px;",
    "p": "font-family:Georgia,serif;font-size:15px;line-height:1.6;color:#1f1b16;margin:0 0 12px;",
    "ul": "margin:0 0 12px;padding-left:20px;",
    "li": "font-family:Georgia,serif;font-size:15px;line-height:1.5;color:#1f1b16;margin:0 0 8px;",
    "a": "color:#7a2c1a;text-decoration:underline;",
    "em": "color:#5c5448;",
    "strong": "color:#1f1b16;",
    "blockquote": "margin:0 0 12px;padding:0 0 0 12px;border-left:3px solid #d8cfc0;color:#5c5448;",
}


def _inline_styles(body_html: str) -> str:
    root = lxml_html.fragment_fromstring(body_html, create_parent="div")
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag in _EMAIL_STYLES:
            el.set("style", _EMAIL_STYLES[el.tag])
            el.attrib.pop("class", None)
            el.attrib.pop("id", None)
    return "".join(lxml_html.tostring(child, encoding="unicode") for child in root)


def _period(since: datetime, until: datetime) -> str:
    if since.year == until.year:
        return f"{since:%d %b} to {until:%d %b %Y}"
    return f"{since:%d %b %Y} to {until:%d %b %Y}"


def _markdown(title: str, since: datetime, until: datetime, featured: Featured | None,
              sections: list[Section], notes: list[str]) -> str:
    out = [f"# {_md(title)}", "", f"_Your library from {_period(since, until)} (UTC)._", ""]
    for note in notes:
        out += [f"_Processing note: {_md(note)}_", ""]
    if featured and featured.body:
        lead = "From your library" if featured.resurfaced else "Featured"
        out += [f"## {lead}: {_md(featured.headline)}", "", featured.body, ""]
        credit = (f"written by a model ({featured.written_by}) from the {featured.kind}; every sentence links to its source"
                  if featured.written_by else f"the {featured.kind}'s own summary")
        out += [f"_From [{_md(featured.title)}]({featured.href}): {credit}._", ""]
    for s in sections:
        if not s.items:
            continue
        out += [f"## {s.heading} ({s.total})", ""]
        for it in s.items:
            line = f"- [{_md(it.title)}]({it.href})"
            if it.detail:
                line += f" — {_md(it.detail)}"
            out.append(line)
        if s.total > len(s.items):
            out.append(f"- …and {s.total - len(s.items)} more")
        out.append("")
    out += [f"_Change what this digest includes, or turn it off, on the [Author page]({_link('/author')})._"]
    return "\n".join(out).strip() + "\n"


def render_email(title: str, markdown: str) -> str:
    body = book_html.render_book_html(markdown, title=title).body
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    return env.get_template("email.html").render(title=title, body=Markup(_inline_styles(body)))


# ---------------------------------------------------------------------------
# The outputter
# ---------------------------------------------------------------------------


class NewsletterOutputter:
    kind = "newsletter"

    def prepare_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        since = _naive_utc(params.get("since"), "since")
        until = _naive_utc(params.get("until"), "until")
        if since and until and since >= until:
            raise OutputError("since must be before until.")
        return {**params, "sections": sections_from(params)}

    def estimate(self, db: Session, user: User, title: str, source_ids: list[str], params: dict[str, Any]) -> dict:
        if not sections_from(params)["featured"]:
            return {"calls": [], "cost_usd": 0.0}
        since, until = self._window(db, user, params, exclude="")
        featured = _pick_featured(db, user, since, until)
        if featured is None:
            return {"calls": [], "cost_usd": 0.0}
        prompt = newsletter_prompts.FEATURED_SYSTEM + newsletter_prompts.featured_user_prompt(featured.kind, featured.title, featured.text)
        return cost_estimator.estimate_calls([(USE_CASE, book_cohesion._tokens(prompt, USE_CASE), OUTPUT_TOKENS_EST)])

    def _window(self, db: Session, user: User, params: dict[str, Any], exclude: str) -> tuple[datetime, datetime]:
        until = _naive_utc(params.get("until"), "until") or _now()
        since = _naive_utc(params.get("since"), "since")
        if since is None:
            last = (
                db.query(Output.created_at).filter(Output.user_id == user.id, Output.kind == "newsletter",
                                                   Output.status == "completed", Output.id != exclude)
                .order_by(Output.created_at.desc()).first()
            )
            since = last[0] if last and last[0] and last[0] < until else until - DEFAULT_WINDOW
        if since >= until:
            raise OutputError("since must be before until.")
        return since, until

    def generate(self, db: Session, user: User, output: Output, *, invoke=None) -> None:
        try:
            params: dict[str, Any] = json.loads(output.parameters_json or "{}")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OutputError(f"Malformed parameters_json: {e}") from e
        enabled = sections_from(params)
        since, until = self._window(db, user, params, exclude=output.id)

        report_progress(db, output, 15, "Collecting what is new")
        builders = {
            "library": lambda: _library(db, user, since, until),
            "knowledge": lambda: _knowledge(db, user, since, until),
            "questions": lambda: _questions(db, user, since, until),
            "saved_searches": lambda: _saved_searches(db, user, since, until),
            "outputs": lambda: _outputs(db, user, since, until, exclude=output.id),
        }
        sections = [builders[name]() for name in LIST_SECTIONS if enabled[name]]
        if not any(s.total for s in sections):
            raise OutputSkipped(f"Nothing new from {_period(since, until)}; no issue was made.")

        notes: list[str] = []
        featured = None
        call = None
        if enabled["featured"]:
            report_progress(db, output, 45, "Writing the featured section")
            featured = _pick_featured(db, user, since, until)
            if featured is not None:
                call = _compose(featured, invoke or book_cohesion._default_invoke)
                if featured.note:
                    notes.append(featured.note)

        report_progress(db, output, 85, "Laying out the issue")
        markdown = _markdown(output.title, since, until, featured, sections, notes)
        output.content_text = markdown
        output_artifacts.write_artifact(output, "html", render_email(output.title, markdown))
        output.parameters_json = json.dumps({
            **params,
            "sections": enabled,
            "since": since.isoformat() + "Z",
            "until": until.isoformat() + "Z",
            "featured_ref": featured.ref if featured and featured.body else None,
            "counts": {s.key: s.total for s in sections},
        })
        if call is not None:
            output.usage_json = json.dumps({
                "calls": [call.as_dict()],
                "input_tokens": call.input_tokens or 0,
                "output_tokens": call.output_tokens or 0,
                "cost_usd": call.cost_usd,
            })
        output_citation_service.record_citations(
            db, output, [featured.specs[n] for n in featured.cited if n in featured.specs] if featured else []
        )

"""DeckOutputter — I-6 / E-6.3 (S-6.3.1, S-6.3.2): a slide deck from research
runs and knowledge reports.

Source IDs are the caller's own job ids (bare or ``job:<id>``), as for books,
and since S-6.3.2 ``document:<id>`` for a document in the caller's library
(D-063) with an extracted knowledge report. Each run's report Markdown
(S-6.1.2) has its citations resolved against the run's visible documents
(`output_citation_service.cite_markdown`, S-6.1.4); the model then sees the
report with every RESOLVED citation as a marker ``[S12]`` and nothing else
that looks like a source. A knowledge report is about one document and cites
no moments, so the document is its one source: every paragraph and list
item carries that document's marker. One ``author_deck_outline`` call plans
the slides and cites them by marker.

A ``document:`` source the caller cannot see, or one with no knowledge
report, is refused by ``check_sources`` before the row exists (404 / 409 at
the router). One that stops qualifying before the worker reads it is left
out and disclosed, like a run with no report.

What the deck guarantees, whatever the model returns:
- every bullets or quote slide cites at least one source the reports gave
  it; a slide that cites none is dropped and the deck says how many;
- sources are numbered by first use across the slides, listed with links on
  the closing sources slide(s), in full in each slide's notes, and recorded
  as ``output_citations`` (position n is source n);
- the text is cleaned of links, markers and footnotes.

Artifacts: the PPTX (``content_path``) and a Markdown rendering of the same
deck in ``content_text`` for the reading room and search. ``usage_json``
records the call.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agents.prompts import deck_prompts
from app.agents.prompts.knowledge_prompts import source_profile
from app.config import settings
from app.models.document import Document
from app.models.job import Job
from app.models.output import Output
from app.models.user import User
from app.services import cost_estimator, output_artifacts, output_citation_service, visibility_service
from app.services.output_service import OutputError, OutputSourceNotFound, OutputSourceNotReady, report_progress
from app.services.outputters import book_cohesion, deck_render
from app.services.outputters.book_markdown import _chapter_documents, _job_report_markdown

logger = logging.getLogger(__name__)

USE_CASE = "author_deck_outline"
MAX_TOKENS = 20_000
OUTPUT_TOKENS_EST = 8_000  # two real two-run decks billed 4,801 and 7,553 (reasoning included)
MIN_SLIDES, MAX_SLIDES = 3, 15
MAX_BULLETS, BULLET_MAX_WORDS, HEADING_MAX_WORDS = 5, 30, 12
NOTES_MAX_WORDS, QUOTE_MAX_WORDS = 180, 60
# The whole input budget for the reports, in characters, shared between runs.
REPORT_CHARS_BUDGET = 240_000

_CITED_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)\[\^(\d+)\]")
_FOOTNOTE = re.compile(r"\[\^(\d+)\]")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\s]*\)")
_MARKER = re.compile(r"\[S\d+\]")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s|$)")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s")
_ABSOLUTE = re.compile(r"^https?://", re.I)

DOCUMENT_REF, JOB_REF = "document:", "job:"


def _ref(source_id: Any) -> tuple[str, str]:
    """``("document", id)`` for ``document:<id>`` (S-6.3.2); ``("job", id)``
    for ``job:<id>`` or a bare id, which is what decks took before."""
    s = str(source_id or "").strip()
    if s.startswith(DOCUMENT_REF):
        return "document", s[len(DOCUMENT_REF):].strip()
    if s.startswith(JOB_REF):
        return "job", s[len(JOB_REF):].strip()
    return "job", s


def _visible_document(db: Session, user: User, document_id: str) -> Document | None:
    """The document, when it is in the caller's library (D-063). Keyed on the
    primary key alone (D-070): a legacy YouTube id is not a document id."""
    if not document_id:
        return None
    return (
        db.query(Document)
        .filter(
            Document.document_id == document_id,
            Document.document_id.in_(visibility_service.visible_document_ids(db, user.id)),
        )
        .first()
    )


def _has_knowledge(doc: Document) -> bool:
    return bool((doc.knowledge_report_md or "").strip())


def _knowledge_marked(markdown: str, n: int) -> str:
    """A knowledge report as the model sees it (S-6.3.2). It describes one
    document and cites no moments, so that document is its only source:
    every paragraph and list item ends with the marker ``[Sn]``, headings and
    rules carry none. Links become their labels, and any marker or footnote
    already in the text is removed, so the model can cite nothing but the
    one source the sources slide links."""
    text = _MARKER.sub("", _FOOTNOTE.sub("", _LINK.sub(r"\1", markdown or "")))
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        is_text = bool(line.strip()) and not _HEADING.match(line) and not _RULE.match(line)
        ends_unit = not nxt.strip() or bool(_HEADING.match(nxt)) or bool(_LIST_ITEM.match(nxt))
        out.append(f"{line.rstrip()} [S{n}]" if is_text and ends_unit else line)
    return "\n".join(out).strip()


def _document_spec(doc: Document) -> output_citation_service.CitationSpec:
    """The citation a knowledge report gives: its document, linked where the
    source lives (the video, the article). A source with no public address
    (an uploaded PDF is served only to signed-in readers, by a relative
    path) links to its knowledge report in the app instead."""
    url = output_citation_service.timestamp_href(doc, None)
    if not url or not _ABSOLUTE.match(url):
        url = f"{settings.APP_BASE_URL.rstrip('/')}/knowledge/{doc.document_id}"
    return output_citation_service.CitationSpec(
        label=(doc.title or "Knowledge report")[:255],
        href=url,
        url=url,
        seconds=None,
        document_id=doc.document_id,
        source_type=doc.source_type or "video",
        source_id=doc.source_id,
        resolved_by="document",
        title=doc.title or None,
        channel=doc.channel_name or None,
    )


def _about(doc: Document) -> str:
    """What the source is, for the knowledge report's header in the prompt:
    ``a YouTube video, published 2025-03-02``. The date anchors the report's
    "as of" claims (TEMPORAL_AWARENESS)."""
    noun = source_profile(doc.source_type).noun
    article = "an" if noun[:1].lower() in "aeiou" else "a"
    when = f", published {doc.published_at:%Y-%m-%d}" if doc.published_at else ""
    return f"{article} {noun}{when}"


@dataclass
class _Material:
    reports: list[tuple[str, ...]] = field(default_factory=list)
    specs: dict[int, output_citation_service.CitationSpec] = field(default_factory=dict)
    missing_runs: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    runs: int = 0
    knowledge: int = 0
    asked_documents: bool = False


def _marked(markdown: str, specs: dict[int, output_citation_service.CitationSpec]) -> str:
    """The report as the model sees it: a resolved citation becomes ``label
    [Sn]``; an unresolved one keeps its label and loses its marker, so a slide
    can only cite something the sources slide can link."""

    def linked(m: re.Match) -> str:
        n = int(m.group(3))
        return f"{m.group(1)} [S{n}]" if specs.get(n) and specs[n].url else m.group(1)

    def bare(m: re.Match) -> str:
        n = int(m.group(1))
        return f" [S{n}]" if specs.get(n) and specs[n].url else ""

    text = _CITED_LINK.sub(linked, markdown)
    text = _FOOTNOTE.sub(bare, text)
    return _LINK.sub(r"\1", text)


def _clean(text: Any, max_words: int) -> str:
    return _MARKER.sub("", book_cohesion._single_paragraph(text, max_words)).strip()


def _source_numbers(raw: Any, valid: set[int]) -> list[int]:
    out: list[int] = []
    for v in raw if isinstance(raw, list) else []:
        try:
            n = int(str(v).lstrip("Ss"))
        except ValueError:
            continue
        if n in valid and n not in out:
            out.append(n)
    return out


class DeckOutputter:
    kind = "deck"

    def check_sources(self, db: Session, user: User, source_ids: list[str]) -> None:
        """S-6.3.2: refuse a ``document:`` source before the row exists. One
        the caller cannot see reads exactly like one that does not exist
        (404, D-063); one with no knowledge report yet is 409. Runs are not
        checked here: as before, a run with no report is left out at
        generation and the deck says so."""
        for raw in source_ids:
            kind, ident = _ref(raw)
            if kind != "document":
                continue
            doc = _visible_document(db, user, ident)
            if doc is None:
                raise OutputSourceNotFound(f"Document {ident or '(empty id)'} is not in your library.")
            if not _has_knowledge(doc):
                raise OutputSourceNotReady(
                    f"“{doc.title or doc.document_id}” has no knowledge report yet. "
                    "Extract one from the library first, then make the deck."
                )

    def _material(self, db: Session, user: User, source_ids: list[str]) -> _Material:
        m = _Material()
        budget = REPORT_CHARS_BUDGET // max(1, len(source_ids))
        for raw in source_ids:
            kind, ident = _ref(raw)
            if kind == "document":
                m.asked_documents = True
                doc = _visible_document(db, user, ident)
                if doc is None or not _has_knowledge(doc):
                    m.missing_documents.append(ident)
                    continue
                n = len(m.specs) + 1
                m.specs[n] = _document_spec(doc)
                m.reports.append(((doc.title or "Untitled").strip(), _knowledge_marked(doc.knowledge_report_md, n)[:budget], _about(doc)))
                m.knowledge += 1
                continue
            job = db.query(Job).filter(Job.id == ident, Job.tenant_id == user.id).first()
            if job is None or not job.report_path:
                m.missing_runs.append(ident)
                continue
            md = _job_report_markdown(job)
            if md.startswith("_("):  # the disclosed placeholder for a missing report
                m.missing_runs.append(ident)
                continue
            cited, cited_specs = output_citation_service.cite_markdown(md, _chapter_documents(db, user, job.id), len(m.specs) + 1)
            for i, spec in enumerate(cited_specs, start=len(m.specs) + 1):
                m.specs[i] = spec
            m.reports.append(((job.topic or "Untitled").strip(), _marked(cited, m.specs)[:budget]))
            m.runs += 1
        return m

    def estimate(self, db: Session, user: User, title: str, source_ids: list[str], params: dict[str, Any]) -> dict:
        material = self._material(db, user, source_ids)
        if not material.reports:
            return {"calls": [], "cost_usd": 0.0}
        prompt = deck_prompts.DECK_SYSTEM + deck_prompts.deck_user_prompt(title, material.reports)
        return cost_estimator.estimate_calls([(USE_CASE, book_cohesion._tokens(prompt, USE_CASE), OUTPUT_TOKENS_EST)])

    def generate(self, db: Session, user: User, output: Output) -> None:
        try:
            source_ids: list[str] = json.loads(output.source_ids_json or "[]")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OutputError(f"Malformed source_ids_json: {e}") from e
        if not source_ids:
            raise OutputError("A deck needs at least one run or knowledge report: source_ids is empty.")

        report_progress(db, output, 10, "Reading the sources")
        material = self._material(db, user, source_ids)
        specs = material.specs
        if not material.reports:
            if material.asked_documents:
                raise OutputError("None of the chosen runs or documents has a report this deck can be built from.")
            raise OutputError("None of the chosen runs has a report this deck can be built from.")

        report_progress(db, output, 25, "Planning the slides")
        raw, call = book_cohesion._call(
            USE_CASE, deck_prompts.DECK_SYSTEM, deck_prompts.deck_user_prompt(output.title, material.reports), MAX_TOKENS,
            book_cohesion._default_invoke,
        )
        output.usage_json = json.dumps({
            "calls": [call.as_dict()],
            "input_tokens": call.input_tokens or 0,
            "output_tokens": call.output_tokens or 0,
            "cost_usd": call.cost_usd,
        })
        if raw is None:
            raise OutputError(f"The slide outline call failed ({call.error}).")

        report_progress(db, output, 70, "Building the slides")
        deck, cited_specs, dropped = self._deck(output, raw, specs, call.model, material.runs, material.knowledge)
        notes = []
        if dropped:
            notes.append(f"{dropped} planned slide{'' if dropped == 1 else 's'} cited no source and {'was' if dropped == 1 else 'were'} left out.")
        missing = material.missing_runs
        if missing:
            notes.append(f"{len(missing)} chosen run{'' if len(missing) == 1 else 's'} had no report and {'was' if len(missing) == 1 else 'were'} left out.")
        gone = material.missing_documents
        if gone:
            notes.append(
                f"{len(gone)} chosen document{'' if len(gone) == 1 else 's'} had no knowledge report in your library "
                f"and {'was' if len(gone) == 1 else 'were'} left out."
            )
        deck.notes = notes

        output_artifacts.write_artifact(output, "pptx", deck_render.render(deck))
        output.content_text = _markdown(deck)
        output_citation_service.record_citations(db, output, cited_specs)

    def _deck(self, output: Output, raw: dict, specs: dict, model: str, runs: int, knowledge: int = 0):
        valid = {n for n, s in specs.items() if s.url}
        slides: list[deck_render.DeckSlide] = []
        dropped = 0
        for entry in raw.get("slides") or []:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("type") or "bullets").lower()
            if kind == "section":
                heading = _clean(entry.get("heading"), HEADING_MAX_WORDS)
                if heading:
                    slides.append(deck_render.DeckSlide("section", heading=heading, notes=_clean(entry.get("speaker_notes"), NOTES_MAX_WORDS)))
                continue
            cited = _source_numbers(entry.get("citations"), valid)
            if not cited:
                dropped += 1
                continue
            notes = _clean(entry.get("speaker_notes"), NOTES_MAX_WORDS)
            if kind == "quote" and _clean(entry.get("quote"), QUOTE_MAX_WORDS):
                slides.append(deck_render.DeckSlide(
                    "quote", quote=_clean(entry.get("quote"), QUOTE_MAX_WORDS),
                    attribution=_clean(entry.get("attribution"), 16), notes=notes, sources=cited))
                continue
            bullets = [b for b in (_clean(x, BULLET_MAX_WORDS) for x in (entry.get("bullets") or [])[:MAX_BULLETS]) if b]
            heading = _clean(entry.get("heading"), HEADING_MAX_WORDS)
            if not bullets or not heading:
                dropped += 1
                continue
            slides.append(deck_render.DeckSlide("bullets", heading=heading, bullets=bullets, notes=notes, sources=cited))

        # Sections with nothing after them are noise; content is capped.
        while slides and slides[-1].kind == "section":
            slides.pop()
        content = [s for s in slides if s.kind != "section"]
        if len(content) > MAX_SLIDES:
            keep = set(id(s) for s in content[:MAX_SLIDES])
            slides = [s for s in slides if s.kind == "section" or id(s) in keep]
        if not any(s.kind != "section" for s in slides):
            raise OutputError("The slide outline had no slide citing a source it was given; nothing to show.")

        # Sources are DOCUMENTS (a video cited at five moments is one source
        # with five links), numbered by first use; slides refer to those
        # numbers. output_citations keeps one row per cited moment, in order
        # of first use. A real two-run deck listed 80 timestamped entries over
        # ten slides before this grouping (S-6.3.1 trial, 2026-10-19).
        marker_order: list[int] = []
        doc_number: dict[str, int] = {}
        sources: list[deck_render.DeckSource] = []
        for s in slides:
            numbers: list[int] = []
            moments: dict[int, list[tuple[str, str]]] = {}
            for marker in s.sources:
                spec = specs[marker]
                if marker not in marker_order:
                    marker_order.append(marker)
                key = spec.document_id or output_citation_service.url_key(spec.url) or spec.url
                if key not in doc_number:
                    doc_number[key] = len(sources) + 1
                    sources.append(deck_render.DeckSource(
                        number=doc_number[key], title=_title_for(spec), channel=spec.channel or "", url=spec.url))
                n = doc_number[key]
                moment = (output_citation_service.clock(spec.seconds) if spec.seconds is not None else "", spec.url)
                if moment not in sources[n - 1].moments:
                    sources[n - 1].moments.append(moment)
                if n not in numbers:
                    numbers.append(n)
                if moment not in moments.setdefault(n, []):
                    moments[n].append(moment)
            s.sources, s.moments = numbers, moments
        cited_specs = [specs[n] for n in marker_order]
        for src in sources:  # a source's moments in time order, not citation order
            src.moments.sort(key=lambda m: _seconds(m[0]))
        byline, disclosure = deck_render.byline(runs, model, knowledge=knowledge)
        deck = deck_render.Deck(
            title=_clean(raw.get("title"), 14) or output.title,
            subtitle=_clean(raw.get("subtitle"), 24),
            byline=byline,
            slides=slides,
            sources=sources,
            disclosure=disclosure,
        )
        return deck, cited_specs, dropped


def _seconds(clock: str) -> int:
    """"1:02:03" / "7:57" back to seconds; an empty clock sorts last."""
    if not clock:
        return 10**9
    total = 0
    for part in clock.split(":"):
        total = total * 60 + (int(part) if part.isdigit() else 0)
    return total


_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/)([\w-]{11})")


def _title_for(spec: output_citation_service.CitationSpec) -> str:
    """The source's title; a link nothing in the library matched still gets
    a recognisable name instead of its timestamp label."""
    if spec.title:
        return spec.title
    m = _VIDEO_ID.search(spec.url or "")
    return f"YouTube video {m.group(1)}" if m else (spec.url or spec.label)


def _markdown(deck: deck_render.Deck) -> str:
    out = [f"# {deck.title}", ""]
    if deck.subtitle:
        out += [f"_{deck.subtitle}_", ""]
    out += [f"_{deck.byline}_", "", f"_{deck.disclosure}_", ""]
    for note in deck.notes:
        out += [f"_Processing note: {note}_", ""]
    for i, s in enumerate(deck.slides, start=2):
        if s.kind == "section":
            out += [f"## {s.heading}", ""]
            continue
        refs = "".join(f"[^{n}]" for n in s.sources)
        if s.kind == "quote":
            out += [f"### Slide {i}: quote", "", f"> {s.quote}{refs}", ">", f"> — {s.attribution}", ""]
        else:
            out += [f"### Slide {i}: {s.heading}", ""]
            out += [f"- {b}" for b in s.bullets]
            out[-1] += refs
            out.append("")
        if s.notes:
            out += [f"_Notes: {s.notes}_", ""]
    out += ["## Sources", ""]
    for src in deck.sources:
        moments = ", ".join(f"[{clock}]({url})" if clock else f"<{url}>" for clock, url in src.moments) or f"<{src.url}>"
        out.append(f"[^{src.number}]: *{src.title}*{' — ' + src.channel if src.channel else ''}: {moments}.")
    return "\n".join(out).strip() + "\n"

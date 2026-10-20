"""DeckOutputter — I-6 / E-6.3 (S-6.3.1): a slide deck from research runs.

Source IDs are the caller's own job ids, as for books. Each run's report
Markdown (S-6.1.2) has its citations resolved against the run's visible
documents (`output_citation_service.cite_markdown`, S-6.1.4); the model then
sees the report with every RESOLVED citation as a marker ``[S12]`` and nothing
else that looks like a source. One ``author_deck_outline`` call plans the
slides and cites them by marker.

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
from typing import Any

from sqlalchemy.orm import Session

from app.agents.prompts import deck_prompts
from app.models.job import Job
from app.models.output import Output
from app.models.user import User
from app.services import cost_estimator, output_artifacts, output_citation_service
from app.services.output_service import OutputError, report_progress
from app.services.outputters import book_cohesion, deck_render
from app.services.outputters.book_markdown import _chapter_documents, _job_report_markdown

logger = logging.getLogger(__name__)

USE_CASE = "author_deck_outline"
MAX_TOKENS = 20_000
OUTPUT_TOKENS_EST = 6_000  # measured on the S-6.3.1 trial deck; see estimate()
MIN_SLIDES, MAX_SLIDES = 3, 15
MAX_BULLETS, BULLET_MAX_WORDS, HEADING_MAX_WORDS = 5, 30, 12
NOTES_MAX_WORDS, QUOTE_MAX_WORDS = 180, 60
# The whole input budget for the reports, in characters, shared between runs.
REPORT_CHARS_BUDGET = 240_000

_CITED_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)\[\^(\d+)\]")
_FOOTNOTE = re.compile(r"\[\^(\d+)\]")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\s]*\)")
_MARKER = re.compile(r"\[S\d+\]")


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

    def _material(self, db: Session, user: User, source_ids: list[str]):
        reports: list[tuple[str, str]] = []
        specs: dict[int, output_citation_service.CitationSpec] = {}
        missing: list[str] = []
        budget = REPORT_CHARS_BUDGET // max(1, len(source_ids))
        for jid in source_ids:
            job = db.query(Job).filter(Job.id == jid, Job.tenant_id == user.id).first()
            if job is None or not job.report_path:
                missing.append(jid)
                continue
            md = _job_report_markdown(job)
            if md.startswith("_("):  # the disclosed placeholder for a missing report
                missing.append(jid)
                continue
            cited, cited_specs = output_citation_service.cite_markdown(md, _chapter_documents(db, user, job.id), len(specs) + 1)
            for i, spec in enumerate(cited_specs, start=len(specs) + 1):
                specs[i] = spec
            reports.append(((job.topic or "Untitled").strip(), _marked(cited, specs)[:budget]))
        return reports, specs, missing

    def estimate(self, db: Session, user: User, title: str, source_ids: list[str], params: dict[str, Any]) -> dict:
        reports, _specs, _missing = self._material(db, user, source_ids)
        if not reports:
            return {"calls": [], "cost_usd": 0.0}
        prompt = deck_prompts.DECK_SYSTEM + deck_prompts.deck_user_prompt(title, reports)
        return cost_estimator.estimate_calls([(USE_CASE, book_cohesion._tokens(prompt, USE_CASE), OUTPUT_TOKENS_EST)])

    def generate(self, db: Session, user: User, output: Output) -> None:
        try:
            source_ids: list[str] = json.loads(output.source_ids_json or "[]")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise OutputError(f"Malformed source_ids_json: {e}") from e
        if not source_ids:
            raise OutputError("A deck needs at least one run: source_ids is empty.")

        report_progress(db, output, 10, "Reading the runs")
        reports, specs, missing = self._material(db, user, source_ids)
        if not reports:
            raise OutputError("None of the chosen runs has a report this deck can be built from.")

        report_progress(db, output, 25, "Planning the slides")
        raw, call = book_cohesion._call(
            USE_CASE, deck_prompts.DECK_SYSTEM, deck_prompts.deck_user_prompt(output.title, reports), MAX_TOKENS,
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
        deck, cited_specs, dropped = self._deck(output, raw, specs, call.model, len(reports))
        notes = []
        if dropped:
            notes.append(f"{dropped} planned slide{'' if dropped == 1 else 's'} cited no source and {'was' if dropped == 1 else 'were'} left out.")
        if missing:
            notes.append(f"{len(missing)} chosen run{'' if len(missing) == 1 else 's'} had no report and {'was' if len(missing) == 1 else 'were'} left out.")
        deck.notes = notes

        output_artifacts.write_artifact(output, "pptx", deck_render.render(deck))
        output.content_text = _markdown(deck)
        output_citation_service.record_citations(db, output, cited_specs)

    def _deck(self, output: Output, raw: dict, specs: dict, model: str, runs: int):
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
            raise OutputError("The slide outline had no slide citing a source from the runs; nothing to show.")

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
        byline, disclosure = deck_render.byline(runs, model)
        deck = deck_render.Deck(
            title=_clean(raw.get("title"), 14) or output.title,
            subtitle=_clean(raw.get("subtitle"), 24),
            byline=byline,
            slides=slides,
            sources=sources,
            disclosure=disclosure,
        )
        return deck, cited_specs, dropped


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

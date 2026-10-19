"""Citations of Author Studio outputs (S-6.7.3 / E-6.7).

Every outputter records what it cites through ``record_citations`` so a book,
a deck and a site cite the same way and the endnotes (S-6.1.4), a sources
slide (S-6.3.1) or a site's backlinks read one table, `output_citations`.

Markdown outputs (the book) find their citations with
``extract_markdown_citations``. Its resolver is a port of the reading
room's (`frontend/src/components/reader/citations.ts`, S-8.8.2), so a link
resolves to the same source in the reader and in a book:

1. the YouTube id in the href (every report since S-1.14.9);
2. the href itself against each candidate document's URL;
3. for older reports, whose anchors carry only ``&t=123``, a known title
   (longest first, at least 8 characters) or else a channel with exactly
   one candidate document, found in the text around the link.

Candidates are the documents the caller passes, which for a book chapter
are that run's documents **visible to the tenant**; a link is never resolved
to a document the user cannot see. A bare anchor nothing could be tied to is
recorded with no URL rather than given an invented one.

S-6.1.4 adds the endnote side: ``cite_markdown`` rewrites each citation into
a working link plus a GFM footnote reference numbered in output order
(``[0:42](https://…&t=42)[^7]``; an unresolved anchor keeps its label and
loses the dead link), ``cite_references`` cites a Q&A answer from its stored
references instead of re-parsing its prose, and ``endnote_definitions``
writes the ``[^n]: Title — Channel, 0:42. <url>`` lines. Endnote ``n`` is
always ``output_citations.position`` ``n``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.output import Output
from app.models.output_citation import OutputCitation

# A Markdown link, not an image. The title part (`"…"`) is optional.
_LINK = re.compile(r'(?<!!)\[(?P<label>[^\]\n]*)\]\((?P<href>[^)\s]+)(?:\s+"[^"]*")?\)')
_CITATION_T = re.compile(r"(?:^|[?&#])t=(\d+)")
_YOUTUBE_ID = re.compile(r"[?&]v=([\w-]{11})")
_ABSOLUTE = re.compile(r"^https?://", re.I)
_GARBAGE = re.compile(r'[\s<>"]')
_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s")
_BLANK_LINES = re.compile(r"\n[ \t]*\n")

MIN_TITLE_CHARS = 8
CONTEXT_MAX_CHARS = 1200


@dataclass
class CitationSpec:
    label: str
    href: str | None
    url: str | None
    seconds: int | None
    document_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    resolved_by: str | None = None
    # For the endnote text only; not stored (the row keeps `document_id`).
    title: str | None = None
    channel: str | None = None


# ---------------------------------------------------------------------------
# Resolution (port of the reader's)
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub("[​-‍﻿]", "", text)
    return re.sub(r"\s+", " ", text.lower()).strip()


def _title_stem(title: str) -> str:
    return _fold(re.split(r"\s[|#]|#", title or "")[0])


def url_key(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("t", "start")]
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{parts.path.rstrip('/')}?{urlencode(query)}"


def timestamp_href(doc: Document, seconds: int | None) -> str | None:
    """Link to a source at a timestamp, per source kind (the reader's rule)."""
    kind = doc.source_type or "video"
    t = seconds if seconds is not None and seconds > 0 else None
    if kind == "video" and doc.video_id:
        return f"https://www.youtube.com/watch?v={doc.video_id}" + (f"&t={t}" if t is not None else "")
    base = doc.source_url or doc.url
    if not base:
        return None
    if kind == "podcast_episode" and t is not None:
        return f"{base}#t={t}"
    return base


class _Resolver:
    def __init__(self, candidates: Iterable[Document]):
        self.by_video_id: dict[str, Document] = {}
        self.by_url: dict[str, Document] = {}
        titled: list[tuple[str, Document]] = []
        by_channel: dict[str, list[Document]] = {}
        for doc in candidates:
            if doc.video_id:
                self.by_video_id[doc.video_id] = doc
            for u in (doc.url, doc.source_url):
                key = url_key(u)
                if key:
                    self.by_url[key] = doc
            full = _fold(doc.title)
            stem = _title_stem(doc.title)
            if len(full) >= MIN_TITLE_CHARS:
                titled.append((full, doc))
            if len(stem) >= MIN_TITLE_CHARS and stem != full:
                titled.append((stem, doc))
            channel = _fold(doc.channel_name)
            if channel:
                by_channel.setdefault(channel, []).append(doc)
        # Longest needle first, so "Part 2" titles beat their "Part 1" prefix.
        self.titled = sorted(titled, key=lambda pair: -len(pair[0]))
        self.sole_by_channel = sorted(
            ((name, docs[0]) for name, docs in by_channel.items() if len(docs) == 1),
            key=lambda pair: -len(pair[0]),
        )

    def find(self, href: str | None, video_id: str | None, contexts: Sequence[str]) -> tuple[Document | None, str | None]:
        if video_id and video_id in self.by_video_id:
            return self.by_video_id[video_id], "video_id"
        if href:
            key = url_key(href)
            if key and key in self.by_url:
                return self.by_url[key], "url"
            return None, None
        folded = [_fold(c) for c in contexts]
        for ctx in folded:
            for needle, doc in self.titled:
                if needle in ctx:
                    return doc, "title"
        for ctx in folded:
            for needle, doc in self.sole_by_channel:
                if needle in ctx:
                    return doc, "channel"
        return None, None


# ---------------------------------------------------------------------------
# Markdown extraction
# ---------------------------------------------------------------------------


def _blocks(markdown: str) -> list[tuple[int, int]]:
    """(start, end) spans of blank-line-separated blocks."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BLANK_LINES.finditer(markdown):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(markdown)))
    return spans


def _contexts(markdown: str, spans: list[tuple[int, int]], pos: int) -> list[str]:
    """The text around a link, nearest first, as the reader's `<p>` and
    `<li>` contexts:

    1. the list item (or paragraph) holding the link, inside its block: a
       tight list puts several items in one block, and an earlier item's
       title must not resolve a later item's anchor;
    2. when that text continues a loose list item from earlier blocks (the
       `**Source:**` paragraph under a `- **Fact:**` marker), the whole item
       from its marker line through the link's block.
    """
    idx = next((i for i, (s, e) in enumerate(spans) if s <= pos <= e), len(spans) - 1)
    start, end = spans[idx]
    lines = markdown[start:end].split("\n")
    offset, here = 0, 0
    for k, line in enumerate(lines):
        if offset + len(line) >= pos - start:
            here = k
            break
        offset += len(line) + 1
    first = next((k for k in range(here, -1, -1) if _LIST_ITEM.match(lines[k])), 0)
    last = next((k for k in range(here + 1, len(lines)) if _LIST_ITEM.match(lines[k])), len(lines))
    item = "\n".join(lines[first:last])
    whole = item
    if not _LIST_ITEM.match(lines[first]):
        # A continuation paragraph: reach back to the item's marker line.
        pieces = [item]
        for j in range(idx - 1, -1, -1):
            prev = markdown[spans[j][0] : spans[j][1]].split("\n")
            if prev and prev[0].lstrip().startswith("#"):
                break
            marker = next((k for k in range(len(prev) - 1, -1, -1) if _LIST_ITEM.match(prev[k])), None)
            if marker is not None:
                pieces.append("\n".join(prev[marker:]))
                break
            pieces.append("\n".join(prev))
        whole = "\n\n".join(reversed(pieces))
    return [item[-CONTEXT_MAX_CHARS:], whole[-CONTEXT_MAX_CHARS:]]


def _spec_for(m: re.Match, markdown: str, spans: list[tuple[int, int]], resolver: _Resolver) -> CitationSpec | None:
    """The citation one Markdown link makes, or None when it is not one
    (an intra-document anchor, a relative non-citation link)."""
    raw = m.group("href").strip()
    if raw.startswith("#"):
        return None
    t = _CITATION_T.search(raw)
    absolute = bool(_ABSOLUTE.match(raw)) and not _GARBAGE.search(raw)
    if not t and not absolute:
        return None
    seconds = int(t.group(1)) if t else None
    yt = _YOUTUBE_ID.search(raw) if absolute else None
    href = raw if absolute else None
    doc, by = resolver.find(href, yt.group(1) if yt else None, _contexts(markdown, spans, m.start()))
    url = href or (timestamp_href(doc, seconds) if doc is not None else None)
    label = m.group("label").strip() or (f"{seconds}s" if seconds is not None else raw)
    return CitationSpec(
        label=label[:255],
        href=raw,
        url=url,
        seconds=seconds,
        document_id=doc.document_id if doc is not None else None,
        source_type=(doc.source_type or "video") if doc is not None else ("url" if href else None),
        source_id=doc.source_id if doc is not None else None,
        resolved_by=by,
        title=doc.title if doc is not None else None,
        channel=(doc.channel_name or None) if doc is not None else None,
    )


def extract_markdown_citations(markdown: str, candidates: Iterable[Document]) -> list[CitationSpec]:
    """Every citation link in ``markdown``, in order, resolved against
    ``candidates``. Intra-document anchors (`#…`), images and relative
    non-citation links are not citations."""
    return cite_markdown(markdown, candidates)[1]


def _md_link_target(url: str) -> str:
    return f"<{url}>" if re.search(r"[\s()<>]", url) else url


def cite_markdown(markdown: str, candidates: Iterable[Document], start: int = 1) -> tuple[str, list[CitationSpec]]:
    """Rewrite every citation in ``markdown`` as a working link plus a
    footnote reference numbered from ``start`` (S-6.1.4), and return the
    rewritten text with the citations in order. A bare ``&t=`` anchor that
    resolved gets its rebuilt URL; one that did not keeps only its label, so
    the manuscript carries no dead link."""
    resolver = _Resolver(candidates)
    spans = _blocks(markdown)
    specs: list[CitationSpec] = []
    parts: list[str] = []
    last = 0
    for m in _LINK.finditer(markdown):
        spec = _spec_for(m, markdown, spans, resolver)
        if spec is None:
            continue
        n = start + len(specs)
        specs.append(spec)
        label = m.group("label").strip() or spec.label
        linked = f"[{label}]({_md_link_target(spec.url)})" if spec.url else label
        parts.append(markdown[last : m.start()])
        parts.append(f"{linked}[^{n}]")
        last = m.end()
    parts.append(markdown[last:])
    return "".join(parts), specs


def strip_links(markdown: str) -> str:
    """Links to their labels: Q&A prose cites through its stored
    references (``cite_references``), never through links parsed out of it."""
    return _LINK.sub(lambda m: m.group("label"), markdown)


def clock(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def cite_references(references: Sequence[dict], candidates: Iterable[Document], start: int = 1) -> tuple[str, list[CitationSpec]]:
    """Citations for one Q&A answer from its stored references (S-6.1.4,
    T-6.1.4.2). Returns ``"Sources: [0:30](url)[^n], …"`` (empty when there
    are none) and the citations in order. A reference resolves to a library
    document only when that document is among ``candidates``; otherwise it
    keeps its own absolute URL, title and channel, which came from the
    user's own exchange."""
    resolver = _Resolver(candidates)
    specs: list[CitationSpec] = []
    parts: list[str] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        url = ref.get("youtube_link") or ref.get("video_url") or ref.get("url") or None
        if url and (not _ABSOLUTE.match(url) or _GARBAGE.search(url)):
            url = None
        yt = _YOUTUBE_ID.search(url) if url else None
        video_id = ref.get("video_id") or (yt.group(1) if yt else None)
        doc, by = resolver.find(url, video_id, [])
        try:
            seconds = int(float(ref.get("timestamp_seconds"))) if ref.get("timestamp_seconds") is not None else None
        except (TypeError, ValueError):
            seconds = None
        if url is None and doc is not None:
            url = timestamp_href(doc, seconds)
        label = (ref.get("timestamp_display") or clock(seconds) or "source").strip()
        n = start + len(specs)
        specs.append(
            CitationSpec(
                label=label[:255],
                href=url,
                url=url,
                seconds=seconds,
                document_id=doc.document_id if doc is not None else None,
                source_type=(doc.source_type or "video") if doc is not None else ("url" if url else None),
                source_id=doc.source_id if doc is not None else None,
                resolved_by=by,
                title=(doc.title if doc is not None else ref.get("video_title")) or None,
                channel=((doc.channel_name or None) if doc is not None else ref.get("channel_name")) or None,
            )
        )
        parts.append((f"[{label}]({_md_link_target(url)})" if url else label) + f"[^{n}]")
    return ("Sources: " + ", ".join(parts)) if parts else "", specs


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>])")


def _md_text(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", re.sub(r"\s+", " ", text or "").strip())


def endnote_definitions(specs: Sequence[CitationSpec], start: int = 1) -> list[str]:
    """One GFM footnote definition per citation: ``[^n]: Title — Channel,
    0:42. <url>``. A citation no source matched says so instead of inventing
    one."""
    lines: list[str] = []
    for n, spec in enumerate(specs, start=start):
        bits: list[str] = []
        if spec.title:
            head = f"*{_md_text(spec.title)}*"
            if spec.channel:
                head += f" — {_md_text(spec.channel)}"
            bits.append(head)
        stamp = clock(spec.seconds) if spec.seconds else ""
        if spec.url:
            text = ", ".join(b for b in bits + ([stamp] if stamp else []) if b)
            lines.append(f"[^{n}]: {text + '. ' if text else ''}<{spec.url}>")
        else:
            label = _md_text(spec.label)
            lines.append(f"[^{n}]: Source not identified (cited as {label}).")
    return lines


def heading_slug(text: str) -> str:
    """The heading id the reading room gives ``text`` (a port of
    `frontend/src/components/reader/slug.ts`), so a book's table of contents
    links to ids that exist in the reader, in GitHub's renderer for these
    headings, and in the EPUB/PDF HTML."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = re.sub("[\u0300-\u036f]", "", folded).lower()
    kept = "".join(ch for ch in folded if unicodedata.category(ch)[0] in "LMN" or ch.isspace() or ch == "-")
    slug = re.sub(r"[\s_]+", "-", kept.strip())
    return re.sub(r"-+", "-", slug) or "section"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def record_citations(db: Session, output: Output, specs: Sequence[CitationSpec]) -> int:
    """Replace ``output``'s citations with ``specs``, numbered 1..n in order.
    Does not commit: the generation lifecycle commits with the content, so a
    failed or cancelled run leaves no rows."""
    db.query(OutputCitation).filter(OutputCitation.output_id == output.id).delete(synchronize_session=False)
    db.add_all(
        OutputCitation(
            output_id=output.id,
            position=i,
            label=spec.label,
            url=spec.url,
            seconds=spec.seconds,
            document_id=spec.document_id,
            source_type=spec.source_type,
            source_id=spec.source_id,
            resolved_by=spec.resolved_by,
        )
        for i, spec in enumerate(specs, start=1)
    )
    return len(specs)


def delete_citations(db: Session, output_id: str) -> None:
    db.query(OutputCitation).filter(OutputCitation.output_id == output_id).delete(synchronize_session=False)


def list_citations(db: Session, output: Output) -> list[tuple[OutputCitation, Document | None]]:
    return (
        db.query(OutputCitation, Document)
        .outerjoin(Document, Document.document_id == OutputCitation.document_id)
        .filter(OutputCitation.output_id == output.id)
        .order_by(OutputCitation.position.asc())
        .all()
    )


def counts_for(db: Session, output_ids: Iterable[str]) -> dict[str, int]:
    ids = list(output_ids)
    if not ids:
        return {}
    rows = (
        db.query(OutputCitation.output_id, func.count(OutputCitation.id))
        .filter(OutputCitation.output_id.in_(ids))
        .group_by(OutputCitation.output_id)
        .all()
    )
    return {output_id: n for output_id, n in rows}

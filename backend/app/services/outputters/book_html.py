"""Book manuscript Markdown -> HTML (S-6.1.5).

One HTML rendering of a book feeds both downloads: the EPUB writer
(`book_epub`) splits it into XHTML chapters and the PDF engines
(`book_pdf`) print it whole. Nothing here reaches the network.

- Parser: markdown-it-py (MIT) in CommonMark mode with GFM tables,
  strikethrough and footnotes (mdit-py-plugins, MIT). Raw HTML in the
  Markdown is **disabled**, so a report can never inject markup into a
  file the user opens in another program.
- Heading ids are the reading room's (`heading_slug`, duplicates `-2`,
  `-3`, as `slug.ts`). The book outputter reads its table of contents back
  from `Heading.line` here, so `#1-first-topic` is the id this renders, and
  the reader, running the same slug over the same headings, agrees.
- Endnotes are the GFM footnotes S-6.1.4 writes. Their references and the
  list get ARIA roles (`doc-noteref`, `doc-endnotes`, `doc-backlink`) and
  `data-epub-type` markers the EPUB writer turns into `epub:type`.
- Images are replaced by their alt text: a book carries no remote fetches
  (an EPUB would have to declare them, a PDF engine would have to fetch
  them, and a local path would read a file on the server).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lxml import html as lxml_html
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin

from app.services.output_citation_service import heading_slug

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Carries a heading's source line from the Markdown parser to the id pass, and
# no further: it is removed before the HTML leaves this module.
_LINE_ATTR = "data-source-line"

# Section headings the book outputter writes; the EPUB writer replaces the
# first with its navigation document and gives the second endnote semantics.
TOC_HEADING = "Table of Contents"
ENDNOTES_HEADING = "Endnotes"

# Characters XML 1.0 forbids. A transcript can carry them; an EPUB with one
# is not well-formed, so they are dropped before parsing.
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_FOOTNOTE_CAPTION = re.compile(r"^\[(\d+)\]$")
# What the parser records as a Setext heading's markup, where ATX has its `#`s.
_SETEXT_MARKUP = ("=", "-")


@dataclass(frozen=True)
class Heading:
    level: int
    id: str
    text: str
    # 0-based line of the Markdown this heading starts on.
    line: int


@dataclass(frozen=True)
class SourceHeading:
    """A heading outside any quote or list, by where it sits in the Markdown."""

    level: int
    # 0-based line it starts on, and the line after it (past a Setext underline).
    line: int
    end: int
    setext: bool


@dataclass(frozen=True)
class BookHtml:
    """A rendered manuscript: the body as an HTML fragment, its headings in
    order, and the title for the document head."""

    title: str
    body: str
    headings: list[Heading] = field(default_factory=list)

    def fragment(self) -> lxml_html.HtmlElement:
        """A fresh, mutable parse of the body inside one ``<div>``."""
        return lxml_html.fragment_fromstring(self.body, create_parent="div")


@lru_cache(maxsize=1)
def _parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])
    md.use(footnote_plugin)
    return md


@lru_cache(maxsize=4)
def stylesheet(name: str = "book.css") -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def slugger():
    """The reader's heading-id function with `-2`, `-3` for repeats."""
    seen: dict[str, int] = {}

    def slug(text: str) -> str:
        base = heading_slug(text)
        n = seen.get(base, 0) + 1
        seen[base] = n
        return base if n == 1 else f"{base}-{n}"

    return slug


def top_level_headings(markdown: str) -> list[SourceHeading]:
    """The headings the renderer will make of ``markdown``, outside any quote
    or list, for a caller rewriting the source. Only the parser can say which
    lines these are: `Text` over `---` is a heading, but `- item` over `---`
    is a list and a rule, and so is anything in a code fence."""
    tokens = _parser().parse(_XML_INVALID.sub("", markdown or ""), {})
    return [
        SourceHeading(level=int(t.tag[1]), line=t.map[0], end=t.map[1], setext=t.markup in _SETEXT_MARKUP)
        for t in tokens
        if t.type == "heading_open" and t.level == 0 and t.map
    ]


def _normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def render_book_html(markdown: str, *, title: str) -> BookHtml:
    """Render a book manuscript. Pure function of its inputs."""
    source = _XML_INVALID.sub("", markdown or "")
    parser = _parser()
    env: dict = {}
    tokens = parser.parse(source, env)
    for token in tokens:
        if token.type == "heading_open" and token.map:
            token.attrSet(_LINE_ATTR, str(token.map[0]))
    root = lxml_html.fragment_fromstring(parser.renderer.render(tokens, parser.options, env) or "<p></p>", create_parent="div")

    slug = slugger()
    headings: list[Heading] = []
    for el in root.iter("h1", "h2", "h3", "h4", "h5", "h6"):
        text = _normalise_space(el.text_content())
        el.set("id", slug(text))
        line = int(el.attrib.pop(_LINE_ATTR, -1))
        headings.append(Heading(level=int(el.tag[1]), id=el.get("id"), text=text, line=line))

    for sup in root.xpath('//sup[contains(concat(" ", @class, " "), " footnote-ref ")]'):
        for a in sup.iter("a"):
            m = _FOOTNOTE_CAPTION.match((a.text or "").strip())
            if m:
                a.text = m.group(1)
            a.set("role", "doc-noteref")
            a.set("data-epub-type", "noteref")
    for hr in root.xpath('//hr[contains(concat(" ", @class, " "), " footnotes-sep ")]'):
        hr.drop_tree()
    for section in root.xpath('//section[contains(concat(" ", @class, " "), " footnotes ")]'):
        section.set("role", "doc-endnotes")
        section.set("data-epub-type", "endnotes")
        for li in section.iter("li"):
            li.set("role", "doc-endnote")
            li.set("data-epub-type", "endnote")
        for back in section.xpath('.//a[contains(concat(" ", @class, " "), " footnote-backref ")]'):
            back.set("role", "doc-backlink")
            target = (back.get("href") or "").lstrip("#")
            back.set("aria-label", f"Back to reference {target.removeprefix('fnref')}")
            back.text = "↩"

    for img in list(root.iter("img")):
        alt = _normalise_space(img.get("alt") or "")
        span = lxml_html.Element("span", {"class": "image-alt"})
        span.text = f"[image: {alt}]" if alt else "[image]"
        span.tail = img.tail
        img.getparent().replace(img, span)

    body = "".join(lxml_html.tostring(child, encoding="unicode") for child in root)
    return BookHtml(title=title, body=body, headings=headings)


def html_document(book: BookHtml, *, lang: str = "en", print_css: bool = True) -> str:
    """A standalone HTML document with the stylesheet inlined (the PDF
    engines load nothing from outside the document)."""
    css = stylesheet("book.css") + ("\n" + stylesheet("book-print.css") if print_css else "")
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{html.escape(lang)}"><head><meta charset="utf-8">'
        f"<title>{html.escape(book.title)}</title><style>\n{css}\n</style></head>"
        f'<body><main class="book">{book.body}</main></body></html>'
    )

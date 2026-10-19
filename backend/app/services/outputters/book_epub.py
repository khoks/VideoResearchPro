"""Book EPUB 3 (S-6.1.5): hand-rolled with ``zipfile`` and lxml.

The plan's choice (docs/plans/l2-author-studio.md): no new runtime
dependency, and the container is small enough to own.

Layout of the archive::

    mimetype                      first entry, stored, "application/epub+zip"
    META-INF/container.xml        points at the package document
    OEBPS/content.opf             metadata, manifest, spine
    OEBPS/nav.xhtml               the table of contents (EPUB 3 navigation)
    OEBPS/style.css               book.css
    OEBPS/title.xhtml             the book title and byline
    OEBPS/part-001.xhtml …        one file per chapter (each ``##`` section)

The manuscript's own "Table of Contents" section is left out: ``nav.xhtml``
is the table of contents, and readers show it in their own menu too.
In-book links (endnote references, back-links) are rewritten to
``file.xhtml#id`` when the target lives in another file.

Every XHTML file is parsed back as XML before it is written, so a file that
is not well-formed fails the build here instead of in the reader.
"""
from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lxml import etree

from app.services.output_citation_service import heading_slug
from app.services.output_service import OutputError
from app.services.outputters.book_html import ENDNOTES_HEADING, TOC_HEADING, BookHtml, stylesheet

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

MIMETYPE = "application/epub+zip"
CONTENT_DIR = "OEBPS"
TITLE_FILE = "title.xhtml"
NAV_FILE = "nav.xhtml"
STYLE_FILE = "style.css"

_TOC_ID = heading_slug(TOC_HEADING)
_ENDNOTES_ID = heading_slug(ENDNOTES_HEADING)


class EpubError(OutputError):
    pass


@dataclass
class _Part:
    filename: str
    kind: str  # "titlepage" | "chapter" | "endnotes"
    elements: list = field(default_factory=list)
    heading_id: str | None = None
    heading_text: str = ""
    sub: list[tuple[str, str]] = field(default_factory=list)  # (id, text) of h3s


def _split(book: BookHtml) -> list[_Part]:
    """Cut the body at every ``h2``: what comes before is the title page."""
    root = book.fragment()
    parts: list[_Part] = [_Part(TITLE_FILE, "titlepage")]
    skipping = False
    for el in list(root):
        if not isinstance(el.tag, str):
            continue  # comments / processing instructions
        if el.tag == "h2":
            hid = el.get("id") or ""
            if hid == _TOC_ID:
                skipping = True
                continue
            skipping = False
            n = sum(1 for p in parts if p.kind != "titlepage") + 1
            parts.append(
                _Part(
                    f"part-{n:03d}.xhtml",
                    "endnotes" if hid == _ENDNOTES_ID else "chapter",
                    heading_id=hid,
                    heading_text=re.sub(r"\s+", " ", el.text_content()).strip(),
                )
            )
        if skipping:
            continue
        parts[-1].elements.append(el)
        if el.tag == "h3" and el.get("id"):
            parts[-1].sub.append((el.get("id"), re.sub(r"\s+", " ", el.text_content()).strip()))
    return parts


def _rewrite_links(parts: list[_Part]) -> None:
    """Point every in-book ``#id`` link at the file that holds ``id``; a
    link whose target is not in the book loses its ``href`` (a dead link is
    worse than plain text)."""
    where: dict[str, str] = {}
    for part in parts:
        for el in part.elements:
            for node in el.iter():
                if isinstance(node.tag, str) and node.get("id"):
                    where.setdefault(node.get("id"), part.filename)
    for part in parts:
        for el in part.elements:
            for a in el.iter("a"):
                href = a.get("href") or ""
                if not href.startswith("#"):
                    continue
                target = href[1:]
                home = where.get(target)
                if home is None:
                    a.attrib.pop("href", None)
                elif home != part.filename:
                    a.set("href", f"{home}#{target}")


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _xhtml(title: str, body_xml: str, *, lang: str) -> bytes:
    """Wrap serialised body content in an XHTML document and round-trip it
    through the XML parser (well-formedness check, ``epub:type`` fix-up)."""
    doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" lang="{lang}" xml:lang="{lang}">'
        f"<head><meta charset=\"utf-8\"/><title>{_xml_escape(title)}</title>"
        f'<link rel="stylesheet" type="text/css" href="{STYLE_FILE}"/></head>'
        f"<body>{body_xml}</body></html>"
    )
    try:
        tree = etree.fromstring(doc.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        raise EpubError(f"EPUB chapter '{title}' is not well-formed XHTML: {e}") from e
    for node in tree.iter():
        if not isinstance(node.tag, str):
            continue
        marker = node.attrib.pop("data-epub-type", None)
        if marker:
            node.set(f"{{{EPUB_NS}}}type", marker)
    return etree.tostring(tree, xml_declaration=True, encoding="utf-8", doctype="<!DOCTYPE html>")


def _serialise(elements: list) -> str:
    return "".join(etree.tostring(el, method="xml", encoding="unicode", with_tail=False) for el in elements)


def _part_document(part: _Part, book_title: str, lang: str) -> bytes:
    epub_type = {"titlepage": "titlepage", "chapter": "chapter", "endnotes": "backmatter"}[part.kind]
    title = part.heading_text or book_title
    body = f'<section data-epub-type="{epub_type}">{_serialise(part.elements)}</section>'
    return _xhtml(title, body, lang=lang)


def _nav_document(parts: list[_Part], book_title: str, lang: str) -> bytes:
    items: list[str] = []
    for part in parts:
        if part.kind == "titlepage" or not part.heading_id:
            continue
        href = f"{part.filename}#{part.heading_id}"
        sub = ""
        if part.sub:
            sub = "<ol>" + "".join(
                f'<li><a href="{part.filename}#{sid}">{_xml_escape(stext)}</a></li>' for sid, stext in part.sub
            ) + "</ol>"
        items.append(f'<li><a href="{href}">{_xml_escape(part.heading_text)}</a>{sub}</li>')
    if not items:  # a navigation list may not be empty
        items.append(f'<li><a href="{TITLE_FILE}">{_xml_escape(book_title)}</a></li>')
    first = next((p.filename for p in parts if p.kind == "chapter"), TITLE_FILE)
    body = (
        f'<nav data-epub-type="toc" id="toc" role="doc-toc"><h1>Contents</h1><ol>{"".join(items)}</ol></nav>'
        f'<nav data-epub-type="landmarks" hidden="hidden"><h2>Landmarks</h2><ol>'
        f'<li><a data-epub-type="toc" href="{NAV_FILE}#toc">Contents</a></li>'
        f'<li><a data-epub-type="bodymatter" href="{first}">Start of content</a></li>'
        "</ol></nav>"
    )
    return _xhtml(f"{book_title} — Contents", body, lang=lang)


def _package_document(parts: list[_Part], *, title: str, identifier: str, modified: datetime, lang: str, creator: str) -> bytes:
    E = etree.Element
    package = E(f"{{{OPF_NS}}}package", nsmap={None: OPF_NS}, attrib={"version": "3.0", "unique-identifier": "book-id"})
    package.set("{http://www.w3.org/XML/1998/namespace}lang", lang)
    metadata = etree.SubElement(package, f"{{{OPF_NS}}}metadata", nsmap={"dc": DC_NS})
    etree.SubElement(metadata, f"{{{DC_NS}}}identifier", id="book-id").text = identifier
    etree.SubElement(metadata, f"{{{DC_NS}}}title").text = title
    etree.SubElement(metadata, f"{{{DC_NS}}}language").text = lang
    etree.SubElement(metadata, f"{{{DC_NS}}}creator").text = creator
    etree.SubElement(metadata, f"{{{DC_NS}}}date").text = modified.strftime("%Y-%m-%d")
    etree.SubElement(metadata, f"{{{OPF_NS}}}meta", property="dcterms:modified").text = modified.strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = etree.SubElement(package, f"{{{OPF_NS}}}manifest")
    etree.SubElement(manifest, f"{{{OPF_NS}}}item", id="nav", href=NAV_FILE, attrib={"media-type": "application/xhtml+xml", "properties": "nav"})
    etree.SubElement(manifest, f"{{{OPF_NS}}}item", id="css", href=STYLE_FILE, attrib={"media-type": "text/css"})
    ids: list[str] = []
    for i, part in enumerate(parts):
        item_id = f"p{i:03d}"
        ids.append(item_id)
        etree.SubElement(manifest, f"{{{OPF_NS}}}item", id=item_id, href=part.filename, attrib={"media-type": "application/xhtml+xml"})

    spine = etree.SubElement(package, f"{{{OPF_NS}}}spine")
    etree.SubElement(spine, f"{{{OPF_NS}}}itemref", idref=ids[0])
    etree.SubElement(spine, f"{{{OPF_NS}}}itemref", idref="nav")
    for item_id in ids[1:]:
        etree.SubElement(spine, f"{{{OPF_NS}}}itemref", idref=item_id)
    return etree.tostring(package, xml_declaration=True, encoding="utf-8", pretty_print=True)


def _container() -> bytes:
    root = etree.Element(f"{{{CONTAINER_NS}}}container", nsmap={None: CONTAINER_NS}, version="1.0")
    rootfiles = etree.SubElement(root, f"{{{CONTAINER_NS}}}rootfiles")
    etree.SubElement(
        rootfiles,
        f"{{{CONTAINER_NS}}}rootfile",
        attrib={"full-path": f"{CONTENT_DIR}/content.opf", "media-type": "application/oebps-package+xml"},
    )
    return etree.tostring(root, xml_declaration=True, encoding="utf-8", pretty_print=True)


def book_identifier(output_id: str) -> str:
    """``urn:uuid:`` of the output id (stable per output; a non-UUID id is
    mapped through uuid5 so the identifier is still a valid URN)."""
    try:
        return f"urn:uuid:{uuid.UUID(str(output_id))}"
    except ValueError:
        return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'pratidhvani:output:{output_id}')}"


def build_epub(
    book: BookHtml,
    *,
    identifier: str,
    modified: datetime | None = None,
    lang: str = "en",
    creator: str = "Pratidhvani Author Studio",
) -> bytes:
    """The book as EPUB 3 bytes."""
    modified = (modified or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    parts = _split(book)
    _rewrite_links(parts)

    files: list[tuple[str, bytes]] = [
        (f"{CONTENT_DIR}/{part.filename}", _part_document(part, book.title, lang)) for part in parts
    ]
    files.insert(0, (f"{CONTENT_DIR}/{NAV_FILE}", _nav_document(parts, book.title, lang)))
    files.insert(0, (f"{CONTENT_DIR}/{STYLE_FILE}", stylesheet("book.css").encode("utf-8")))
    files.insert(
        0,
        (
            f"{CONTENT_DIR}/content.opf",
            _package_document(parts, title=book.title, identifier=identifier, modified=modified, lang=lang, creator=creator),
        ),
    )

    buf = io.BytesIO()
    stamp = modified.timetuple()[:6]
    with zipfile.ZipFile(buf, "w") as zf:
        # OCF: the mimetype entry comes first, uncompressed, with no extra field.
        zf.writestr(zipfile.ZipInfo("mimetype", date_time=stamp), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr(zipfile.ZipInfo("META-INF/container.xml", date_time=stamp), _container(), compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files:
            zf.writestr(zipfile.ZipInfo(name, date_time=stamp), data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()

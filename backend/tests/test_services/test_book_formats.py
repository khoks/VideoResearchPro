"""S-6.1.5 — a book's EPUB and PDF downloads.

What a reader relies on: the EPUB is a valid EPUB 3 container whose every
in-book link lands on an element that exists (endnote references, back-links,
the navigation document); the PDF opens, has an outline and working
internal links, and shows a Devanagari quote as text (the font is embedded,
not boxes). The PDF engine is optional: with none installed, a request for a
PDF is refused before any row exists, with what to install, and the EPUB and
Markdown still work.
"""
from __future__ import annotations

import http.server
import io
import json
import re
import sys
import threading
import types
import zipfile
from unittest.mock import patch

import pytest
from lxml import etree

from app.config import settings
from app.models.output import Output
from app.models.qa_exchange import QAExchange
from app.services import auth_service, output_artifacts, output_service
from app.services.output_service import OutputError, OutputUnavailable
from app.services.outputters import book_epub, book_html, book_markdown, book_pdf
from tests.test_services.test_book_endnotes import _generate, _smoke_run

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
QUOTE = "अहिंसा परमो धर्मः"


@pytest.fixture(autouse=True)
def quiet_progress():
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


@pytest.fixture
def probes_reset():
    book_pdf.reset_probes()
    yield
    book_pdf.reset_probes()


@pytest.fixture
def pdf_engine(monkeypatch, probes_reset):
    """This machine's real PDF engine, or skip."""
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "auto")
    engine = book_pdf.pdf_engine()
    if engine is None:
        pytest.skip(f"no PDF engine here: {book_pdf.unavailable_message()}")
    return engine


def _qa_with_devanagari(db, job, user):
    db.add(QAExchange(job_id=job.id, tenant_id=user.id, question="What does the verse say?",
                      answer=f"It reads {QUOTE} (ahiṃsā paramo dharmaḥ), “non-violence is the highest virtue”.",
                      references="[]"))
    db.commit()


# ---------------------------------------------------------------------------
# Markdown -> HTML
# ---------------------------------------------------------------------------


def test_heading_ids_are_the_readers_and_duplicates_are_numbered():
    book = book_html.render_book_html(
        "# Book\n\n## 1. First Topic\n\n#### Key Facts\n\n## 2. हिंदी पुस्तक — भाग १\n\n#### Key Facts\n",
        title="Book",
    )
    assert [h.id for h in book.headings] == ["book", "1-first-topic", "key-facts", "2-हिंदी-पुस्तक-भाग-१", "key-facts-2"]
    assert 'id="2-हिंदी-पुस्तक-भाग-१"' in book.body


def test_raw_html_is_text_and_images_become_their_alt_text():
    book = book_html.render_book_html(
        "Para <script>alert(1)</script> <b>x</b>\n\n![Chart of prices](http://127.0.0.1:9/x.png)\n", title="T"
    )
    root = book.fragment()
    assert root.xpath("//script") == [] and root.xpath("//b") == []
    assert "<script>alert(1)</script>" in root.text_content()
    assert root.xpath("//img") == []
    assert root.xpath('//span[@class="image-alt"]')[0].text == "[image: Chart of prices]"


def test_footnotes_render_as_numbered_endnotes_with_backlinks():
    book = book_html.render_book_html(
        "Claim [1:15](https://youtu.be/x?t=75)[^1].\n\n## Endnotes\n\n[^1]: *T* — C, 1:15. <https://youtu.be/x?t=75>\n",
        title="T",
    )
    root = book.fragment()
    ref = root.xpath('//a[@role="doc-noteref"]')[0]
    assert ref.text == "1" and ref.get("href") == "#fn1"
    assert root.xpath('//section[@role="doc-endnotes"]//li[@id="fn1"]')
    assert root.xpath('//a[@role="doc-backlink"]')[0].get("href") == "#fnref1"
    assert root.xpath('//hr[contains(@class, "footnotes-sep")]') == []


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------


def _epub_files(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _assert_valid_epub(data: bytes) -> dict[str, etree._Element]:
    """OCF container, package document and link integrity; returns every
    XHTML document parsed, by archive name."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED and first.extra == b""
        assert zf.read("mimetype") == b"application/epub+zip"
        assert zf.testzip() is None
    files = _epub_files(data)

    container = etree.fromstring(files["META-INF/container.xml"])
    opf_path = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile").get("full-path")
    opf = etree.fromstring(files[opf_path])
    base = opf_path.rsplit("/", 1)[0] + "/"
    assert opf.get("version") == "3.0"
    assert opf.find(f".//{DC}identifier").text.startswith("urn:uuid:")
    assert opf.find(f".//{DC}language").text == "en"
    modified = opf.find(f".//{OPF}meta[@property='dcterms:modified']").text
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", modified)

    items = {i.get("id"): i for i in opf.iter(f"{OPF}item")}
    for item in items.values():
        assert base + item.get("href") in files, f"manifest lists a missing file: {item.get('href')}"
    content_files = {n for n in files if n.startswith(base) and n != opf_path}
    assert content_files == {base + i.get("href") for i in items.values()}, "every content file is in the manifest"
    assert [i.get("properties") for i in items.values()].count("nav") == 1
    spine = [r.get("idref") for r in opf.iter(f"{OPF}itemref")]
    assert spine and all(idref in items for idref in spine)

    docs = {n: etree.fromstring(b) for n, b in files.items() if n.endswith(".xhtml")}
    ids = {n: {el.get("id") for el in d.iter() if isinstance(el.tag, str) and el.get("id")} for n, d in docs.items()}
    for name, doc in docs.items():
        assert doc.tag == f"{XHTML}html"
        for a in doc.iter(f"{XHTML}a"):
            href = a.get("href")
            if href is None or href.startswith(("https://", "http://")):
                continue
            target_file, _, frag = href.partition("#")
            target = base + target_file if target_file else name
            assert target in docs, f"{name}: link to a missing file {href}"
            if frag:
                assert frag in ids[target], f"{name}: link to a missing id {href}"
    return docs


def test_epub_of_a_real_two_chapter_book_is_valid_and_every_link_resolves(db, tmp_path):
    user = auth_service.create_user(db, email="bf1@x.com", password="pw" * 6)
    a = _smoke_run(db, user.id, tmp_path, topic="First run")
    b = _smoke_run(db, user.id, tmp_path, topic="Second run")
    _qa_with_devanagari(db, b, user)
    out = _generate(db, user, [a.id, b.id], formats=["epub"])

    assert output_artifacts.available_formats(out) == ["md", "epub"]
    assert out.content_path and out.content_path.endswith("artifact.epub")
    docs = _assert_valid_epub(output_artifacts.artifact_file(out, "epub").read_bytes())

    nav = next(d for n, d in docs.items() if n.endswith("/nav.xhtml"))
    toc = nav.xpath("//x:nav[@epub:type='toc']//x:a/text()", namespaces={"x": XHTML[1:-1], "epub": EPUB_TYPE[1:-5]})
    assert toc[:2] == ["1. First run", "2. Second run"] and toc[-1] == "Endnotes"
    assert all("table-of-contents" not in {el.get("id") for el in d.iter() if isinstance(el.tag, str)} for d in docs.values()), (
        "nav.xhtml replaces the manuscript's own contents section"
    )

    noterefs = [el for d in docs.values() for el in d.iter(f"{XHTML}a") if el.get(EPUB_TYPE) == "noteref"]
    endnotes = [el for d in docs.values() for el in d.iter(f"{XHTML}li") if el.get(EPUB_TYPE) == "endnote"]
    assert len(noterefs) == len(endnotes) == 60, "one endnote per citation, as in the Markdown"
    assert all("part-" in el.get("href") and "#fn" in el.get("href") for el in noterefs), (
        "references in a chapter point into the endnotes file"
    )
    text = "".join(etree.tostring(d, encoding="unicode", method="text") for d in docs.values())
    assert QUOTE in text


def test_epub_identifier_is_stable_per_output():
    assert book_epub.book_identifier("4a4e0d9e-8f8e-4a3c-9a54-2f9b3d1c0e11") == "urn:uuid:4a4e0d9e-8f8e-4a3c-9a54-2f9b3d1c0e11"
    assert book_epub.book_identifier("not-a-uuid") == book_epub.book_identifier("not-a-uuid")
    assert book_epub.book_identifier("not-a-uuid").startswith("urn:uuid:")


def test_xml_invalid_characters_in_a_transcript_do_not_break_the_epub():
    book = book_html.render_book_html("# B\n\n## 1. C\n\nbad \x0b char \x01 here\n", title="B & <b>")
    _assert_valid_epub(book_epub.build_epub(book, identifier="urn:uuid:00000000-0000-0000-0000-000000000000"))


# ---------------------------------------------------------------------------
# Format selection and the optional PDF engine
# ---------------------------------------------------------------------------


def test_requested_formats_default_and_validation(monkeypatch):
    monkeypatch.setattr(book_pdf, "pdf_engine", lambda: None)
    assert book_markdown.requested_formats({}) == ["epub"]
    monkeypatch.setattr(book_pdf, "pdf_engine", lambda: "chromium")
    assert book_markdown.requested_formats({}) == ["epub", "pdf"]
    assert book_markdown.requested_formats({"formats": ["PDF", "md", "pdf"]}) == ["pdf"]
    assert book_markdown.requested_formats({"formats": []}) == []
    with pytest.raises(OutputError, match="docx"):
        book_markdown.requested_formats({"formats": ["docx"]})
    with pytest.raises(OutputError, match="list"):
        book_markdown.requested_formats({"formats": "pdf"})


def test_engine_order_and_unavailable_message(monkeypatch, probes_reset):
    monkeypatch.setattr(book_pdf, "_PROBES", {
        "weasyprint": lambda: "WeasyPrint is installed but cannot load its libraries (cannot load library 'libgobject-2.0-0')",
        "chromium": lambda: None,
    })
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "auto")
    assert book_pdf.pdf_engine() == "chromium", "WeasyPrint first, Chromium when it cannot load"
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "weasyprint")
    assert book_pdf.pdf_engine() is None
    message = book_pdf.unavailable_message()
    assert "libgobject" in message and "requirements-author.txt" in message and "pango" in message.lower()
    with pytest.raises(OutputUnavailable):
        book_pdf.require_engine()
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "off")
    assert book_pdf.pdf_engine() is None and "turned off" in book_pdf.unavailable_message()


def test_a_pdf_the_worker_cannot_print_fails_the_row_with_what_to_install(db, tmp_path, monkeypatch):
    user = auth_service.create_user(db, email="bf2@x.com", password="pw" * 6)
    job = _smoke_run(db, user.id, tmp_path)
    monkeypatch.setattr(book_pdf, "pdf_engine", lambda: None)
    row = output_service.create_output(db, user_id=user.id, kind="book", title="No engine", source_ids=[job.id],
                                       parameters={"formats": ["md", "epub", "pdf"]})
    out = output_service.run_generation(db, user, row)
    assert out.status == "failed"
    assert "turned off" in out.error_message or "requirements-author.txt" in out.error_message
    assert output_artifacts.available_formats(out) == [], "nothing half-built is left behind"


def test_weasyprint_branch_calls_html_with_a_fetcher_that_refuses_the_network(monkeypatch, probes_reset):
    calls: dict = {}

    class FakeHTML:
        def __init__(self, string, url_fetcher):
            calls["html"], calls["fetcher"] = string, url_fetcher

        def write_pdf(self):
            return b"%PDF-1.7 fake"

    fake = types.ModuleType("weasyprint")
    fake.HTML = FakeHTML
    fake.default_url_fetcher = lambda url, *a, **k: {"string": b"ok", "mime_type": "image/png"}
    monkeypatch.setitem(sys.modules, "weasyprint", fake)
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "weasyprint")

    assert book_pdf.pdf_engine() == "weasyprint"
    assert book_pdf.render_pdf("<html><body>x</body></html>") == b"%PDF-1.7 fake"
    fetch = calls["fetcher"]
    assert fetch("data:image/png;base64,AAAA")["string"] == b"ok"
    for url in ("http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "https://example.com/x.css"):
        with pytest.raises(ValueError):
            fetch(url)


# ---------------------------------------------------------------------------
# PDF with this machine's engine
# ---------------------------------------------------------------------------


def test_pdf_of_a_real_book_opens_with_outline_links_and_devanagari_text(db, tmp_path, pdf_engine):
    fitz = pytest.importorskip("fitz")
    user = auth_service.create_user(db, email="bf3@x.com", password="pw" * 6)
    a = _smoke_run(db, user.id, tmp_path, topic="First run")
    b = _smoke_run(db, user.id, tmp_path, topic="Second run")
    _qa_with_devanagari(db, b, user)
    out = _generate(db, user, [a.id, b.id])  # no `formats`: EPUB and PDF by default when an engine exists

    assert output_artifacts.available_formats(out) == ["md", "pdf", "epub"]
    assert out.content_path.endswith("artifact.pdf"), "the PDF is the primary artifact when there is one"
    doc = fitz.open(output_artifacts.artifact_file(out, "pdf"))
    assert doc.page_count > 4
    outline = [title for _level, title, _page in doc.get_toc()]
    for heading in ("The Smoke Book", "Table of Contents", "1. First run", "2. Second run", "Endnotes"):
        assert heading in outline

    pages = {title: page for _level, title, page in doc.get_toc()}
    toc_page = doc[pages["Table of Contents"] - 1]
    targets = sorted(link["page"] + 1 for link in toc_page.get_links() if link.get("page") is not None)
    assert targets == [pages["1. First run"], pages["2. Second run"]], "contents entries jump to their chapters"

    text = "".join(page.get_text() for page in doc)
    assert QUOTE in text, "the Devanagari quote is real text, not missing glyphs"
    assert "https://www.youtube.com/watch?v=" in text, "endnotes print their URLs"
    fonts = {f[3]: f[1] for page in doc for f in page.get_fonts()}
    assert fonts and all(ext != "n/a" for ext in fonts.values()), f"every font embedded: {fonts}"


class _CountingHandler(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):  # noqa: N802
        type(self).hits += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_pdf_engine_fetches_nothing_from_the_network(pdf_engine):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        document = (
            f'<!DOCTYPE html><html><head><link rel="stylesheet" href="{url}/x.css">'
            f'<style>@import url("{url}/y.css"); body {{ background: url("{url}/z.png"); }}</style></head>'
            f'<body><p>Hello</p><img src="{url}/a.png"><iframe src="{url}/f"></iframe></body></html>'
        )
        pdf = book_pdf.render_pdf(document, engine=pdf_engine)
    finally:
        server.shutdown()
        server.server_close()
    assert pdf.startswith(b"%PDF")
    assert _CountingHandler.hits == 0


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@pytest.fixture
def pro_headers(db):
    user = auth_service.create_user(db, email="bfr@x.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def test_kinds_reports_formats_and_why_pdf_is_missing(unauthenticated_client, pro_headers):
    _user, headers = pro_headers
    body = unauthenticated_client.get("/api/v1/author/kinds", headers=headers).json()
    book = body["formats"]["book"]
    assert book["available"] == ["md", "epub"]
    assert "pdf" in book["unavailable"] and book["pdf_engine"] is None


def test_explicit_pdf_without_an_engine_is_501_before_any_row(unauthenticated_client, db, pro_headers, tmp_path, monkeypatch, probes_reset):
    user, headers = pro_headers
    job = _smoke_run(db, user.id, tmp_path)
    monkeypatch.setattr(settings, "AUTHOR_PDF_ENGINE", "auto")
    monkeypatch.setattr(book_pdf, "_PROBES", {"weasyprint": lambda: "WeasyPrint is not installed",
                                              "chromium": lambda: "Playwright is not installed"})
    before = db.query(Output).count()
    r = unauthenticated_client.post("/api/v1/author/outputs", headers=headers,
                    json={"kind": "book", "title": "PDF please", "source_ids": [job.id], "parameters": {"formats": ["pdf"]}})
    assert r.status_code == 501
    assert "requirements-author.txt" in r.json()["detail"] and "playwright install chromium" in r.json()["detail"]
    assert db.query(Output).count() == before

    r = unauthenticated_client.post("/api/v1/author/outputs", headers=headers,
                    json={"kind": "book", "title": "Bad", "source_ids": [job.id], "parameters": {"formats": ["docx"]}})
    assert r.status_code == 400 and db.query(Output).count() == before


def test_default_book_records_its_formats_and_serves_the_epub(unauthenticated_client, db, pro_headers, tmp_path, monkeypatch):
    user, headers = pro_headers
    monkeypatch.setattr(settings, "OUTPUTS_DIR", str(tmp_path / "outputs"))
    job = _smoke_run(db, user.id, tmp_path)
    r = unauthenticated_client.post("/api/v1/author/outputs?sync=true", headers=headers,
                    json={"kind": "book", "title": "पुस्तक One", "source_ids": [job.id]})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["status"] == "completed"
    assert item["parameters"]["formats"] == ["md", "epub"], "the row records what was built"
    assert item["formats"] == ["md", "epub"]

    d = unauthenticated_client.get(f"/api/v1/author/outputs/{item['id']}/download?format=epub", headers=headers)
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/epub+zip"
    assert "filename*=UTF-8''%E0%A4%AA" in d.headers["content-disposition"] and ".epub" in d.headers["content-disposition"]
    _assert_valid_epub(d.content)
    assert json.loads(db.get(Output, item["id"]).parameters_json)["formats"] == ["md", "epub"]

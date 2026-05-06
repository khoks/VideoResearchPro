"""Unit tests for the PDF connector + flatten + upload endpoint.

PyMuPDF is invoked with real bytes — we generate a small in-memory
PDF on the fly using PyMuPDF's own writer so the tests don't need
a fixture binary file. Tests run in <1 second.
"""
from __future__ import annotations


import fitz
import pytest

from app.sources import registry
from app.sources.pdf import flatten as pdf_flatten
from app.sources.pdf.connector import (
    PDFConnector,
    SOURCE_TYPE,
    hash_pdf_bytes,
    upload_path_for_source_id,
)
from app.sources.types import Candidate, ExtractedText


# ---------------------------------------------------------------------------
# Fixture: build a tiny PDF in-memory
# ---------------------------------------------------------------------------


def _build_pdf(pages: list[str]) -> bytes:
    """Generate a PDF with `len(pages)` pages, each containing the
    given text as the first paragraph.

    Uses PyMuPDF's writer so we don't need a separate library or a
    fixture file. Output is a real PDF — `fitz.open(stream=...)`
    parses it cleanly.
    """
    doc = fitz.open()
    for body in pages:
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((50, 80), body, fontsize=12)
    out = doc.write()
    doc.close()
    return bytes(out)


@pytest.fixture
def pdf_bytes_two_pages() -> bytes:
    return _build_pdf(
        [
            "Page one body. The first page contains the introduction "
            "and the framing of the document.",
            "Page two body. The second page contains the conclusion "
            "and final remarks of the author.",
        ]
    )


@pytest.fixture
def pdf_bytes_single_page() -> bytes:
    return _build_pdf(["Single page contents."])


# ---------------------------------------------------------------------------
# hash_pdf_bytes — stable, dedup-friendly, hex digest
# ---------------------------------------------------------------------------


def test_hash_pdf_bytes_is_deterministic(pdf_bytes_two_pages: bytes):
    a = hash_pdf_bytes(pdf_bytes_two_pages)
    b = hash_pdf_bytes(pdf_bytes_two_pages)
    assert a == b
    assert len(a) == 64  # SHA-256 hex


def test_hash_pdf_bytes_distinguishes_different_pdfs(
    pdf_bytes_two_pages: bytes, pdf_bytes_single_page: bytes
):
    assert hash_pdf_bytes(pdf_bytes_two_pages) != hash_pdf_bytes(pdf_bytes_single_page)


def test_hash_pdf_bytes_uses_first_64kb_only():
    """Two PDFs sharing their first 64KB but differing in the trailer
    should hash the same (we hash only the head — content uniqueness
    in the first 64KB is what matters for collision resistance)."""
    head = b"x" * (64 * 1024)
    a = head + b"trailer-a"
    b = head + b"trailer-b"
    assert hash_pdf_bytes(a) == hash_pdf_bytes(b)


# ---------------------------------------------------------------------------
# Flatten — PDF bytes → segments
# ---------------------------------------------------------------------------


def test_flatten_pdf_emits_one_segment_per_page(pdf_bytes_two_pages: bytes):
    segs = pdf_flatten.flatten_pdf(pdf_bytes_two_pages, "pdf:abc")
    assert len(segs) == 2
    assert "first page" in segs[0]["text"].lower()
    assert "second page" in segs[1]["text"].lower()


def test_flatten_pdf_attaches_page_extra(pdf_bytes_two_pages: bytes):
    segs = pdf_flatten.flatten_pdf(pdf_bytes_two_pages, "pdf:abc")
    extras = [s["extra"] for s in segs]
    assert extras[0]["kind"] == "page"
    assert extras[0]["page"] == 1
    assert extras[0]["total_pages"] == 2
    assert extras[0]["comment_id"] == "pdf:abc:p1"
    assert extras[1]["page"] == 2
    assert extras[1]["comment_id"] == "pdf:abc:p2"


def test_flatten_pdf_synthesises_page_url_fragment_when_url_provided(
    pdf_bytes_two_pages: bytes,
):
    segs = pdf_flatten.flatten_pdf(
        pdf_bytes_two_pages,
        "pdf:abc",
        document_url="https://example.com/doc.pdf",
    )
    assert segs[0]["extra"]["comment_url"] == "https://example.com/doc.pdf#page=1"
    assert segs[1]["extra"]["comment_url"] == "https://example.com/doc.pdf#page=2"


def test_flatten_pdf_leaves_comment_url_empty_when_no_doc_url(
    pdf_bytes_two_pages: bytes,
):
    segs = pdf_flatten.flatten_pdf(pdf_bytes_two_pages, "pdf:abc")
    assert segs[0]["extra"]["comment_url"] == ""


def test_flatten_pdf_returns_empty_for_empty_bytes():
    assert pdf_flatten.flatten_pdf(b"", "pdf:abc") == []


def test_flatten_pdf_returns_empty_for_corrupt_input():
    """Truly malformed bytes raise inside fitz.open; flatten returns []."""
    assert pdf_flatten.flatten_pdf(b"not a pdf", "pdf:abc") == []


def test_flatten_pdf_skips_blank_pages():
    """A page with no extractable text is skipped — segment count
    reflects only pages with content."""
    doc = fitz.open()
    doc.new_page(width=595, height=842)  # blank page 1
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 80), "Real content on page two.", fontsize=12)
    pdf_bytes = bytes(doc.write())
    doc.close()
    segs = pdf_flatten.flatten_pdf(pdf_bytes, "pdf:test")
    # Only the page-with-text survives.
    assert len(segs) == 1
    assert segs[0]["extra"]["page"] == 2
    assert "Real content" in segs[0]["text"]


# ---------------------------------------------------------------------------
# Connector: discovery methods raise NotImplementedError
# ---------------------------------------------------------------------------


def test_search_raises_not_implemented():
    conn = PDFConnector()
    with pytest.raises(NotImplementedError):
        conn.search("anything")


def test_list_creator_items_raises_not_implemented():
    conn = PDFConnector()
    with pytest.raises(NotImplementedError):
        list(conn.list_creator_items("something"))


def test_fetch_metadata_returns_empty_dict():
    """fetch_metadata is a no-op for PDFs — upload endpoint already
    wrote everything."""
    assert PDFConnector().fetch_metadata(["pdf:abc"]) == {}


# ---------------------------------------------------------------------------
# Connector: fetch_text
# ---------------------------------------------------------------------------


def test_fetch_text_reads_upload_and_returns_segments(
    pdf_bytes_two_pages: bytes, monkeypatch, tmp_path
):
    """Happy path — upload is on disk, fetch_text reads + flattens."""
    from app.sources.pdf import connector as pdf_connector_mod

    monkeypatch.setattr(
        pdf_connector_mod.settings, "PDF_UPLOAD_DIR", str(tmp_path)
    )
    digest = hash_pdf_bytes(pdf_bytes_two_pages)
    source_id = f"pdf:{digest}"
    path = tmp_path / f"{digest}.pdf"
    path.write_bytes(pdf_bytes_two_pages)

    cand = Candidate(
        source_type="pdf",
        source_id=source_id,
        title="Test Doc",
        source_url=f"/api/v1/library/pdf/{digest}.pdf",
    )
    out = PDFConnector().fetch_text(cand)
    assert isinstance(out, ExtractedText)
    assert out.text_source == "pdf"
    assert len(out.segments) == 2
    assert out.extra.get("page_count") == 2
    # Per-page comment_url synthesised from candidate.source_url.
    assert (
        out.segments[0]["extra"]["comment_url"]
        == f"/api/v1/library/pdf/{digest}.pdf#page=1"
    )


def test_fetch_text_returns_none_when_upload_missing(monkeypatch, tmp_path):
    from app.sources.pdf import connector as pdf_connector_mod

    monkeypatch.setattr(
        pdf_connector_mod.settings, "PDF_UPLOAD_DIR", str(tmp_path)
    )
    cand = Candidate(
        source_type="pdf",
        source_id="pdf:nonexistent",
        title="Missing",
        source_url="",
    )
    assert PDFConnector().fetch_text(cand) is None


def test_fetch_text_returns_none_when_pdf_corrupt(monkeypatch, tmp_path):
    """A file that exists but isn't a valid PDF → fail-soft None."""
    from app.sources.pdf import connector as pdf_connector_mod

    monkeypatch.setattr(
        pdf_connector_mod.settings, "PDF_UPLOAD_DIR", str(tmp_path)
    )
    digest = "corrupt"
    path = tmp_path / f"{digest}.pdf"
    path.write_bytes(b"not a pdf")
    cand = Candidate(
        source_type="pdf",
        source_id=f"pdf:{digest}",
        title="Bad",
        source_url="",
    )
    assert PDFConnector().fetch_text(cand) is None


def test_upload_path_for_source_id_handles_prefixed_and_bare_ids(monkeypatch, tmp_path):
    from app.sources.pdf import connector as pdf_connector_mod

    monkeypatch.setattr(
        pdf_connector_mod.settings, "PDF_UPLOAD_DIR", str(tmp_path)
    )
    assert upload_path_for_source_id("pdf:abc123").endswith("abc123.pdf")
    assert upload_path_for_source_id("abc123").endswith("abc123.pdf")


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------


def test_connector_source_type_is_pdf():
    assert PDFConnector.source_type == "pdf"
    assert SOURCE_TYPE == "pdf"


def test_connector_registers_under_pdf():
    from app.sources.pdf import connector as _  # noqa: F401

    got = registry.connector_for("pdf")
    assert isinstance(got, PDFConnector)

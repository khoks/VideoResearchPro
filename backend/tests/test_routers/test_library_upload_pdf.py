"""Router tests for ``POST /api/v1/library/upload-pdf`` (S-5.10.4 / D-070).

None existed before 2026-10-19. The first one that matters is the visibility
one: an uploaded PDF has no ``video_id``, and until D-070 the grant written
for it was a silent no-op, so the uploader could never see their own file.

The PDF connector is patched (text extraction is the connector's own test
surface); chunking runs for real; the Chroma write is captured so the test
can assert the chunk carries ``document_id`` — the field retrieval filters
on, and the reason the chunk is now written at all (``insert_chunks`` used
to skip every chunk without a ``video_id``).
"""
from unittest.mock import patch

import pytest

from app.config import settings
from app.sources.types import ExtractedText


class _FakeConnector:
    def __init__(self, extracted):
        self._extracted = extracted

    def fetch_text(self, candidate, **_kw):
        return self._extracted


def _extracted():
    return ExtractedText(
        segments=[
            {"text": "Page one of the paper.", "start": 0.0, "duration": 0.0,
             "extra": {"kind": "page", "comment_url": "#page=1"}},
            {"text": "Page two of the paper.", "start": 1.0, "duration": 0.0,
             "extra": {"kind": "page", "comment_url": "#page=2"}},
        ],
        language="en",
        text_source="pdf",
        word_count=10,
        extra={"page_count": 2},
    )


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))
    return tmp_path / "pdf"


def _upload(client, name="paper.pdf", payload=b"%PDF-1.4\n% fake bytes for the router test\n"):
    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(_extracted())),
        patch("app.routers.library.chroma_service.insert_chunks") as insert,
    ):
        resp = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": (name, payload, "application/pdf")},
        )
    return resp, insert


def test_upload_pdf_creates_document_and_writes_chunks_with_document_id(client, upload_dir):
    resp, insert = _upload(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["deduped"] is False
    assert body["page_count"] == 2
    assert body["word_count"] == 10
    doc_id = body["document_id"]
    assert doc_id
    assert (upload_dir / f"{body['source_id'][len('pdf:'):]}.pdf").exists()

    assert insert.called
    chunks = insert.call_args.args[0]
    assert chunks, "the PDF's text must reach the Chroma write path"
    for chunk in chunks:
        meta = chunk["metadata"]
        assert meta["document_id"] == doc_id
        assert meta["source_type"] == "pdf"
        # No YouTube id for a PDF — and not the string "None" either.
        assert meta["video_id"] == ""


def test_uploaded_pdf_is_visible_in_library_listing(client, upload_dir):
    """D-063/D-070: the uploader sees their own PDF, with the response shape
    the frontend row tolerates — no video_id, no duration, a source_type."""
    resp, _ = _upload(client)
    doc_id = resp.json()["document_id"]

    listing = client.get("/api/v1/library/videos")
    assert listing.status_code == 200, listing.text
    rows = {row["id"]: row for row in listing.json()}
    assert doc_id in rows
    row = rows[doc_id]
    assert row["source_type"] == "pdf"
    assert row["video_id"] is None
    assert row["duration_seconds"] is None
    assert row["channel_id"] is None
    assert row["title"] == "paper"
    assert row["transcript_status"] == "fetched"
    assert row["transcript_word_count"] == 10
    assert row["job_count"] == 0


def test_reupload_dedupes_and_still_grants(client, upload_dir):
    first, _ = _upload(client)
    again, insert = _upload(client)
    assert again.status_code == 201, again.text
    assert again.json()["deduped"] is True
    assert again.json()["document_id"] == first.json()["document_id"]
    assert not insert.called

    # Still exactly one listing row — the grant is idempotent.
    listing = client.get("/api/v1/library/videos").json()
    assert [r["id"] for r in listing].count(first.json()["document_id"]) == 1


def test_upload_rejects_non_pdf_and_empty_files(client, upload_dir):
    bad_ext = client.post(
        "/api/v1/library/upload-pdf", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert bad_ext.status_code == 400
    empty = client.post(
        "/api/v1/library/upload-pdf", files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    assert empty.status_code == 400

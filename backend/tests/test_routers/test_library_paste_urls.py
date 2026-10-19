"""Router tests for ``POST /api/v1/library/paste-urls`` (S-1.5.8).

Regression for the 2026-10-19 defect: ``_ingest_single_paste_url`` read
``current_user`` from a scope that did not have it, so every URL that got
past the blank check raised ``NameError`` and the whole batch 500'd. No
router test exercised the endpoint end-to-end before this file.

The connector and the Chroma write are patched; chunking runs for real so
the per-document metadata path is exercised.
"""
from unittest.mock import patch

from app.sources.types import ExtractedText


class _FakeConnector:
    """Stands in for the article connector: returns fixed text."""

    def __init__(self, extracted):
        self._extracted = extracted
        self.calls = []

    def fetch_text(self, candidate):
        self.calls.append(candidate)
        return self._extracted


def _extracted(title="An essay"):
    return ExtractedText(
        segments=[
            {"text": "First paragraph of the essay.", "start": 0.0, "duration": 0.0},
            {"text": "Second paragraph with more words.", "start": 1.0, "duration": 0.0},
        ],
        language="en",
        text_source="trafilatura",
        word_count=10,
        extra={"extracted_title": title, "extracted_author": "A. Writer"},
    )


def _post(client, urls):
    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(_extracted())),
        patch("app.routers.library.chroma_service.insert_chunks") as insert,
    ):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": urls})
    return resp, insert


def test_paste_urls_creates_then_dedupes(client):
    url = "https://example.com/essay"

    resp, insert = _post(client, [url])
    assert resp.status_code == 201, resp.text
    rows = resp.json()["results"]
    assert len(rows) == 1
    first = rows[0]
    assert first["status"] == "created"
    assert first["deduped"] is False
    assert first["source_type"] == "article"
    assert first["word_count"] == 10
    assert first["document_id"]
    assert insert.called

    # Same URL again: dedup hit, no second Chroma write, same document.
    resp2, insert2 = _post(client, [url])
    assert resp2.status_code == 201, resp2.text
    again = resp2.json()["results"][0]
    assert again["status"] == "deduped"
    assert again["deduped"] is True
    assert again["document_id"] == first["document_id"]
    assert not insert2.called


def test_paste_urls_resolves_social_hosts_and_flags_blank_lines(client):
    resp, _ = _post(
        client,
        [
            "https://x.com/someone/status/1",
            "https://www.linkedin.com/posts/abc",
            "   ",
        ],
    )
    assert resp.status_code == 201, resp.text
    by_url = {r["url"]: r for r in resp.json()["results"]}
    assert by_url["https://x.com/someone/status/1"]["source_type"] == "tweet"
    assert by_url["https://www.linkedin.com/posts/abc"]["source_type"] == "li_post"
    blank = [r for r in resp.json()["results"] if r["status"] == "invalid_url"]
    assert len(blank) == 1


def test_paste_urls_extraction_failure_is_per_row(client):
    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(None)),
        patch("app.routers.library.chroma_service.insert_chunks") as insert,
    ):
        resp = client.post(
            "/api/v1/library/paste-urls", json={"urls": ["https://example.com/empty"]}
        )
    assert resp.status_code == 201, resp.text
    row = resp.json()["results"][0]
    assert row["status"] == "extraction_failed"
    assert row["source_type"] == "article"
    assert "document_id" not in row
    assert not insert.called


def test_paste_urls_rejects_empty_and_oversized_batches(client):
    assert client.post("/api/v1/library/paste-urls", json={"urls": []}).status_code == 400
    assert client.post("/api/v1/library/paste-urls", json={}).status_code == 400
    too_many = [f"https://example.com/{i}" for i in range(101)]
    assert client.post("/api/v1/library/paste-urls", json={"urls": too_many}).status_code == 400


def test_pasted_document_is_visible_in_library_listing(client):
    """D-063 / D-070: the paste path must grant visibility, and the listing
    must render a document that has no channel, duration or thumbnail.

    Was a strict xfail from 2026-10-19 until S-5.10.4 landed: the grant was
    keyed on the legacy ``documents.video_id``, NULL for a pasted page, so
    ``grant()`` dropped the id and the listing's filter never matched."""
    resp, insert = _post(client, ["https://example.com/visible"])
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["results"][0]["document_id"]

    # The chunk that reached Chroma carries the key retrieval filters on.
    chunks = insert.call_args.args[0]
    assert chunks and all(c["metadata"]["document_id"] == doc_id for c in chunks)

    listing = client.get("/api/v1/library/videos")
    assert listing.status_code == 200, listing.text
    rows = {row["id"]: row for row in listing.json()}
    assert doc_id in rows
    row = rows[doc_id]
    assert row["source_type"] == "article"
    assert row["video_id"] is None
    assert row["duration_seconds"] is None
    assert row["channel_id"] is None and row["channel_name"] == ""
    assert row["title"] == "An essay"

"""Two tenants, non-video documents: user B must not see user A's pasted page
or uploaded PDF — in the listing, in the listing's search, or in the set that
library Q&A retrieves from (S-5.10.4 / D-070, acceptance criterion).

Before D-070 this test could not even be written: the grants for these
documents were never stored, so NOBODY saw them, which hid the leak question
behind a data-loss one. Now that grants are keyed on ``document_id`` the
D-063 invariant has to be shown to hold for every source type, not only for
YouTube videos (``tests/test_routers/test_tenant_isolation_leaks.py``).
"""
from unittest.mock import patch

import pytest

from app.config import settings
from app.services import auth_service
from app.sources.types import ExtractedText


class _FakeConnector:
    def __init__(self, extracted):
        self._extracted = extracted

    def fetch_text(self, candidate, **_kw):
        return self._extracted


def _page(title: str) -> ExtractedText:
    return ExtractedText(
        segments=[{"text": f"{title}: the body of the page.", "start": 0.0, "duration": 0.0}],
        language="en",
        text_source="trafilatura",
        word_count=7,
        extra={"extracted_title": title, "extracted_author": "A. Writer"},
    )


def _pdf() -> ExtractedText:
    return ExtractedText(
        segments=[{"text": "A page of the private paper.", "start": 0.0, "duration": 0.0}],
        language="en",
        text_source="pdf",
        word_count=6,
        extra={"page_count": 1},
    )


@pytest.fixture
def user_b_headers(db):
    user_b = auth_service.create_user(db, email="b@example.com", password="testpass123")
    token, _ = auth_service.create_access_token(user_b.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))


def _paste(client, url, title, headers=None):
    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(_page(title))),
        patch("app.routers.library.chroma_service.insert_chunks"),
    ):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": [url]}, headers=headers)
    assert resp.status_code == 201, resp.text
    row = resp.json()["results"][0]
    assert row["status"] == "created", row
    return row["document_id"]


def _upload(client, name, headers=None):
    with (
        patch("app.routers.library._connector_for", return_value=_FakeConnector(_pdf())),
        patch("app.routers.library.chroma_service.insert_chunks"),
    ):
        resp = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": (name, name.encode() + b"%PDF-1.4 distinct bytes", "application/pdf")},
            headers=headers,
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


@pytest.fixture
def two_tenant_library(client, user_b_headers, upload_dir):
    """A (the client's default user) ingests a page and a PDF; B ingests one page."""
    a_page = _paste(client, "https://example.com/a-private-essay", "A Private Essay")
    a_pdf = _upload(client, "a-private-paper.pdf")
    b_page = _paste(client, "https://example.com/b-own-essay", "B Own Essay", headers=user_b_headers)
    return {"a_page": a_page, "a_pdf": a_pdf, "b_page": b_page}


def test_listing_shows_only_the_tenants_own_non_video_documents(client, user_b_headers, two_tenant_library):
    ids = two_tenant_library

    a_rows = {r["id"] for r in client.get("/api/v1/library/videos").json()}
    assert {ids["a_page"], ids["a_pdf"]} <= a_rows
    assert ids["b_page"] not in a_rows

    b_rows = {r["id"] for r in client.get("/api/v1/library/videos", headers=user_b_headers).json()}
    assert b_rows == {ids["b_page"]}


def test_search_cannot_find_another_tenants_document_by_title(client, user_b_headers, two_tenant_library):
    ids = two_tenant_library
    # A finds their own by title; B searching the same title finds nothing.
    mine = client.get("/api/v1/library/videos", params={"search": "Private Essay"}).json()
    assert [r["id"] for r in mine] == [ids["a_page"]]
    theirs = client.get(
        "/api/v1/library/videos", params={"search": "Private Essay"}, headers=user_b_headers
    ).json()
    assert theirs == []
    # The PDF's title ("a-private-paper") is just as invisible to B.
    assert client.get(
        "/api/v1/library/videos", params={"search": "private-paper"}, headers=user_b_headers
    ).json() == []


def test_library_qa_retrieval_scope_excludes_the_other_tenants_documents(
    client, user_b_headers, two_tenant_library
):
    """The router hands the agent exactly the asker's visible document ids;
    the agent filters Chroma on them (service-level proof in
    ``tests/test_services/test_chroma_document_scope.py``)."""
    ids = two_tenant_library
    calls = {}

    def _capture(headers, who):
        with (
            patch("app.agents.qa_agent.run_library_qa_agent",
                  return_value={"answer": "a", "references": []}) as agent,
            patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
        ):
            resp = client.post(
                "/api/v1/library/qa", json={"question": "What does the essay say?"}, headers=headers
            )
        assert resp.status_code == 200, resp.text
        calls[who] = agent.call_args.kwargs

    _capture(None, "a")
    _capture(user_b_headers, "b")

    a_scope = set(calls["a"]["visible_document_ids"])
    b_scope = set(calls["b"]["visible_document_ids"])
    assert a_scope == {ids["a_page"], ids["a_pdf"]}
    assert b_scope == {ids["b_page"]}
    assert not (a_scope & b_scope)
    # The corpus figures follow the same scope — B's statistics count one document.
    assert calls["b"]["corpus_statistics"]["video_count"] == 1
    assert calls["a"]["corpus_statistics"]["video_count"] == 2


def test_tenant_with_nothing_ingested_gets_an_empty_scope_not_everything(client, user_b_headers, upload_dir):
    """B has ingested nothing; A has. B's scope must be [] — the list that
    ``query_collection`` turns into no results, never None."""
    _paste(client, "https://example.com/only-a", "Only A Has This")
    with (
        patch("app.agents.qa_agent.run_library_qa_agent",
              return_value={"answer": "a", "references": []}) as agent,
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post("/api/v1/library/qa", json={"question": "anything"}, headers=user_b_headers)
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["visible_document_ids"] == []

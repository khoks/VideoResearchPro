"""T-1.5.8.4 at the caller: a pasted social post's author and date, from
``POST /library/paste-urls`` to everything they feed.

The real connector runs (``_connector_for`` is not patched); only the fetch
is: ``extract_text`` returns trafilatura's view of a small page written for
the test, with invented names (D-087), and the Chroma write is captured.
What the date and author reach: the document row and its
``source_metadata_json``, the library listing, the chunks (``published_ts``,
``author``), the citation, library Q&A's source list, and the corpus
statistics library Q&A reads (D-072).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from app.agents import qa_agent
from app.models.document import Document
from app.services import corpus_stats_service
from app.services.article_extraction import ExtractionResult

UTC = timezone.utc
X_STATUS_ID = "1764959161537439217"  # 2024-03-05 10:20:30.123 UTC
X_STATUS_TIME = datetime(2024, 3, 5, 10, 20, 30, 123000, tzinfo=UTC)

_BODY = "Tidal storage keeps the grid steady through the night. " * 6


def _extraction(*, html: str, author: str | None = None, published_at: datetime | None = None):
    return ExtractionResult(
        text=_BODY,
        title="A post",
        author=author,
        published_at=published_at,
        language="en",
        word_count=len(_BODY.split()),
        source="trafilatura",
        html=html,
    )


def _paste(client, url: str, extraction: ExtractionResult):
    with (
        patch("app.sources.paste_url.connector.extract_text", return_value=extraction),
        patch("app.routers.library.chroma_service.insert_chunks") as insert,
    ):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": [url]})
    assert resp.status_code == 201, resp.text
    row = resp.json()["results"][0]
    assert row["status"] == "created", row
    return row["document_id"], insert.call_args.args[0]


def test_a_pasted_x_post_carries_its_handle_and_date_everywhere(client, db, test_user):
    """X serves a shell with no metadata; trafilatura names the site. The
    address names the author and dates the post."""
    url = f"https://x.com/quill_feather/status/{X_STATUS_ID}"
    doc_id, chunks = _paste(client, url, _extraction(html="<html><head></head></html>", author="X"))

    doc = db.get(Document, doc_id)
    assert doc.source_type == "tweet"
    assert doc.published_at.replace(tzinfo=UTC) == X_STATUS_TIME
    assert json.loads(doc.source_metadata_json) == {
        "author": "@quill_feather",
        "extractor": "trafilatura",
        "handle": "@quill_feather",
    }

    # The library row.
    listing = {row["id"]: row for row in client.get("/api/v1/library/videos").json()}
    assert listing[doc_id]["published_at"].startswith("2024-03-05T10:20:30")

    # The chunks: the numeric date range filters read, and the author.
    meta = chunks[0]["metadata"]
    assert meta["published_ts"] == int(X_STATUS_TIME.timestamp())
    assert meta["published_year"] == 2024
    assert meta["published_at"].startswith("2024-03-05T10:20:30")
    assert meta["author"] == "@quill_feather"
    assert meta["segment_author"] == "@quill_feather"

    # The citation, and library Q&A's list of sources it may cite.
    _, reference = qa_agent._reference_for_source_type({"metadata": meta})
    assert reference["author"] == "@quill_feather"
    assert reference["channel_name"] == "@quill_feather"
    assert 'by @quill_feather' in qa_agent._build_library_allowed_sources([{"metadata": meta}])

    # The corpus statistics library Q&A reads.
    stats = corpus_stats_service.corpus_statistics_for_tenant(db, test_user.id)
    assert stats["dated_video_count"] == 1
    assert stats["earliest_published"].startswith("2024-03-05")


def test_a_pasted_facebook_post_reads_its_json_ld_over_trafilatura(client, db):
    page = (
        '<html><head><script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "SocialMediaPosting",
                "author": {"@type": "Person", "name": "Tobiah Okonkwo-Lind"},
                "datePublished": "2022-08-19T14:05:00+02:00",
            }
        )
        + "</script></head><body></body></html>"
    )
    doc_id, chunks = _paste(
        client,
        "https://www.facebook.com/tobiah.ol/posts/pfbid0abc",
        _extraction(html=page, author="Facebook", published_at=datetime(2025, 1, 1)),
    )

    doc = db.get(Document, doc_id)
    assert doc.published_at.replace(tzinfo=UTC) == datetime(2022, 8, 19, 12, 5, tzinfo=UTC)
    assert json.loads(doc.source_metadata_json)["author"] == "Tobiah Okonkwo-Lind"
    assert "handle" not in json.loads(doc.source_metadata_json)
    assert chunks[0]["metadata"]["segment_author"] == "Tobiah Okonkwo-Lind"


def test_trafilatura_keeps_what_the_page_does_not_say(client, db):
    """A LinkedIn page with no metadata of its own, and an article, which is
    never read for platform fields: trafilatura's author and date stand,
    and its date is now stored, in UTC."""
    li_id, _ = _paste(
        client,
        "https://www.linkedin.com/posts/odalys-b_tidal-energy-share-1",
        _extraction(html="<html></html>", author="Odalys Brennan", published_at=datetime(2023, 6, 1)),
    )
    article_id, _ = _paste(
        client,
        "https://example.com/tidal-essay",
        _extraction(
            html='<script type="application/ld+json">{"@type": "NewsArticle", "author": "Nobody"}</script>',
            author="A. Writer",
            published_at=datetime(2021, 2, 3, 9, 0, tzinfo=timezone.utc),
        ),
    )

    li = db.get(Document, li_id)
    assert json.loads(li.source_metadata_json)["author"] == "Odalys Brennan"
    assert li.published_at.replace(tzinfo=UTC) == datetime(2023, 6, 1, tzinfo=UTC)
    article = db.get(Document, article_id)
    assert json.loads(article.source_metadata_json)["author"] == "A. Writer"
    assert article.published_at.replace(tzinfo=UTC) == datetime(2021, 2, 3, 9, 0, tzinfo=UTC)


def test_an_undated_post_stores_no_date_and_its_chunks_none(client, db, test_user):
    """D-072: unknown is left out, never a placeholder. A 1970 date from the
    extractor is a placeholder, so it is unknown too."""
    doc_id, chunks = _paste(
        client,
        "https://www.instagram.com/p/C4xYzAbCdEf/",
        _extraction(html="<html></html>", published_at=datetime(1970, 1, 1)),
    )

    assert db.get(Document, doc_id).published_at is None
    meta = chunks[0]["metadata"]
    assert "published_ts" not in meta and "published_year" not in meta
    assert meta["published_at"] == ""
    assert corpus_stats_service.corpus_statistics_for_tenant(db, test_user.id)["dated_video_count"] == 0

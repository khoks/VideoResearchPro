"""T-1.6.7: an article Brave found in a topic job gets the date its page states.

A Brave result carries no date (its ``age`` is "3 hours ago"), so the
``Candidate`` has none, and ``job_tasks`` dated a document from the Candidate
alone. The page's own date has been in ``ExtractedText.extra
["extracted_published_at"]`` since #431 (T-1.5.8.4), and a pasted article used
it; a searched one never did. So every article in a topic job read as undated:
no ``published_ts`` / ``published_year`` on its chunks and no place in the
corpus statistics' publication span.

These run the real topic search and the real resume, with a fake article
connector and no network: the search phase fetches the page to store it, and
the resume fetches any page the search phase could not read.

What must hold (D-072, D-154): the page's date is used only when the row has
none, so it never goes over a Candidate's; it is stored as timezone-aware UTC;
and an unknown or placeholder date is left out, never written as a sentinel.

Mutation check: make ``_fill_published_at`` return at once and every test that
expects a date fails, at the document, the chunk and the statistics.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.transcript_cache import TranscriptCache
from app.services import corpus_stats_service, metadata_backfill_service
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate, ExtractedText
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

PAGE_DATE = datetime(2024, 3, 5, 14, 30, tzinfo=timezone.utc)
FEED_DATE = datetime(2023, 1, 9, 8, 0, tzinfo=timezone.utc)


class _Articles(BaseConnector):
    """Brave-shaped: results with no date, pages that state one."""

    source_type = "article"

    def __init__(self, candidates: list[Candidate], page_dates: dict[str, object]):
        self.candidates = candidates
        self.page_dates = page_dates
        self.unreadable_once: set[str] = set()
        self.fetched: list[str] = []

    def search(self, query, instructions="", limit=10):
        return self.candidates[:limit]

    def list_creator_items(self, *a, **kw):  # pragma: no cover
        return []

    def fetch_metadata(self, *a, **kw):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id="", query=""):
        self.fetched.append(candidate.source_id)
        if candidate.source_id in self.unreadable_once:
            self.unreadable_once.discard(candidate.source_id)
            return None
        return ExtractedText(
            segments=[{"text": f"The body of {candidate.source_id} about tariffs.", "start": 0.0, "duration": 3.0}],
            language="en",
            text_source="paste_extract_trafilatura",
            word_count=6,
            extra={"extracted_title": candidate.title, "extracted_published_at": self.page_dates.get(candidate.source_id)},
        )


def _brave(source_id: str, published_at: datetime | None = None) -> Candidate:
    return Candidate(
        source_type="article",
        source_id=source_id,
        title=f"Article {source_id}",
        source_url=f"https://news.example.com/{source_id}",
        published_at=published_at,
        extra={"brave_age": "3 days ago"},
    )


@pytest.fixture
def articles(monkeypatch):
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    holder: dict = {}

    def install(candidates, page_dates):
        fake = _Articles(candidates, page_dates)
        registry.register(fake)
        holder["fake"] = fake
        return fake

    yield install
    registry._reset_for_tests()
    for connector in snapshot.values():
        registry.register(connector)


@pytest.fixture
def worker(monkeypatch, db):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(job_tasks, "progress_service", MagicMock())
    # Era extraction is a model call, not this test's subject.
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)

    def no_video(*a, **k):  # pragma: no cover - an article-only run never asks
        raise AssertionError("the YouTube search agent ran for an article-only job")

    monkeypatch.setattr("app.agents.search_agent.run_search_agent", no_video)
    return db


def _topic_job(db) -> str:
    job = Job(job_type="topic", topic="tariffs", num_videos=5, status="pending",
              source_types_json='["article"]', tenant_id="tenant-articles")
    db.add(job)
    db.commit()
    return job.id


def _search(job_id: str) -> None:
    job_tasks.execute_topic_job.run(job_id)


def _resume(job_id: str) -> list[dict]:
    """The real resume, its report stubbed. Returns the chunks handed to Chroma."""
    with (
        patch.object(job_tasks, "chroma_service") as chroma,
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.resume_job_after_approval.run(job_id)
    return [c for call in chroma.insert_chunks.call_args_list for c in call.args[0]]


def _doc(db, source_id: str) -> Document:
    db.expire_all()
    return db.query(Document).filter(Document.source_id == source_id).one()


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite gives a stored datetime back without its zone; it was UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _chunk_meta(chunks: list[dict], source_id: str) -> list[dict]:
    found = [c["metadata"] for c in chunks if c["metadata"].get("source_id") == source_id]
    assert found, f"no chunk for {source_id}"
    return found


def test_a_searched_article_takes_its_pages_date_through_to_chunks_and_statistics(db, articles, worker):
    articles([_brave("article:a1")], {"article:a1": PAGE_DATE})
    job_id = _topic_job(db)

    _search(job_id)

    doc = _doc(db, "article:a1")
    assert _as_utc(doc.published_at) == PAGE_DATE

    chunks = _resume(job_id)

    db.expire_all()
    assert db.get(Job, job_id).status == "completed"
    for meta in _chunk_meta(chunks, "article:a1"):
        assert meta["published_ts"] == int(PAGE_DATE.timestamp())
        assert meta["published_year"] == 2024
        assert meta["published_at"].startswith("2024-03-05")
    stats = corpus_stats_service.corpus_statistics_for_document_ids(
        db, corpus_stats_service.approved_document_ids_for_job(db, job_id)
    )
    assert stats["dated_video_count"] == 1
    assert stats["earliest_published"] == stats["latest_published"] == "2024-03-05"
    assert stats["videos_by_year"] == {"2024": 1}


def test_a_page_the_search_could_not_read_is_dated_when_the_resume_reads_it(db, articles, worker):
    """The extraction loop's own fetch: the search phase stored the article
    without text, and the resume is where its page, and its date, arrive."""
    fake = articles([_brave("article:late")], {"article:late": PAGE_DATE})
    fake.unreadable_once.add("article:late")
    job_id = _topic_job(db)

    _search(job_id)
    assert _doc(db, "article:late").published_at is None
    chunks = _resume(job_id)

    assert fake.fetched == ["article:late", "article:late"]
    assert _as_utc(_doc(db, "article:late").published_at) == PAGE_DATE
    assert {m["published_year"] for m in _chunk_meta(chunks, "article:late")} == {2024}


def test_a_candidates_own_date_wins_over_the_page(db, articles, worker):
    """An article from a feed comes with its date; the page never replaces it."""
    articles([_brave("article:fed", published_at=FEED_DATE)], {"article:fed": PAGE_DATE})
    job_id = _topic_job(db)

    _search(job_id)
    chunks = _resume(job_id)

    assert _as_utc(_doc(db, "article:fed").published_at) == FEED_DATE
    assert {m["published_year"] for m in _chunk_meta(chunks, "article:fed")} == {2023}


def test_a_date_already_on_the_shared_row_stays(db, articles, worker):
    """The row is shared across tenants: a later run fills a gap, never rewrites."""
    db.add(Document(source_type="article", source_id="article:known", title="Known",
                    url="https://news.example.com/article:known", published_at=FEED_DATE))
    db.commit()
    articles([_brave("article:known")], {"article:known": PAGE_DATE})

    _search(_topic_job(db))

    assert _as_utc(_doc(db, "article:known").published_at) == FEED_DATE


def test_an_undated_shared_row_takes_the_candidates_date_before_the_pages(db, articles, worker):
    db.add(Document(source_type="article", source_id="article:gap", title="Gap",
                    url="https://news.example.com/article:gap"))
    db.commit()
    articles([_brave("article:gap", published_at=FEED_DATE)], {"article:gap": PAGE_DATE})

    _search(_topic_job(db))

    assert _as_utc(_doc(db, "article:gap").published_at) == FEED_DATE


@pytest.mark.parametrize(
    "page_date",
    [
        None,  # the page states no date
        datetime(1970, 1, 1, tzinfo=timezone.utc),  # a placeholder (D-154)
        datetime(2999, 1, 1, tzinfo=timezone.utc),  # a date in the future
        "2024-03-05",  # not a datetime: the connector contract is a datetime or None
    ],
    ids=["none", "epoch", "future", "string"],
)
def test_an_unknown_date_is_left_out_never_a_sentinel(db, articles, worker, page_date):
    articles([_brave("article:undated")], {"article:undated": page_date})
    job_id = _topic_job(db)

    _search(job_id)
    chunks = _resume(job_id)

    assert _doc(db, "article:undated").published_at is None
    for meta in _chunk_meta(chunks, "article:undated"):
        assert "published_ts" not in meta and "published_year" not in meta
        assert meta["published_at"] == ""
    stats = corpus_stats_service.corpus_statistics_for_document_ids(
        db, corpus_stats_service.approved_document_ids_for_job(db, job_id)
    )
    assert stats["dated_video_count"] == 0 and stats["earliest_published"] is None


def test_a_naive_page_date_is_read_as_utc(db, articles, worker):
    articles([_brave("article:naive")], {"article:naive": datetime(2024, 3, 5, 14, 30)})

    _search(_topic_job(db))

    assert _as_utc(_doc(db, "article:naive").published_at) == PAGE_DATE


def test_mutation_without_the_page_date_the_article_is_undated(db, articles, worker, monkeypatch):
    """The pre-T-1.6.7 rule at the same seam: only the Candidate's date."""
    monkeypatch.setattr(job_tasks, "_fill_published_at", lambda *a, **k: None)
    articles([_brave("article:a1")], {"article:a1": PAGE_DATE})
    job_id = _topic_job(db)

    _search(job_id)
    chunks = _resume(job_id)

    assert _doc(db, "article:a1").published_at is None
    assert all("published_year" not in m for m in _chunk_meta(chunks, "article:a1"))



# ---------------------------------------------------------------------------
# An article already in the library, embedded while it had no date
#
# The search phase fetches every candidate, a library row included, so it can
# date one (the page's date, or a Candidate's date on an undated shared row).
# The resume then reuses that row's stored chunks without inserting them
# again, so they would keep no date while the row and the corpus statistics
# have one. Once the search phase has committed the date, the stored chunks
# are stamped (metadata only, no re-embed). An in-memory Chroma holds them.
#
# Mutation check: ``test_mutation_without_the_stamp_the_stored_chunks_stay_undated``
# takes the stamp out and shows the row dated while its chunks are not.
# ---------------------------------------------------------------------------
LIBRARY_SEGMENTS = [
    {"text": f"An earlier read of the tariff article, paragraph {i}.", "start": float(i * 5), "duration": 5.0}
    for i in range(6)
]


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def _embedded_article(db, chroma, source_id: str, *, published_at: datetime | None = None) -> str:
    """A library article: fetched, embedded, its text cached and its chunks
    stored as the extraction loop wrote them then. Returns its document_id."""
    url = f"https://news.example.com/{source_id}"
    doc = Document(source_type="article", source_id=source_id, title=f"Article {source_id}", url=url,
                   source_url=url, published_at=published_at, transcript_status="fetched",
                   transcript_language="en", embedded_in_chroma=True)
    db.add(doc)
    db.flush()
    db.add(TranscriptCache(document_id=doc.document_id, video_id=None,
                           segments_json=json.dumps(LIBRARY_SEGMENTS), language="en", source="article"))
    db.commit()
    chunks = chunk_transcript(LIBRARY_SEGMENTS, chunk_size=40, chunk_overlap=8,
                              video_metadata=job_tasks._build_video_metadata(doc, "en"))
    assert len(chunks) > 1
    assert chroma.insert_chunks(chunks) == len(chunks)
    return doc.document_id


def _stored(chroma, document_id: str) -> list[dict]:
    got = chroma.get_global_collection().get(where={"document_id": document_id},
                                             include=["metadatas", "documents", "embeddings"])
    return [
        {"id": cid, "meta": meta, "text": text, "embedding": [round(float(x), 6) for x in vector]}
        for cid, meta, text, vector in zip(got["ids"], got["metadatas"], got["documents"], got["embeddings"])
    ]


def _resume_on_chroma(job_id: str) -> None:
    """The real resume against the in-memory Chroma, its report stubbed."""
    with (
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        job_tasks.resume_job_after_approval.run(job_id)


@pytest.mark.parametrize(
    "candidate_date, expected",
    [(None, PAGE_DATE), (FEED_DATE, FEED_DATE)],
    ids=["the-pages-date", "the-candidates-date"],
)
def test_a_library_article_dated_by_the_search_gets_the_date_on_its_stored_chunks(
    db, articles, worker, ephemeral_chroma, candidate_date, expected
):
    document_id = _embedded_article(db, ephemeral_chroma, "article:lib")
    before = _stored(ephemeral_chroma, document_id)
    assert before and all("published_ts" not in c["meta"] and c["meta"]["published_at"] == "" for c in before)
    articles([_brave("article:lib", published_at=candidate_date)], {"article:lib": PAGE_DATE})
    job_id = _topic_job(db)

    _search(job_id)

    assert _as_utc(_doc(db, "article:lib").published_at) == expected
    stamped = _stored(ephemeral_chroma, document_id)
    assert [c["id"] for c in stamped] == [c["id"] for c in before]
    for old, new in zip(before, stamped):
        assert new["meta"]["published_ts"] == int(expected.timestamp())
        assert new["meta"]["published_year"] == expected.year
        assert new["meta"]["published_at"].startswith(expected.date().isoformat())
        # Metadata only: the same text, the same vector, every other key kept.
        assert new["text"] == old["text"] and new["embedding"] == old["embedding"]
        kept = {k: v for k, v in old["meta"].items() if k != "published_at"}
        assert {k: new["meta"].get(k) for k in kept} == kept

    _resume_on_chroma(job_id)

    db.expire_all()
    assert db.get(Job, job_id).status == "completed"
    after = _stored(ephemeral_chroma, document_id)
    assert [c["meta"]["published_year"] for c in after] == [expected.year] * len(before)
    stats = corpus_stats_service.corpus_statistics_for_document_ids(
        db, corpus_stats_service.approved_document_ids_for_job(db, job_id)
    )
    assert stats["dated_video_count"] == 1 and stats["videos_by_year"] == {str(expected.year): 1}


def test_a_library_article_that_had_its_date_is_not_stamped_again(db, articles, worker, ephemeral_chroma):
    """Nothing was dated, so no Chroma read: the stored chunks stay as they are."""
    document_id = _embedded_article(db, ephemeral_chroma, "article:dated", published_at=FEED_DATE)
    before = _stored(ephemeral_chroma, document_id)
    articles([_brave("article:dated")], {"article:dated": PAGE_DATE})

    with patch.object(metadata_backfill_service, "stamp_chunk_temporal_fields") as stamp:
        _search(_topic_job(db))

    stamp.assert_not_called()
    assert _as_utc(_doc(db, "article:dated").published_at) == FEED_DATE
    assert _stored(ephemeral_chroma, document_id) == before


def test_a_new_article_needs_no_stamp_its_chunks_are_built_dated(db, articles, worker):
    """A row the search creates has no stored chunks yet: the resume inserts
    them, dated. Only a row already embedded is stamped."""
    articles([_brave("article:new")], {"article:new": PAGE_DATE})

    with patch.object(metadata_backfill_service, "stamp_chunk_temporal_fields") as stamp:
        _search(_topic_job(db))

    stamp.assert_not_called()
    assert _as_utc(_doc(db, "article:new").published_at) == PAGE_DATE


def test_a_failed_stamp_leaves_the_search_working(db, articles, worker, ephemeral_chroma):
    """Fail-soft, as the era's stamp: the date is on the row, and
    ``backfill_chunk_temporal_fields.py`` reaches the chunks later."""
    _embedded_article(db, ephemeral_chroma, "article:lib")
    articles([_brave("article:lib")], {"article:lib": PAGE_DATE})
    job_id = _topic_job(db)

    with patch.object(metadata_backfill_service, "stamp_chunk_temporal_fields",
                      side_effect=RuntimeError("chroma unavailable")) as stamp:
        _search(job_id)

    stamp.assert_called_once()
    db.expire_all()
    assert db.get(Job, job_id).status == "awaiting_approval"
    assert _as_utc(_doc(db, "article:lib").published_at) == PAGE_DATE


def test_mutation_without_the_stamp_the_stored_chunks_stay_undated(
    db, articles, worker, ephemeral_chroma, monkeypatch
):
    """The review's case with the stamp taken out: the row and the statistics
    are dated, and every stored chunk still has no date."""
    monkeypatch.setattr(job_tasks, "_stamp_dates_on_embedded_chunks", lambda *a, **k: None)
    document_id = _embedded_article(db, ephemeral_chroma, "article:lib")
    articles([_brave("article:lib")], {"article:lib": PAGE_DATE})
    job_id = _topic_job(db)

    _search(job_id)
    _resume_on_chroma(job_id)

    assert _as_utc(_doc(db, "article:lib").published_at) == PAGE_DATE
    assert all("published_ts" not in c["meta"] for c in _stored(ephemeral_chroma, document_id))

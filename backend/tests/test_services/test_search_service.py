"""S-8.2.1 — global search service: FTS5 trigram path and the LIKE fallback.

The two paths are exercised through one parametrised fixture so every
contract test (isolation, empty-for-nobody, caps, shape) runs on both.
FTS-only behaviour (ranking, substrings, scripts, trigger maintenance,
short-query fallback) has its own tests on the `fts` fixture.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, text

from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.services import schema_init_service
from app.services import search_service as svc
from tests.conftest import engine

A = "tenant-a-uuid"
B = "tenant-b-uuid"
NOBODY = "tenant-with-nothing-uuid"

NOW = datetime(2026, 10, 19, 12, 0, 0)


@pytest.fixture(params=["fts5", "like"])
def backend(request, db, monkeypatch):
    """Run the test on the FTS5 index, then again with the process forced onto
    the LIKE path (no index tables at all)."""
    if request.param == "fts5":
        assert svc.ensure_index(engine) == svc.BACKEND_FTS5
        yield svc.BACKEND_FTS5
        svc.drop_index(engine)
    else:
        monkeypatch.setattr(svc, "_backend", svc.BACKEND_LIKE)
        yield svc.BACKEND_LIKE


@pytest.fixture
def fts(db):
    assert svc.ensure_index(engine) == svc.BACKEND_FTS5
    yield
    svc.drop_index(engine)


def _fts_tables() -> set[str]:
    with engine.connect() as c:
        return {r[0] for r in c.exec_driver_sql("select name from sqlite_master where name like 'fts%'")}


def _ids(result: dict, kind: str) -> list[str]:
    return [i["id"] for g in result["groups"] if g["type"] == kind for i in g["items"]]


def _doc(db, tenant: str, *, suffix: str, title: str, description: str = "", channel_id: str | None = None,
         knowledge: str | None = None, created_at: datetime = NOW) -> Document:
    doc = Document(
        document_id=f"doc-{suffix}",
        video_id=f"vid{suffix}"[:20],
        title=title,
        description=description,
        url=f"https://youtu.be/vid{suffix}",
        channel_id=channel_id,
        knowledge_report_md=knowledge,
        knowledge_extracted_at=created_at if knowledge else None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(doc)
    db.commit()
    db.add(DocumentVisibility(document_id=doc.document_id, tenant_id=tenant, source="job"))
    db.commit()
    return doc


def _seed_two_tenants(db) -> None:
    """Every group has one row per tenant, with the same words in both, so a
    leak in any group shows up as the other tenant's id."""
    for t in (A, B):
        ch = Channel(channel_id=f"UC{t}"[:24], name=f"Rate Cuts Channel {t}")
        db.add(ch)
        db.commit()
        db.add(ChannelSubscription(channel_id=ch.channel_id, tenant_id=t, subscribed=True))
        db.commit()
        _doc(db, t, suffix=t, title=f"Interest rate cuts explained {t}", description="the Fed's path",
             channel_id=ch.channel_id, knowledge=f"# Knowledge {t}\n\nRate cuts and the Fed.")
        job = Job(id=f"job-{t}", tenant_id=t, job_type="topic", status="completed",
                  topic=f"Rate cuts research {t}", search_instructions="focus on the Fed", created_at=NOW)
        db.add(job)
        db.commit()
        db.add_all([
            QAExchange(id=f"qa-job-{t}", job_id=job.id, tenant_id=t, question=f"What are rate cuts? {t}", answer="a"),
            LibraryQAExchange(id=f"qa-lib-{t}", tenant_id=t, question=f"Library rate cuts {t}", answer="a"),
            QAHistoryExchange(id=f"qa-hist-{t}", tenant_id=t, question=f"History rate cuts {t}", answer="a"),
        ])
        db.commit()


# ---------------------------------------------------------------------------
# Contracts that hold on both engines
# ---------------------------------------------------------------------------


def test_every_group_is_scoped_to_the_asking_tenant(db, backend):
    _seed_two_tenants(db)
    for me, other in ((A, B), (B, A)):
        res = svc.search(db, me, "rate cuts", limit=10)
        assert res["backend"] == backend
        assert [g["type"] for g in res["groups"]] == list(svc.SEARCH_TYPES)
        for kind in svc.SEARCH_TYPES:
            ids = _ids(res, kind)
            assert ids, f"{kind}: {me} should find their own row"
            assert not any(other in i for i in ids), f"{kind}: leaked {other}'s row to {me}: {ids}"
        assert other not in str(res), f"{other}'s id must not appear anywhere in {me}'s response"


def test_tenant_with_nothing_visible_gets_nothing_never_everything(db, backend):
    """D-063: documents and knowledge reports exist in the shared cache, but a
    tenant holding no visibility grant must see none of them."""
    _seed_two_tenants(db)
    res = svc.search(db, NOBODY, "rate", limit=10)
    assert all(g["items"] == [] for g in res["groups"]), res


def test_non_video_document_without_video_id_is_found_by_its_owner_only(db, backend):
    """D-070: a PDF or pasted page has no legacy `video_id`. Visibility is
    keyed on `document_id`, so the owner finds it and nobody else does. A
    join on `video_id` (the pre-D-070 key) would hide it from its owner."""
    pdf = Document(
        document_id="doc-pdf-1", video_id=None, source_type="pdf", source_id="pdf:abc123",
        title="Annual report on monetary easing", url="/api/v1/library/pdf/abc123.pdf",
        knowledge_report_md="# PDF knowledge\n\nMonetary easing timeline.",
    )
    db.add(pdf)
    db.commit()
    db.add(DocumentVisibility(document_id=pdf.document_id, tenant_id=A, source="pdf_upload"))
    db.commit()

    mine = svc.search(db, A, "monetary easing", types=["documents", "knowledge"], limit=5)
    assert _ids(mine, "documents") == ["doc-pdf-1"]
    assert _ids(mine, "knowledge") == ["doc-pdf-1"]
    doc_item = [g for g in mine["groups"] if g["type"] == "documents"][0]["items"][0]
    assert doc_item["href"] == "/library?document=doc-pdf-1"
    assert doc_item["subtitle"].startswith("pdf")

    theirs = svc.search(db, B, "monetary easing", types=["documents", "knowledge"], limit=5)
    assert all(g["items"] == [] for g in theirs["groups"])


def test_item_shape_and_hrefs(db, backend):
    _seed_two_tenants(db)
    res = svc.search(db, A, "rate cuts", limit=10)
    by_kind = {g["type"]: g["items"] for g in res["groups"]}
    for kind, items in by_kind.items():
        for item in items:
            assert set(item) == {"id", "title", "subtitle", "href", "score"}, kind
    assert by_kind["jobs"][0]["href"] == f"/jobs/job-{A}"
    assert by_kind["documents"][0]["href"] == f"/library?document=doc-{A}"
    assert by_kind["knowledge"][0]["href"].endswith("&view=knowledge")
    assert by_kind["channels"][0]["href"].startswith("/library/channels/UC")
    qa_hrefs = {i["href"] for i in by_kind["qa"]}
    assert f"/jobs/job-{A}?exchange=qa-job-{A}" in qa_hrefs
    assert f"/library/qa?exchange=qa-lib-{A}" in qa_hrefs
    assert f"/qa-history?exchange=qa-hist-{A}" in qa_hrefs


def test_limit_caps_each_group(db, backend):
    for i in range(7):
        _doc(db, A, suffix=f"cap{i}", title=f"Rate cuts episode {i}")
    res = svc.search(db, A, "rate cuts", types=["documents"], limit=3)
    assert len(_ids(res, "documents")) == 3


def test_types_restricts_groups_and_keeps_canonical_order(db, backend):
    _seed_two_tenants(db)
    res = svc.search(db, A, "rate", types=["qa", "jobs"], limit=5)
    assert [g["type"] for g in res["groups"]] == ["jobs", "qa"]


def test_blank_query_returns_empty_groups(db, backend):
    _seed_two_tenants(db)
    res = svc.search(db, A, "   ", limit=5)
    assert res["q"] == "" and all(g["items"] == [] for g in res["groups"])


def test_like_metacharacters_in_the_query_are_literal(db, backend):
    _doc(db, A, suffix="pct", title="100% literal title")
    _doc(db, A, suffix="other", title="Something else entirely")
    res = svc.search(db, A, "100%", types=["documents"], limit=5)
    assert _ids(res, "documents") == ["doc-pct"]


# ---------------------------------------------------------------------------
# FTS5-only behaviour
# ---------------------------------------------------------------------------


def test_title_outranks_description(db, fts):
    _doc(db, A, suffix="body", title="Monetary policy overview", description="rate cuts are mentioned in passing")
    _doc(db, A, suffix="title", title="Rate cuts deep dive", description="")
    res = svc.search(db, A, "rate cuts", types=["documents"], limit=5)
    items = [g for g in res["groups"] if g["type"] == "documents"][0]["items"]
    assert [i["id"] for i in items] == ["doc-title", "doc-body"]
    assert items[0]["score"] > items[1]["score"]


def test_substring_case_insensitive_and_devanagari(db, fts):
    _doc(db, A, suffix="hi", title="भारत की अर्थव्यवस्था और RBI")
    _doc(db, A, suffix="en", title="Interest rate cuts explained")
    assert _ids(svc.search(db, A, "अर्थव्यवस्था", types=["documents"]), "documents") == ["doc-hi"]
    assert _ids(svc.search(db, A, "CUTS", types=["documents"]), "documents") == ["doc-en"]
    assert _ids(svc.search(db, A, "terest", types=["documents"]), "documents") == ["doc-en"]  # mid-word


def test_triggers_keep_the_index_current(db, fts):
    doc = _doc(db, A, suffix="upd", title="Original headline")
    assert _ids(svc.search(db, A, "original", types=["documents"]), "documents") == ["doc-upd"]

    doc.title = "Renamed headline"
    db.commit()
    assert _ids(svc.search(db, A, "original", types=["documents"]), "documents") == []
    assert _ids(svc.search(db, A, "renamed", types=["documents"]), "documents") == ["doc-upd"]

    # An update to an unindexed column must not touch the index.
    doc.transcript_status = "completed"
    db.commit()
    assert _ids(svc.search(db, A, "renamed", types=["documents"]), "documents") == ["doc-upd"]

    db.delete(doc)
    db.commit()
    assert _ids(svc.search(db, A, "renamed", types=["documents"]), "documents") == []


def test_knowledge_group_indexes_only_documents_with_a_report(db, fts):
    doc = _doc(db, A, suffix="k", title="Plain video")
    assert _ids(svc.search(db, A, "quantum", types=["knowledge"]), "knowledge") == []
    doc.knowledge_report_md = "# Report\n\nQuantum tunnelling explained."
    doc.knowledge_extracted_at = NOW
    db.commit()
    assert _ids(svc.search(db, A, "quantum", types=["knowledge"]), "knowledge") == ["doc-k"]
    doc.knowledge_report_md = None
    db.commit()
    assert _ids(svc.search(db, A, "quantum", types=["knowledge"]), "knowledge") == []


def test_short_query_falls_back_to_like_even_with_fts5(db, fts):
    _doc(db, A, suffix="ra", title="Rate cuts")
    res = svc.search(db, A, "ra", types=["documents"], limit=5)
    assert res["backend"] == svc.BACKEND_LIKE
    assert _ids(res, "documents") == ["doc-ra"]


def test_recency_breaks_bm25_ties(db, fts):
    _doc(db, A, suffix="old", title="Rate cuts", created_at=NOW - timedelta(days=30))
    _doc(db, A, suffix="new", title="Rate cuts", created_at=NOW)
    assert _ids(svc.search(db, A, "rate cuts", types=["documents"]), "documents") == ["doc-new", "doc-old"]


def test_qa_groups_cover_all_three_surfaces(db, fts):
    _seed_two_tenants(db)
    ids = _ids(svc.search(db, A, "rate cuts", types=["qa"], limit=10), "qa")
    assert set(ids) == {f"qa-job-{A}", f"qa-lib-{A}", f"qa-hist-{A}"}


def test_channels_visible_through_documents_without_a_subscription_row(db, fts):
    ch = Channel(channel_id="UCviaDocOnly000000000000", name="Seen Through A Video")
    db.add(ch)
    db.commit()
    _doc(db, A, suffix="chdoc", title="irrelevant", channel_id=ch.channel_id)
    assert _ids(svc.search(db, A, "through", types=["channels"]), "channels") == [ch.channel_id]
    assert _ids(svc.search(db, B, "through", types=["channels"]), "channels") == []


# ---------------------------------------------------------------------------
# Engine plumbing
# ---------------------------------------------------------------------------


def test_match_expression_quotes_tokens_and_drops_short_ones():
    assert svc.match_expression("rate cuts") == '"rate" AND "cuts"'
    assert svc.match_expression('say "hi" there') == '"say" AND """hi""" AND "there"'
    assert svc.match_expression("ra cu") is None
    assert svc.match_expression("a  longword ") == '"longword"'


def test_probe_failure_falls_back_to_like_creates_nothing_and_warns(db):
    fake_logger = MagicMock()
    with patch.object(svc, "probe_fts5", return_value=None), patch.object(svc, "logger", fake_logger):
        assert svc.ensure_index(engine) == svc.BACKEND_LIKE
    assert svc.current_backend() == svc.BACKEND_LIKE
    assert not _fts_tables()
    assert fake_logger.warning.called
    assert "FTS5" in fake_logger.warning.call_args.args[0]
    svc.drop_index(engine)  # resets the process-global backend for later tests


def test_ensure_index_is_idempotent_and_rebuilds_only_new_tables(db):
    _doc(db, A, suffix="pre", title="Indexed before the tables existed")
    assert svc.ensure_index(engine) == svc.BACKEND_FTS5
    try:
        # Created now → rebuilt from the base table, so the pre-existing row is found.
        assert _ids(svc.search(db, A, "before", types=["documents"]), "documents") == ["doc-pre"]
        assert svc.ensure_index(engine) == svc.BACKEND_FTS5  # no error, nothing duplicated
        assert _ids(svc.search(db, A, "before", types=["documents"]), "documents") == ["doc-pre"]
        with engine.connect() as c:
            assert c.exec_driver_sql("select count(*) from fts_documents").scalar() == 1
    finally:
        svc.drop_index(engine)


def test_schema_init_ignores_the_search_tables(db, fts):
    live = schema_init_service._live_table_names(engine)
    assert "fts_documents" in _fts_tables()
    assert not any(t.startswith("fts_") for t in live)
    assert "documents" in live


def test_drop_index_removes_tables_and_triggers(db):
    svc.ensure_index(engine)
    svc.drop_index(engine)
    assert not _fts_tables()
    with engine.connect() as c:
        triggers = c.exec_driver_sql("select name from sqlite_master where type='trigger' and name like 'fts_%'").fetchall()
    assert triggers == []
    assert svc.current_backend() == svc.BACKEND_LIKE


# ---------------------------------------------------------------------------
# Latency budget (plan: under 300 ms on 5,000 documents, both paths)
# ---------------------------------------------------------------------------


def _seed_large(db, n_docs: int = 5000, n_qa: int = 2000) -> None:
    docs, grants, qas = [], [], []
    for i in range(n_docs):
        vid = f"bulk{i:07d}"
        title = (
            f"Video {i} on interest rate cuts and the Fed" if i % 7 == 0
            else f"Clip {i} on भारत की अर्थव्यवस्था और RBI policy"
        )
        docs.append({
            "document_id": f"bulk-doc-{i}", "video_id": vid, "source_type": "video", "source_id": vid,
            "title": title, "description": "a description " * 10, "url": f"https://youtu.be/{vid}",
            "transcript_status": "pending", "embedded_in_chroma": False,
            "created_at": NOW - timedelta(minutes=i), "updated_at": NOW,
        })
        grants.append({"id": f"grant-{i}", "document_id": f"bulk-doc-{i}", "tenant_id": A, "source": "job", "created_at": NOW})
    for i in range(n_qa):
        qas.append({
            "id": f"bulk-qa-{i}", "tenant_id": A, "question": f"Question {i} about rate cuts and inflation",
            "answer": "x", "references_json": "[]", "answer_language": "en", "created_at": NOW,
        })
    db.execute(insert(Document.__table__), docs)
    db.execute(insert(DocumentVisibility.__table__), grants)
    db.execute(insert(LibraryQAExchange.__table__), qas)
    db.commit()


def test_latency_under_budget_on_a_large_library(db, backend):
    _seed_large(db)
    assert db.execute(text("select count(*) from documents")).scalar() == 5000

    def timed() -> float:
        t0 = time.perf_counter()
        res = svc.search(db, A, "rate cuts", limit=10)
        elapsed = time.perf_counter() - t0
        assert len(_ids(res, "documents")) == 10 and len(_ids(res, "qa")) == 10
        return elapsed

    best = min(timed() for _ in range(3))
    assert best < 0.3, f"{backend}: {best * 1000:.0f} ms"

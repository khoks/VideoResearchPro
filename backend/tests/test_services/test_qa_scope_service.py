"""S-8.1.4 — the scope of a library question (`library_qa_exchanges.scope_json`).

A scope only narrows the reader's visible set; a scope that resolves to no
documents retrieves nothing; a key the resolver does not know is refused
rather than ignored (ignoring it would widen the question to the library).
"""
import json
from datetime import datetime, timezone

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.schemas.qa_scope import QAScope
from app.services import auth_service, qa_scope_service, shelf_service, visibility_service


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="scope-other@example.com", password="otherpass123")


def _doc(db, vid, granted):
    d = Document(
        video_id=vid, title=vid, url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=60, transcript_status="fetched", created_at=datetime.now(timezone.utc),
    )
    db.add(d)
    db.commit()
    for t in granted:
        visibility_service.grant(db, [d.document_id], t)
    return d


def _job(db, tenant_id, docs):
    job = Job(tenant_id=tenant_id, job_type="topic", topic="t", status="completed", num_videos=len(docs))
    db.add(job)
    db.commit()
    for d in docs:
        db.add(JobVideo(job_id=job.id, video_id=d.video_id, approved=True))
    db.commit()
    return job


@pytest.fixture
def library(db, test_user, other):
    me, them = test_user.id, other.id
    a = _doc(db, "scopevid0001", [me])
    b = _doc(db, "scopevid0002", [me])
    c = _doc(db, "scopevid0003", [me, them])
    theirs = _doc(db, "scopevid0004", [them])
    return {"a": a, "b": b, "c": c, "theirs": theirs}


# ------------------------------------------------------------------ the shape

def test_dump_and_load_round_trip():
    assert qa_scope_service.dump(None) is None
    assert qa_scope_service.dump({}) is None
    assert qa_scope_service.dump(QAScope()) is None
    raw = qa_scope_service.dump({"shelf_id": "s1", "saved_search_id": None})
    assert raw == '{"shelf_id":"s1"}'
    assert qa_scope_service.load(raw) == QAScope(shelf_id="s1")
    both = qa_scope_service.dump(QAScope(shelf_id="s1", saved_search_id="q9"))
    assert both == '{"saved_search_id":"q9","shelf_id":"s1"}', "sorted keys: equal scopes store equal strings"


def test_load_keeps_unknown_keys_and_tolerates_bad_values():
    newer = qa_scope_service.load('{"shelf_id":"s1","tag_id":"t7"}')
    assert newer.shelf_id == "s1"
    assert newer.model_dump()["tag_id"] == "t7", "an older build never drops what a newer one wrote"
    assert qa_scope_service.dump(newer) == '{"shelf_id":"s1","tag_id":"t7"}'
    for bad in (None, "", "not json", "[1,2]", '"text"', "{}", '{"shelf_id": null}'):
        assert qa_scope_service.load(bad) is None


# ------------------------------------------------------------------ resolution

def test_no_scope_is_the_visible_library(db, test_user, other, library):
    mine = qa_scope_service.resolve_document_ids(db, test_user.id, None)
    assert set(mine) == {library["a"].document_id, library["b"].document_id, library["c"].document_id}
    assert library["theirs"].document_id not in mine
    theirs = qa_scope_service.resolve_document_ids(db, other.id, None)
    assert set(theirs) == {library["c"].document_id, library["theirs"].document_id}


def test_provenance_only_scope_does_not_narrow(db, test_user, library):
    whole = qa_scope_service.resolve_document_ids(db, test_user.id, None)
    assert qa_scope_service.resolve_document_ids(db, test_user.id, {"saved_search_id": "q1"}) == whole


def test_shelf_scope_is_its_runs_documents_within_what_i_can_see(db, test_user, library):
    job = _job(db, test_user.id, [library["a"], library["c"], library["theirs"]])
    shelf = shelf_service.create_shelf(db, test_user.id, "Rates")
    shelf_service.add_job(db, shelf, job)
    ids = qa_scope_service.resolve_document_ids(db, test_user.id, {"shelf_id": shelf.id})
    assert set(ids) == {library["a"].document_id, library["c"].document_id}, "never another reader's document"


def test_empty_shelf_retrieves_nothing_never_the_library(db, test_user, library):
    shelf = shelf_service.create_shelf(db, test_user.id, "Empty")
    assert qa_scope_service.resolve_document_ids(db, test_user.id, {"shelf_id": shelf.id}) == []
    # A run whose documents I cannot see is just as empty.
    job = _job(db, test_user.id, [library["theirs"]])
    hidden = shelf_service.create_shelf(db, test_user.id, "Hidden")
    shelf_service.add_job(db, hidden, job)
    assert qa_scope_service.resolve_document_ids(db, test_user.id, {"shelf_id": hidden.id}) == []


def test_another_readers_shelf_is_not_found(db, test_user, other, library):
    theirs = shelf_service.create_shelf(db, other.id, "Theirs")
    with pytest.raises(qa_scope_service.ScopeNotFound):
        qa_scope_service.resolve_document_ids(db, test_user.id, {"shelf_id": theirs.id})
    with pytest.raises(qa_scope_service.ScopeNotFound):
        qa_scope_service.resolve_document_ids(db, test_user.id, {"shelf_id": "no-such-shelf"})


def test_unknown_key_is_refused_not_ignored(db, test_user, library):
    with pytest.raises(qa_scope_service.UnknownScopeKey):
        qa_scope_service.resolve_document_ids(db, test_user.id, {"tag_id": "t1"})
    with pytest.raises(qa_scope_service.UnknownScopeKey):
        qa_scope_service.resolve_document_ids(db, test_user.id, QAScope.model_validate({"channel_id": "UC1"}))


def test_nothing_visible_resolves_to_nothing(db, other):
    assert qa_scope_service.resolve_document_ids(db, other.id, None) == []


# ------------------------------------------------------------------ history

def test_history_carries_each_exchanges_scope(client, db, test_user):
    db.add_all([
        LibraryQAExchange(tenant_id=test_user.id, question="Whole library?", answer="a", references_json="[]"),
        LibraryQAExchange(tenant_id=test_user.id, question="On a shelf?", answer="a", references_json="[]",
                          scope_json=json.dumps({"shelf_id": "s1"})),
        LibraryQAExchange(tenant_id=test_user.id, question="Corrupt scope?", answer="a", references_json="[]",
                          scope_json="{oops"),
    ])
    db.commit()
    rows = {r["question"]: r for r in client.get("/api/v1/library/qa").json()}
    assert rows["Whole library?"]["scope"] is None
    assert rows["On a shelf?"]["scope"] == {"shelf_id": "s1", "saved_search_id": None}
    assert rows["Corrupt scope?"]["scope"] is None

"""S-8.1.4 — shelf-scoped Q&A (`POST /shelves/{id}/qa`, `GET /shelves/{id}/qa`).

The shelf's runs' documents, within what the asker can see, are all the agent
may retrieve, and all the answer may cite. An empty shelf retrieves nothing;
it never widens to the library. Another reader's shelf is a 404 and runs
nothing. Exchanges join the one library history with their scope.
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.services import auth_service, shelf_service, visibility_service


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="shelfqa-other@example.com", password="otherpass123")


@pytest.fixture
def other_headers(other):
    token, _ = auth_service.create_access_token(other.id)
    return {"Authorization": f"Bearer {token}"}


def _doc(db, vid, granted):
    d = Document(
        video_id=vid, title=f"Title {vid}", url=f"https://www.youtube.com/watch?v={vid}",
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


def _ref(doc):
    vid = doc.video_id
    return {
        "video_id": vid, "video_url": f"https://www.youtube.com/watch?v={vid}", "video_title": doc.title,
        "channel_name": "c", "timestamp_seconds": 1, "timestamp_display": "0:01",
        "youtube_link": f"https://www.youtube.com/watch?v={vid}&t=1",
    }


@pytest.fixture
def setup(db, test_user, other):
    me, them = test_user.id, other.id
    a = _doc(db, "shelfqa00001", [me])
    b = _doc(db, "shelfqa00002", [me])
    off_shelf = _doc(db, "shelfqa00003", [me, them])
    theirs = _doc(db, "shelfqa00004", [them])
    shelf = shelf_service.create_shelf(db, me, "Rates")
    shelf_service.add_job(db, shelf, _job(db, me, [a, b]))
    their_shelf = shelf_service.create_shelf(db, them, "Theirs")
    shelf_service.add_job(db, their_shelf, _job(db, them, [off_shelf, theirs]))
    return {"a": a, "b": b, "off": off_shelf, "theirs": theirs, "shelf": shelf, "their_shelf": their_shelf}


def _ask(client, path, refs, headers=None):
    with (
        patch("app.agents.qa_agent.run_library_qa_agent",
              return_value={"answer": "An answer.", "references": refs}) as agent,
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True) as index,
    ):
        resp = client.post(path, json={"question": "What about rates?"}, headers=headers)
    return resp, agent, index


def test_shelf_question_retrieves_and_cites_only_the_shelf(client, db, setup):
    shelf = setup["shelf"]
    resp, agent, index = _ask(client, f"/api/v1/shelves/{shelf.id}/qa", [_ref(setup["a"]), _ref(setup["off"])])
    assert resp.status_code == 200, resp.text
    kwargs = agent.call_args.kwargs
    assert set(kwargs["visible_document_ids"]) == {setup["a"].document_id, setup["b"].document_id}
    assert kwargs["corpus_statistics"]["video_count"] == 2, "the length policy sees the shelf, not the library"

    body = resp.json()
    assert [r["video_id"] for r in body["references"]] == ["shelfqa00001"], "an off-shelf citation is dropped"
    assert body["scope"] == {"shelf_id": shelf.id, "saved_search_id": None}
    row = db.get(LibraryQAExchange, body["id"])
    assert json.loads(row.scope_json) == {"shelf_id": shelf.id}
    assert [r["video_id"] for r in json.loads(row.references_json)] == ["shelfqa00001"]
    index.assert_called_once()  # joins the Q&A library index like any library exchange

    # One history: the library page lists it with its scope; the shelf lists it.
    library = {r["id"]: r for r in client.get("/api/v1/library/qa").json()}
    assert library[body["id"]]["scope"]["shelf_id"] == shelf.id
    assert [r["id"] for r in client.get(f"/api/v1/shelves/{shelf.id}/qa").json()] == [body["id"]]


def test_library_question_is_unscoped_and_stays_off_the_shelf(client, db, setup):
    resp, agent, _ = _ask(client, "/api/v1/library/qa", [_ref(setup["off"])])
    assert resp.status_code == 200, resp.text
    assert set(agent.call_args.kwargs["visible_document_ids"]) == {
        setup["a"].document_id, setup["b"].document_id, setup["off"].document_id,
    }
    assert resp.json()["scope"] is None
    assert resp.json()["references"][0]["video_id"] == "shelfqa00003", "library answers are not filtered"
    assert db.get(LibraryQAExchange, resp.json()["id"]).scope_json is None
    assert client.get(f"/api/v1/shelves/{setup['shelf'].id}/qa").json() == []


def test_empty_shelf_retrieves_nothing_never_the_library(client, db, test_user, setup):
    empty = shelf_service.create_shelf(db, test_user.id, "Empty")
    resp, agent, _ = _ask(client, f"/api/v1/shelves/{empty.id}/qa", [_ref(setup["a"])])
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["visible_document_ids"] == [], "[] means nothing; None would mean everything"
    assert resp.json()["references"] == []


def test_another_readers_shelf_is_404_and_runs_nothing(client, db, test_user, setup):
    for shelf_id in (setup["their_shelf"].id, "no-such-shelf"):
        resp, agent, _ = _ask(client, f"/api/v1/shelves/{shelf_id}/qa", [])
        assert resp.status_code == 404
        agent.assert_not_called()
        assert client.get(f"/api/v1/shelves/{shelf_id}/qa").status_code == 404
    assert db.query(LibraryQAExchange).filter_by(tenant_id=test_user.id).count() == 0


def test_two_readers_shelves_never_mix(client, other_headers, setup):
    mine, _, _ = _ask(client, f"/api/v1/shelves/{setup['shelf'].id}/qa", [])
    theirs, agent, _ = _ask(client, f"/api/v1/shelves/{setup['their_shelf'].id}/qa", [], headers=other_headers)
    assert theirs.status_code == 200, theirs.text
    assert set(agent.call_args.kwargs["visible_document_ids"]) == {
        setup["off"].document_id, setup["theirs"].document_id,
    }
    their_history = client.get(f"/api/v1/shelves/{setup['their_shelf'].id}/qa", headers=other_headers).json()
    assert [r["id"] for r in their_history] == [theirs.json()["id"]]
    my_history = client.get(f"/api/v1/shelves/{setup['shelf'].id}/qa").json()
    assert [r["id"] for r in my_history] == [mine.json()["id"]]
    assert client.get(f"/api/v1/shelves/{setup['shelf'].id}/qa", headers=other_headers).status_code == 404


def test_shelf_history_reads_the_parsed_scope(client, db, test_user, setup):
    shelf = setup["shelf"]
    db.add_all([
        LibraryQAExchange(tenant_id=test_user.id, question="Saved search run", answer="a", references_json="[]",
                          scope_json=json.dumps({"saved_search_id": "q1", "shelf_id": shelf.id}, sort_keys=True,
                                                separators=(",", ":"))),
        LibraryQAExchange(tenant_id=test_user.id, question="Corrupt", answer="a", references_json="[]",
                          scope_json='{"shelf_id":"' + shelf.id + '"'),
    ])
    db.commit()
    questions = [r["question"] for r in client.get(f"/api/v1/shelves/{shelf.id}/qa").json()]
    assert questions == ["Saved search run"], "a saved search on the shelf counts; an unreadable scope does not"


def test_free_tier_can_ask_on_its_shelf(client, test_user, setup):
    assert test_user.tier == "free"
    resp, _, _ = _ask(client, f"/api/v1/shelves/{setup['shelf'].id}/qa", [])
    assert resp.status_code == 200, resp.text

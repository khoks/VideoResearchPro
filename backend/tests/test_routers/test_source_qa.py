"""T-8.4.2.4 — a library question about one source (`POST /library/qa` with
``document_id``).

The knowledge drawer's suggestions are asked about the source the drawer
shows. Retrieval is restricted to exactly that document, the answer may cite
only it, and a source the asker cannot see is a 404 that runs nothing and
spends no quota. The exchange joins the library history with
``scope: {"document_id": …}``, stored by the canonical id (D-070).
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
    return auth_service.create_user(db, email="sourceqa-other@example.com", password="otherpass123")


def _doc(db, granted, *, vid=None, title="Title", source_type="video", channel_id=None):
    d = Document(
        video_id=vid,
        source_type=source_type,
        source_id=vid or f"page-{title}",
        title=title,
        url=f"https://www.youtube.com/watch?v={vid}" if vid else "https://example.com/page",
        duration_seconds=60,
        transcript_status="fetched",
        channel_id=channel_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(d)
    db.commit()
    for t in granted:
        visibility_service.grant(db, [d.document_id], t)
    return d


def _ref(doc):
    vid = doc.video_id
    return {
        "video_id": vid, "document_id": doc.document_id,
        "video_url": doc.url, "video_title": doc.title,
        "channel_name": "c", "timestamp_seconds": 1, "timestamp_display": "0:01",
        "youtube_link": doc.url,
    }


def _note_ref(target_type, target_id):
    return {
        "source_type": "note", "note_id": f"n-{target_id}", "note_target_type": target_type,
        "note_target_id": target_id, "note_created_at": "2026-10-19", "quote": "my note",
        "video_url": "", "video_title": "Your note", "channel_name": "you",
        "timestamp_seconds": 0.0, "timestamp_display": "", "youtube_link": "",
    }


@pytest.fixture
def setup(db, test_user, other):
    me, them = test_user.id, other.id
    return {
        "a": _doc(db, [me], vid="sourceqa0001", title="Rates explained", channel_id="UCrates"),
        "b": _doc(db, [me], vid="sourceqa0002", title="Another talk"),
        "page": _doc(db, [me], source_type="paste_url", title="A pasted page"),
        "shared": _doc(db, [me, them], vid="sourceqa0003", title="Both of us"),
        "theirs": _doc(db, [them], vid="sourceqa0004", title="Not yours"),
    }


def _ask(client, refs, body, path="/api/v1/library/qa", headers=None):
    with (
        patch("app.agents.qa_agent.run_library_qa_agent",
              return_value={"answer": "An answer.", "references": refs}) as agent,
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(path, json={"question": "What does it claim?", **body}, headers=headers)
    return resp, agent


def test_retrieval_is_exactly_the_one_source_and_only_it_is_cited(client, db, setup):
    a, b = setup["a"], setup["b"]
    resp, agent = _ask(client, [_ref(a), _ref(b)], {"document_id": a.document_id})
    assert resp.status_code == 200, resp.text

    kwargs = agent.call_args.kwargs
    assert kwargs["visible_document_ids"] == [a.document_id], "retrieval is that source, not the library"
    assert kwargs["corpus_statistics"]["video_count"] == 1, "the length policy sees one source"

    body = resp.json()
    assert [r["video_id"] for r in body["references"]] == ["sourceqa0001"], "a citation of another source is dropped"
    assert body["scope"]["document_id"] == a.document_id
    row = db.get(LibraryQAExchange, body["id"])
    assert json.loads(row.scope_json) == {"document_id": a.document_id}

    # It joins the one library history, saying what it was asked about.
    history = {r["id"]: r for r in client.get("/api/v1/library/qa").json()}
    assert history[body["id"]]["scope"]["document_id"] == a.document_id


def test_without_a_document_the_question_is_still_the_whole_library(client, setup):
    resp, agent = _ask(client, [], {})
    assert resp.status_code == 200, resp.text
    assert set(agent.call_args.kwargs["visible_document_ids"]) == {
        setup[k].document_id for k in ("a", "b", "page", "shared")
    }
    assert resp.json()["scope"] is None


def test_a_legacy_youtube_id_is_stored_as_the_canonical_document_id(client, db, setup):
    a = setup["a"]
    resp, agent = _ask(client, [], {"document_id": a.video_id})
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["visible_document_ids"] == [a.document_id]
    assert json.loads(db.get(LibraryQAExchange, resp.json()["id"]).scope_json) == {"document_id": a.document_id}


def test_a_source_with_no_video_id_is_scoped_by_its_document_id(client, setup):
    """D-070: a pasted page has no legacy id; keying on it would scope to nothing."""
    page = setup["page"]
    assert page.video_id is None
    resp, agent = _ask(client, [_ref(page)], {"document_id": page.document_id})
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["visible_document_ids"] == [page.document_id]
    assert [r["document_id"] for r in resp.json()["references"]] == [page.document_id]


def test_a_source_the_asker_cannot_see_is_404_and_runs_nothing(client, db, test_user, setup):
    from app.services import quota_metering_service

    with patch.object(quota_metering_service, "record_usage") as record:
        for doc_id in (setup["theirs"].document_id, setup["theirs"].video_id, "no-such-document"):
            resp, agent = _ask(client, [], {"document_id": doc_id})
            assert resp.status_code == 404, resp.text
            assert resp.json()["detail"] == "Source not found"
            agent.assert_not_called()
    record.assert_not_called()
    assert db.query(LibraryQAExchange).filter_by(tenant_id=test_user.id).count() == 0


def test_a_shared_source_is_asked_by_each_reader_alone(client, other, setup):
    token, _ = auth_service.create_access_token(other.id)
    headers = {"Authorization": f"Bearer {token}"}
    shared = setup["shared"]
    resp, agent = _ask(client, [], {"document_id": shared.document_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["visible_document_ids"] == [shared.document_id]
    assert agent.call_args.kwargs["notes_tenant_id"] == other.id
    mine = [r["id"] for r in client.get("/api/v1/library/qa").json()]
    assert resp.json()["id"] not in mine, "another reader's question stays theirs"


def test_notes_are_the_sources_own(client, db, test_user, setup):
    """S-8.5.2: a question about one source draws the notes on it, on its
    knowledge report and on its channel, and the notes on answers asked
    about it before; never a note on another source."""
    a, b = setup["a"], setup["b"]
    on_source, elsewhere = _note_ref("document", a.document_id), _note_ref("document", b.document_id)
    resp, agent = _ask(client, [on_source, elsewhere], {"document_id": a.document_id})
    assert resp.status_code == 200, resp.text
    keys = agent.call_args.kwargs["note_target_keys"]
    assert set(keys) == {
        f"document:{a.document_id}", f"knowledge_artifact:{a.document_id}", "channel:UCrates",
    }
    assert [r.get("note_target_id") for r in resp.json()["references"]] == [a.document_id]

    _, again = _ask(client, [], {"document_id": a.document_id})
    assert f"library_qa_exchange:{resp.json()['id']}" in again.call_args.kwargs["note_target_keys"]
    _, about_b = _ask(client, [], {"document_id": b.document_id})
    assert f"library_qa_exchange:{resp.json()['id']}" not in about_b.call_args.kwargs["note_target_keys"]


def _job(db, tenant_id, docs):
    job = Job(tenant_id=tenant_id, job_type="topic", topic="t", status="completed", num_videos=len(docs))
    db.add(job)
    db.commit()
    for d in docs:
        db.add(JobVideo(job_id=job.id, video_id=d.video_id, approved=True))
    db.commit()
    return job


def test_on_a_shelf_a_document_narrows_never_widens(client, db, test_user, setup):
    a, b = setup["a"], setup["b"]
    shelf = shelf_service.create_shelf(db, test_user.id, "Rates")
    shelf_service.add_job(db, shelf, _job(db, test_user.id, [a]))
    path = f"/api/v1/shelves/{shelf.id}/qa"

    on_shelf, agent = _ask(client, [], {"document_id": a.document_id}, path=path)
    assert on_shelf.status_code == 200, on_shelf.text
    assert agent.call_args.kwargs["visible_document_ids"] == [a.document_id]
    assert on_shelf.json()["scope"]["shelf_id"] == shelf.id
    assert on_shelf.json()["scope"]["document_id"] == a.document_id

    off_shelf, agent = _ask(client, [_ref(b)], {"document_id": b.document_id}, path=path)
    assert off_shelf.status_code == 200, off_shelf.text
    assert agent.call_args.kwargs["visible_document_ids"] == [], "a source off the shelf is nothing, not the library"
    assert agent.call_args.kwargs["note_target_keys"] == []
    assert off_shelf.json()["references"] == []

    hidden, agent = _ask(client, [], {"document_id": setup["theirs"].document_id}, path=path)
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Source not found"
    agent.assert_not_called()


def test_a_blank_document_id_is_refused(client, setup):
    resp, agent = _ask(client, [], {"document_id": ""})
    assert resp.status_code == 422
    agent.assert_not_called()

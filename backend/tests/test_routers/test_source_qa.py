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
from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.services import auth_service, library_qa_service, shelf_service, visibility_service
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript


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


# ------------------------------------------------------------- the real agent
#
# The tests above hand the router a finished ``references`` list. These run
# ``run_library_qa_agent`` itself, over chunks built the way ingest builds
# them (``_build_video_metadata`` plus ``chunk_transcript``), with only
# retrieval and the model stubbed. A reference shape written by hand is how a
# non-YouTube citation looked scoped in a test and was dropped in production.


def _ingested_chunks(doc):
    """What retrieval returns for ``doc``, down to Chroma dropping ``None``."""
    meta = job_tasks._build_video_metadata(doc, "en")
    chunks = chunk_transcript(
        [{"text": "Rates rose because the central bank moved first.", "start": 0.0, "duration": 5.0}],
        video_metadata=meta,
    )
    assert chunks
    return [
        {"text": c["text"], "metadata": {k: v for k, v in c["metadata"].items() if v is not None}, "distance": 0.1}
        for c in chunks
    ]


def _llm_for(answer):
    def build(use_case, **_kwargs):
        response = MagicMock()
        response.content = {
            "qa_sub_query_expansion": "",
            "library_qa_refine_context": "Rates rose because the central bank moved first.",
            "library_qa_formulate_answer": answer,
        }.get(use_case, "[]")
        llm = MagicMock()
        llm.invoke.return_value = response
        return llm

    return build


def _ask_the_agent(client, chunks, body, answer, path="/api/v1/library/qa"):
    with (
        patch.object(qa_agent.chroma_service, "query_collection", return_value=chunks) as query,
        patch.object(qa_agent, "get_llm_for", side_effect=_llm_for(answer)),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post(path, json={"question": "What does it claim?", **body})
    assert resp.status_code == 200, resp.text
    return resp.json(), query


_NON_VIDEO = ["pdf", "article", "tweet", "podcast_episode", "reddit_post", "hn_story", "mastodon_post", "bluesky_post"]


@pytest.mark.parametrize("source_type", _NON_VIDEO)
def test_a_source_with_no_youtube_id_keeps_its_citation(client, db, test_user, source_type):
    """T-8.4.2.4 / D-070: every non-video reference has ``video_id: ""``. Keyed
    on that, the check dropped the citation and the answer lost its sources."""
    title = f"Everything about rates, a {source_type}"
    doc = _doc(db, [test_user.id], source_type=source_type, title=title)

    body, query = _ask_the_agent(
        client, _ingested_chunks(doc), {"document_id": doc.document_id},
        f'Rates rose. [Source: "{title}" by Someone at 0:00]',
    )

    assert query.call_args.kwargs["document_ids"] == [doc.document_id], "retrieval is that source"
    assert [r["document_id"] for r in body["references"]] == [doc.document_id]
    assert body["references"][0]["source_type"] == source_type
    assert body["references"][0]["video_id"] == ""
    stored = json.loads(db.get(LibraryQAExchange, body["id"]).references_json)
    assert [r["document_id"] for r in stored] == [doc.document_id]

    events = db.query(AuditLog).filter(AuditLog.user_id == test_user.id, AuditLog.event == "first_cited_answer").all()
    assert len(events) == 1, "a kept citation is a cited answer"


def test_a_youtube_source_is_still_cited_by_its_own_id(client, db, test_user):
    title = "Rates explained in a video"
    video = _doc(db, [test_user.id], vid="dQw4w9WgXcQ", title=title)
    body, _ = _ask_the_agent(
        client, _ingested_chunks(video), {"document_id": video.document_id},
        f'Rates rose. [Source: "{title}" by Someone at 0:00]',
    )
    assert [(r["document_id"], r["video_id"]) for r in body["references"]] == [(video.document_id, "dQw4w9WgXcQ")]


def test_a_shelf_question_keeps_a_pdf_citation(client, db, test_user):
    """The same check narrows a shelf, which lost these before this page did."""
    title = "A report on central banks"
    pdf = _doc(db, [test_user.id], source_type="pdf", title=title)
    job = Job(tenant_id=test_user.id, job_type="topic", topic="t", status="completed", num_videos=1)
    db.add(job)
    db.commit()
    db.add(JobVideo(job_id=job.id, document_id=pdf.document_id, approved=True))
    db.commit()
    shelf = shelf_service.create_shelf(db, test_user.id, "Rates")
    shelf_service.add_job(db, shelf, job)

    body, query = _ask_the_agent(
        client, _ingested_chunks(pdf), {}, f'Rates rose. [Source: "{title}" by Someone at 0:00]',
        path=f"/api/v1/shelves/{shelf.id}/qa",
    )
    assert query.call_args.kwargs["document_ids"] == [pdf.document_id]
    assert [r["document_id"] for r in body["references"]] == [pdf.document_id]


def test_a_citation_of_another_source_is_dropped_by_document_id(client, db, test_user):
    """The check is exact now, so it still drops what is out of scope when the
    reference has no YouTube id to compare."""
    title = "A page outside the question"
    inside = _doc(db, [test_user.id], source_type="article", title="A page inside the question")
    outside = _doc(db, [test_user.id], source_type="article", title=title)

    body, _ = _ask_the_agent(
        client, _ingested_chunks(outside), {"document_id": inside.document_id},
        f'Rates rose. [Source: "{title}" by Someone at 0:00]',
    )
    assert body["references"] == []


def test_a_reference_naming_no_document_is_left_alone(db, setup):
    """An empty ``video_id`` names nothing; only a real id is compared."""
    a, b = setup["a"], setup["b"]
    nameless = {"source_type": "pdf", "video_id": "", "video_title": "t"}
    no_keys = {"source_type": "pdf", "video_title": "t"}
    foreign_video = {"video_id": b.video_id, "video_title": "t"}
    kept = library_qa_service.within_scope(db, [nameless, no_keys, foreign_video], [a.document_id])
    assert kept == [nameless, no_keys]

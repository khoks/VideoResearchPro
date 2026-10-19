"""S-8.9.1 — `GET /library/graph`.

The graph is built from the caller's visible documents (D-063 / D-070), so
nothing of another reader's — a document, an answer, a channel, a topic —
can appear, and an empty visible set is an empty graph, never everything.
"""
import json
from datetime import datetime, timezone

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.services import auth_service, shelf_service, visibility_service


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="other@example.com", password="otherpass123")


def _doc(db, vid, title, channel, topics, granted, published=None):
    d = Document(
        video_id=vid, title=title, channel_id=channel, url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=60, transcript_status="fetched", created_at=datetime.now(timezone.utc),
        published_at=published or datetime(2026, 1, 1),
        extracted_knowledge_json=json.dumps({"topics": topics}) if topics else None,
    )
    db.add(d)
    db.commit()
    for t in granted:
        visibility_service.grant(db, [d.document_id], t)
    return d


def _ref(vid):
    return {"video_id": vid, "video_url": f"https://www.youtube.com/watch?v={vid}", "youtube_link": f"https://www.youtube.com/watch?v={vid}&t=1",
            "video_title": vid, "channel_name": "x", "timestamp_seconds": 1, "timestamp_display": "0:01"}


@pytest.fixture
def library(db, test_user, other):
    db.add_all([Channel(channel_id="UCgraphA", name="Graph A"), Channel(channel_id="UCgraphB", name="Graph B")])
    db.commit()
    me, them = test_user.id, other.id
    d1 = _doc(db, "graphvid001", "Rates 1", "UCgraphA", ["Monetary policy", "Inflation"], [me])
    d2 = _doc(db, "graphvid002", "Rates 2", "UCgraphA", ["monetary policy", "Inflation", "Housing"], [me, them])
    d3 = _doc(db, "graphvid003", "Housing 1", "UCgraphB", ["Housing"], [me])
    d4 = _doc(db, "graphvid004", "Lonely", None, ["Gardening"], [me])
    secret = _doc(db, "graphvid005", "Their secret", "UCgraphB", ["Secret topic", "Housing"], [them])
    secret2 = _doc(db, "graphvid006", "Their secret 2", "UCgraphB", ["Secret topic"], [them])
    db.add_all([
        LibraryQAExchange(tenant_id=me, question="What about rates?", answer="a", references_json=json.dumps([_ref("graphvid001"), _ref("graphvid002")])),
        LibraryQAExchange(tenant_id=me, question="Cites only theirs", answer="a", references_json=json.dumps([_ref("graphvid005")])),
        LibraryQAExchange(tenant_id=them, question="Their question", answer="a", references_json=json.dumps([_ref("graphvid002")])),
    ])
    db.commit()
    return {"d1": d1, "d2": d2, "d3": d3, "d4": d4, "secret": secret, "secret2": secret2}


def _ids(data, type_=None):
    return {n["id"] for n in data["nodes"] if type_ is None or n["type"] == type_}


def test_global_graph_is_built_from_my_visible_documents(client, library):
    r = client.get("/api/v1/library/graph")
    assert r.status_code == 200, r.text
    data = r.json()
    docs = {n["label"] for n in data["nodes"] if n["type"] == "document"}
    assert docs == {"Rates 1", "Rates 2", "Housing 1", "Lonely"}
    assert _ids(data, "channel") == {"channel:UCgraphA", "channel:UCgraphB"}
    # Topics need two of MY documents: Gardening (1) is under the floor, and
    # "Secret topic" exists only on the other reader's documents.
    assert _ids(data, "topic") == {"topic:monetary policy", "topic:inflation", "topic:housing"}
    topic_labels = {n["label"] for n in data["nodes"] if n["type"] == "topic"}
    assert "Monetary policy" in topic_labels  # a tie goes to the capitalised spelling, whatever the row order

    exchanges = [n for n in data["nodes"] if n["type"] == "exchange"]
    assert [n["label"] for n in exchanges] == ["What about rates?"], "theirs excluded; mine citing only theirs has no edge"

    edge_types = {(e["source"], e["target"], e["type"]) for e in data["edges"]}
    d1 = f"document:{library['d1'].document_id}"
    assert (d1, "channel:UCgraphA", "published_by") in edge_types
    assert (d1, "topic:monetary policy", "about") in edge_types
    assert any(e["type"] == "cites" and e["target"] == d1 for e in data["edges"])
    assert ("topic:inflation", "topic:monetary policy", "co_occurs") in edge_types

    assert data["truncated"] is False
    assert data["total"] == {"documents": 4, "channels": 2, "topics": 3, "exchanges": 1}
    assert "Showing 4 documents" in data["summary"] and "connected group" in data["summary"]


def test_nothing_of_another_reader_leaks(client, library):
    data = client.get("/api/v1/library/graph").json()
    blob = json.dumps(data)
    for leaked in ("Their secret", "Secret topic", "Their question", library["secret"].document_id):
        assert leaked not in blob


def test_empty_visible_set_is_an_empty_graph(client, db, other):
    db.add(Channel(channel_id="UCgraphZ", name="Z"))
    db.commit()
    _doc(db, "graphvid099", "Only theirs", "UCgraphZ", ["Topic", "Other"], [other.id])
    data = client.get("/api/v1/library/graph").json()
    assert data["nodes"] == [] and data["edges"] == []
    assert data["total"] == {"documents": 0, "channels": 0, "topics": 0, "exchanges": 0}
    assert "nothing to draw" in data["summary"]


def test_cap_keeps_the_most_connected_and_flags_truncation(client, library):
    data = client.get("/api/v1/library/graph", params={"limit": 3}).json()
    assert data["truncated"] is True
    assert len(data["nodes"]) == 3
    degrees = [n["degree"] for n in data["nodes"]]
    assert degrees == sorted(degrees, reverse=True)
    kept = _ids(data)
    assert all(e["source"] in kept and e["target"] in kept for e in data["edges"])
    assert "of 10 nodes are shown" in data["summary"]


def test_focus_returns_the_neighbourhood_to_the_given_depth(client, library):
    d3 = f"document:{library['d3'].document_id}"
    one = client.get("/api/v1/library/graph", params={"focus": d3, "depth": 1}).json()
    assert one["focus"] == d3
    assert _ids(one) == {d3, "channel:UCgraphB", "topic:housing"}
    two = client.get("/api/v1/library/graph", params={"focus": d3, "depth": 2}).json()
    assert f"document:{library['d2'].document_id}" in _ids(two), "Rates 2 shares the housing topic"
    assert len(two["nodes"]) > len(one["nodes"])
    # An unknown focus falls back to the global view.
    assert client.get("/api/v1/library/graph", params={"focus": "document:nope"}).json()["focus"] is None


def test_filters_by_channel_job_and_shelf(client, db, test_user, other, library):
    by_channel = client.get("/api/v1/library/graph", params={"channel_id": "UCgraphA"}).json()
    assert {n["label"] for n in by_channel["nodes"] if n["type"] == "document"} == {"Rates 1", "Rates 2"}

    job = Job(tenant_id=test_user.id, job_type="topic", topic="t", status="completed", num_videos=1)
    db.add(job)
    db.commit()
    db.add(JobVideo(job_id=job.id, video_id="graphvid003", approved=True))
    db.commit()
    by_job = client.get("/api/v1/library/graph", params={"job_id": job.id}).json()
    assert {n["label"] for n in by_job["nodes"] if n["type"] == "document"} == {"Housing 1"}

    shelf = shelf_service.create_shelf(db, test_user.id, "S")
    shelf_service.add_job(db, shelf, job)
    by_shelf = client.get("/api/v1/library/graph", params={"shelf_id": shelf.id}).json()
    assert {n["label"] for n in by_shelf["nodes"] if n["type"] == "document"} == {"Housing 1"}
    empty_shelf = shelf_service.create_shelf(db, test_user.id, "Empty")
    assert client.get("/api/v1/library/graph", params={"shelf_id": empty_shelf.id}).json()["nodes"] == []

    their_shelf = shelf_service.create_shelf(db, other.id, "Theirs")
    their_job = Job(tenant_id=other.id, job_type="topic", topic="x", status="completed", num_videos=1)
    db.add(their_job)
    db.commit()
    assert client.get("/api/v1/library/graph", params={"shelf_id": their_shelf.id}).status_code == 404
    assert client.get("/api/v1/library/graph", params={"job_id": their_job.id}).status_code == 404


def test_types_filter_and_job_exchanges(client, db, test_user, library):
    job = Job(tenant_id=test_user.id, job_type="topic", topic="t", status="completed", num_videos=1)
    db.add(job)
    db.commit()
    db.add(QAExchange(job_id=job.id, tenant_id=test_user.id, question="Job question", answer="a", references=json.dumps([_ref("graphvid003")])))
    db.commit()
    data = client.get("/api/v1/library/graph", params={"types": "exchange"}).json()
    assert {n["type"] for n in data["nodes"]} == {"document", "exchange"}
    job_ex = [n for n in data["nodes"] if n["type"] == "exchange" and n["meta"]["kind"] == "job"]
    assert job_ex and job_ex[0]["meta"]["job_id"] == job.id


def test_graph_requires_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/library/graph").status_code == 401

"""S-8.7.2 — `GET /channels/{id}/intelligence`.

Every figure is over the documents of the channel the caller can see
(D-063 / D-070). Two readers on the same channel see different aggregates,
the cache is per reader, an empty visible set is an empty aggregate (never
the channel's global one), and the cache recomputes when its inputs change.
"""
import json
from datetime import datetime, timezone

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.transcript_cache import TranscriptCache
from app.services import auth_service, channel_intelligence_service, visibility_service

CH = "UCintel00000000000000001"


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="other@example.com", password="otherpass123")


def _channel(db):
    db.add(Channel(channel_id=CH, name="Intel Channel"))
    db.commit()


def _doc(db, vid, title, *, published, minutes, knowledge=None, transcript=None, meta=None, granted=()):
    d = Document(
        video_id=vid, title=title, channel_id=CH, url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=int(minutes * 60) if minutes else None,
        published_at=published, transcript_status="fetched" if transcript else "pending",
        created_at=datetime.now(timezone.utc),
        extracted_knowledge_json=json.dumps(knowledge) if knowledge else None,
        knowledge_extracted_at=datetime.now(timezone.utc) if knowledge else None,
        source_metadata_json=json.dumps(meta) if meta else None,
    )
    db.add(d)
    db.commit()
    if transcript:
        db.add(TranscriptCache(
            document_id=d.document_id, video_id=vid, language="en",
            segments_json=json.dumps([{"text": t, "start": i, "duration": 1} for i, t in enumerate(transcript)]),
        ))
        db.commit()
    for tenant in granted:
        visibility_service.grant(db, [d.document_id], tenant)
    return d


def _seed(db, me, them):
    _channel(db)
    mine_a = _doc(
        db, "intelvid001", "Rates explained", published=datetime(2026, 1, 10), minutes=12,
        knowledge={"topics": ["Monetary policy", "Inflation"], "concepts": ["Taylor rule"]},
        transcript=["central banks set interest rates", "inflation targeting and interest rates"],
        granted=[me, them],
    )
    mine_b = _doc(
        db, "intelvid002", "Housing and rates", published=datetime(2026, 3, 2), minutes=45,
        knowledge={"topics": ["monetary policy", "Housing"], "concepts": []},
        transcript=["mortgage rates housing supply", "interest rates and mortgage demand"],
        granted=[me],
    )
    mine_c = _doc(
        db, "intelvid003", "No knowledge yet", published=None, minutes=None, granted=[me],
    )
    # Only the other reader can see this one; its distinctive vocabulary must
    # never reach my aggregate.
    theirs = _doc(
        db, "intelvid004", "Crypto special", published=datetime(2026, 2, 1), minutes=90,
        knowledge={"topics": ["Cryptocurrency"], "concepts": ["Proof of stake"]},
        transcript=["blockchain validators staking", "blockchain consensus staking rewards"],
        granted=[them],
    )
    return mine_a, mine_b, mine_c, theirs


def test_aggregate_over_my_visible_documents(client, db, test_user, other):
    _seed(db, test_user.id, other.id)
    r = client.get(f"/api/v1/channels/{CH}/intelligence")
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["coverage"] == {
        "documents": 3, "with_knowledge": 2, "without_knowledge": 1,
        "ratio": pytest.approx(0.6667, abs=1e-4), "with_transcript": 2,
    }
    # Cadence is contiguous Jan..Mar 2026 with the gap month at zero.
    assert data["cadence"] == {
        "months": [{"month": "2026-01", "count": 1}, {"month": "2026-02", "count": 0}, {"month": "2026-03", "count": 1}],
        "undated": 1,
    }
    buckets = {b["label"]: b["count"] for b in data["durations"]["buckets"]}
    assert buckets["5–15 min"] == 1 and buckets["30–60 min"] == 1 and buckets["1–2 h"] == 0
    assert data["durations"]["unknown"] == 1

    topics = {t["label"]: t["documents"] for t in data["topics"]}
    assert topics["Monetary policy"] == 2, "merged case-insensitively, counted per document"
    assert "Cryptocurrency" not in topics
    assert [c["label"] for c in data["concepts"]] == ["Taylor rule"]

    terms = {k["term"] for k in data["keywords"]}
    assert {"rates", "interest"} <= terms
    assert not terms & {"blockchain", "staking", "validators"}, "another reader's transcript leaked"
    assert data["keywords"][0]["weight"] == 1.0

    assert data["stance"] is None and "social posts" in data["notes"]["stance"]
    assert "Extract knowledge for 1 more" in data["notes"]["topics"]


def test_the_other_reader_sees_their_own_view_and_caches_are_separate(client, db, test_user, other):
    _seed(db, test_user.id, other.id)
    channel = db.get(Channel, CH)
    theirs = channel_intelligence_service.get_intelligence(db, other.id, channel)
    assert theirs["coverage"]["documents"] == 2
    assert {t["label"] for t in theirs["topics"]} >= {"Cryptocurrency"}

    # Their cached row must not be served to me.
    mine = client.get(f"/api/v1/channels/{CH}/intelligence").json()
    assert mine["cached"] is False
    assert mine["coverage"]["documents"] == 3
    assert "Cryptocurrency" not in {t["label"] for t in mine["topics"]}


def test_empty_visible_set_is_empty_not_global(client, db, test_user, other):
    _channel(db)
    _doc(db, "intelvid010", "Not mine", published=datetime(2026, 1, 1), minutes=10,
         knowledge={"topics": ["Secret"]}, transcript=["hidden words everywhere"], granted=[other.id])
    data = client.get(f"/api/v1/channels/{CH}/intelligence").json()
    assert data["coverage"]["documents"] == 0
    assert data["topics"] == [] and data["keywords"] == [] and data["cadence"]["months"] == []
    assert data["qa"]["exchanges"] == 0
    assert "Nothing from this channel" in data["notes"]["documents"]


def test_cache_hits_then_recomputes_when_inputs_change(client, db, test_user, other):
    _seed(db, test_user.id, other.id)
    first = client.get(f"/api/v1/channels/{CH}/intelligence").json()
    assert first["cached"] is False
    second = client.get(f"/api/v1/channels/{CH}/intelligence").json()
    assert second["cached"] is True and second["computed_at"] == first["computed_at"]

    # New knowledge on a visible document changes the fingerprint.
    doc = db.query(Document).filter(Document.video_id == "intelvid003").one()
    doc.extracted_knowledge_json = json.dumps({"topics": ["Fiscal policy"], "concepts": []})
    doc.knowledge_extracted_at = datetime.now(timezone.utc)
    db.commit()
    third = client.get(f"/api/v1/channels/{CH}/intelligence").json()
    assert third["cached"] is False
    assert "Fiscal policy" in {t["label"] for t in third["topics"]}
    assert third["coverage"]["with_knowledge"] == 3

    # A newly granted document does too; refresh forces it regardless.
    assert client.get(f"/api/v1/channels/{CH}/intelligence", params={"refresh": True}).json()["cached"] is False


def test_qa_activity_counts_only_my_exchanges_citing_the_channel(client, db, test_user, other):
    _seed(db, test_user.id, other.id)
    ref = lambda vid: {"video_url": f"https://www.youtube.com/watch?v={vid}", "youtube_link": f"https://www.youtube.com/watch?v={vid}&t=10", "video_title": "t", "channel_name": "Intel Channel", "timestamp_seconds": 10, "timestamp_display": "0:10"}
    db.add_all([
        LibraryQAExchange(tenant_id=test_user.id, question="What sets rates?", answer="a", references_json=json.dumps([ref("intelvid001")])),
        LibraryQAExchange(tenant_id=test_user.id, question="Unrelated", answer="a", references_json=json.dumps([ref("elsewhere01")])),
        # Their exchange cites a document we share; it must not count for me.
        LibraryQAExchange(tenant_id=other.id, question="Their question", answer="a", references_json=json.dumps([ref("intelvid001")])),
        # I cite their private document: it is not in my channel view.
        LibraryQAExchange(tenant_id=test_user.id, question="Crypto?", answer="a", references_json=json.dumps([ref("intelvid004")])),
    ])
    db.commit()
    qa = client.get(f"/api/v1/channels/{CH}/intelligence").json()["qa"]
    assert qa["exchanges"] == 1
    assert [e["question"] for e in qa["recent"]] == ["What sets rates?"]
    assert qa["most_cited"][0]["label"] == "Rates explained"


def test_stance_series_where_classification_exists(client, db, test_user):
    _channel(db)
    for i, (stance, sentiment) in enumerate([("for", "positive"), ("against", "negative"), ("for", "neutral")]):
        _doc(db, f"intelvid02{i}", f"Post {i}", published=datetime(2026, 4 + (i // 2), 5), minutes=None,
             meta={"classification": {"stance": stance, "sentiment": sentiment, "framing": "political"}},
             granted=[test_user.id])
    data = client.get(f"/api/v1/channels/{CH}/intelligence").json()
    assert data["stance"]["classified_documents"] == 3
    assert data["stance"]["stance"] == [
        {"month": "2026-04", "counts": {"for": 1, "against": 1}},
        {"month": "2026-05", "counts": {"for": 1}},
    ]
    assert "stance" not in data["notes"]


def test_unknown_channel_is_404(client):
    assert client.get("/api/v1/channels/UCnope/intelligence").status_code == 404

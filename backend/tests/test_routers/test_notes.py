"""Notes API (M5 / S-8.5.1).

What these assert, in the order the story lists them:

- the router is mounted and the table exists (a request to ``/api/v1/notes``
  answers; an unregistered router would 404, a missing model would 500);
- the closed sets are enforced at the API layer (422), and a selector is
  stored and returned in the W3C shape;
- target existence goes through the tenant's visibility (documents, channels)
  or ownership (jobs, exchanges): a note on something the tenant cannot see
  is a 404 indistinguishable from a missing target (T-8.5.1.4);
- two-tenant isolation on every verb: tenant B cannot read, list, edit or
  delete tenant A's notes, and B's list never contains A's rows;
- a document addressed by its legacy YouTube id and by its canonical
  ``document_id`` is ONE note stream (the plan's open question 2: a note on
  a document shows wherever the document shows);
- delete is soft: gone from reads and lists, present with ``deleted_at``
  when asked for, still a row.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.note import Note
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.services import auth_service, subscription_service

NOTES = "/api/v1/notes"


# ---------------------------------------------------------------------------
# Fixtures: one tenant with a full set of targets, one foreign tenant with
# the same, so every "mine works / theirs 404s" pair reads side by side.
# ---------------------------------------------------------------------------


@pytest.fixture
def other_headers(db):
    user = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    token, _ = auth_service.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}, user


@pytest.fixture
def world(db, test_user, other_headers):
    """Targets of every type for the caller ("mine") and for the other
    tenant ("theirs"). Returns ids keyed by target type."""
    _, other = other_headers
    mine_ch = Channel(channel_id="UCmine0000000000000000", name="My Channel")
    theirs_ch = Channel(channel_id="UCtheirs00000000000000", name="Their Channel")
    sub_only_ch = Channel(channel_id="UCsubonly0000000000000", name="Subscribed Only")
    db.add_all([mine_ch, theirs_ch, sub_only_ch])
    db.commit()

    mine_doc = Document(
        document_id="doc-mine-uuid", video_id="minevid0001",
        channel_id=mine_ch.channel_id, title="My video about tariffs",
        url="https://youtu.be/minevid0001", transcript_status="fetched",
        knowledge_report_md="# report", extracted_knowledge_json='{"topics":["t"]}',
        knowledge_extracted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    mine_doc_no_knowledge = Document(
        document_id="doc-mine-nok", video_id="minevid0002",
        channel_id=mine_ch.channel_id, title="No knowledge yet",
        url="https://youtu.be/minevid0002", transcript_status="fetched",
    )
    theirs_doc = Document(
        document_id="doc-theirs-uuid", video_id="theirvid001",
        channel_id=theirs_ch.channel_id, title="Their video",
        url="https://youtu.be/theirvid001", transcript_status="fetched",
        knowledge_report_md="# theirs", knowledge_extracted_at=datetime(2026, 10, 1),
    )
    db.add_all([mine_doc, mine_doc_no_knowledge, theirs_doc])
    db.commit()
    db.add_all([
        DocumentVisibility(video_id="minevid0001", tenant_id=test_user.id, source="job"),
        DocumentVisibility(video_id="minevid0002", tenant_id=test_user.id, source="job"),
        DocumentVisibility(video_id="theirvid001", tenant_id=other.id, source="job"),
    ])
    subscription_service.set_subscribed(db, sub_only_ch.channel_id, test_user.id, True)

    mine_job = Job(id="job-mine", tenant_id=test_user.id, job_type="topic",
                   topic="Tariff history", status="completed")
    theirs_job = Job(id="job-theirs", tenant_id=other.id, job_type="topic",
                     topic="SECRET", status="completed")
    db.add_all([mine_job, theirs_job])
    db.commit()

    db.add_all([
        QAExchange(id="qa-mine", job_id="job-mine", tenant_id=test_user.id,
                   question="What did Smoot-Hawley do?", answer="Raised tariffs."),
        QAExchange(id="qa-theirs", job_id="job-theirs", tenant_id=other.id,
                   question="their question", answer="their answer"),
        LibraryQAExchange(id="lqa-mine", tenant_id=test_user.id,
                          question="Library question", answer="Library answer"),
        LibraryQAExchange(id="lqa-theirs", tenant_id=other.id,
                          question="their lib q", answer="a"),
        QAHistoryExchange(id="hqa-mine", tenant_id=test_user.id,
                          question="History question", answer="History answer"),
        QAHistoryExchange(id="hqa-theirs", tenant_id=other.id,
                          question="their hist q", answer="a"),
    ])
    db.commit()
    return {
        "mine": {
            "document": "doc-mine-uuid",
            "document_video_id": "minevid0001",
            "document_no_knowledge": "doc-mine-nok",
            "knowledge_artifact": "doc-mine-uuid",
            "job": "job-mine",
            "qa_exchange": "qa-mine",
            "library_qa_exchange": "lqa-mine",
            "qa_history_exchange": "hqa-mine",
            "channel": mine_ch.channel_id,
            "channel_sub_only": sub_only_ch.channel_id,
        },
        "theirs": {
            "document": "doc-theirs-uuid",
            "document_video_id": "theirvid001",
            "knowledge_artifact": "doc-theirs-uuid",
            "job": "job-theirs",
            "qa_exchange": "qa-theirs",
            "library_qa_exchange": "lqa-theirs",
            "qa_history_exchange": "hqa-theirs",
            "channel": theirs_ch.channel_id,
        },
    }


def _post(client, target_type, target_id, body="A note.", **extra):
    return client.post(
        NOTES,
        json={"target_type": target_type, "target_id": target_id, "body_md": body, **extra},
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_router_is_mounted_and_table_exists(client):
    r = client.get(NOTES)
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "limit": 500, "offset": 0}


def test_requires_auth(unauthenticated_client):
    assert unauthenticated_client.get(NOTES).status_code == 401
    assert unauthenticated_client.post(
        NOTES, json={"target_type": "job", "target_id": "x", "body_md": "y"}
    ).status_code == 401


# ---------------------------------------------------------------------------
# Create, read, selector, closed sets
# ---------------------------------------------------------------------------


def test_create_on_visible_document_and_read_back(client, world):
    r = _post(client, "document", world["mine"]["document"], "**Bold** claim about tariffs.")
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["target_type"] == "document"
    assert note["target_id"] == "doc-mine-uuid"
    assert note["target_video_id"] == "minevid0001"
    assert note["target_label"] == "My video about tariffs"
    assert note["body_md"] == "**Bold** claim about tariffs."
    assert note["motivation"] == "commenting"
    assert note["selector"] is None
    assert note["deleted_at"] is None
    # Timestamps carry an offset so a browser never reads them as local.
    assert note["created_at"].endswith("Z") or "+00:00" in note["created_at"]

    r = client.get(f"{NOTES}/{note['id']}")
    assert r.status_code == 200
    assert r.json()["body_md"] == "**Bold** claim about tariffs."


def test_selector_round_trips_in_w3c_shape(client, world):
    selector = {
        "exact": "the tariff of abominations",
        "prefix": "they called it ",
        "suffix": " and it",
        "start_seconds": 83.5,
    }
    r = _post(client, "document", world["mine"]["document"], "Anchor.", motivation="highlighting",
              selector=selector)
    assert r.status_code == 201, r.text
    got = r.json()
    assert got["motivation"] == "highlighting"
    assert got["selector"] == {"type": "TextQuoteSelector", **selector}


@pytest.mark.parametrize(
    "payload",
    [
        {"target_type": "wiki_page", "target_id": "x", "body_md": "y"},
        {"target_type": "job", "target_id": "job-mine", "body_md": "y", "motivation": "shouting"},
        {"target_type": "job", "target_id": "job-mine", "body_md": "   "},
        {"target_type": "job", "target_id": "job-mine", "body_md": ""},
        {"target_type": "job", "target_id": "job-mine", "body_md": "y",
         "selector": {"exact": "x", "start_seconds": -1}},
        {"target_type": "job", "target_id": "job-mine", "body_md": "y",
         "selector": {"prefix": "no exact"}},
    ],
)
def test_closed_sets_and_blank_bodies_are_422(client, world, payload):
    assert client.post(NOTES, json=payload).status_code == 422


def test_body_over_cap_is_422(client, world):
    r = _post(client, "job", world["mine"]["job"], "x" * 20_001)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Every target type: mine works, theirs is a 404
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_type",
    ["document", "knowledge_artifact", "job", "qa_exchange",
     "library_qa_exchange", "qa_history_exchange", "channel"],
)
def test_each_target_type_resolves_for_its_owner(client, world, target_type):
    r = _post(client, target_type, world["mine"][target_type])
    assert r.status_code == 201, r.text
    assert r.json()["target_label"]


@pytest.mark.parametrize(
    "target_type",
    ["document", "knowledge_artifact", "job", "qa_exchange",
     "library_qa_exchange", "qa_history_exchange", "channel"],
)
def test_note_on_a_target_the_tenant_cannot_see_is_404(client, world, target_type):
    """T-8.5.1.4. The target exists — it belongs to someone else — and the
    answer must be the same 404 a nonexistent id gets."""
    r = _post(client, target_type, world["theirs"][target_type])
    assert r.status_code == 404
    assert r.json()["detail"] == "Target not found"
    r2 = _post(client, target_type, "does-not-exist")
    assert r2.status_code == 404
    assert r2.json()["detail"] == r.json()["detail"]


def test_document_note_by_legacy_video_id_is_also_404_when_foreign(client, world):
    assert _post(client, "document", world["theirs"]["document_video_id"]).status_code == 404


def test_channel_visible_through_subscription_alone(client, world):
    r = _post(client, "channel", world["mine"]["channel_sub_only"])
    assert r.status_code == 201, r.text
    assert r.json()["target_label"] == "Subscribed Only"


def test_knowledge_artifact_must_exist(client, world):
    """The artifact is columns on the document; a document the tenant can see
    but has not extracted is not a knowledge artifact yet."""
    r = _post(client, "knowledge_artifact", world["mine"]["document_no_knowledge"])
    assert r.status_code == 404
    # The same document is a fine `document` target.
    assert _post(client, "document", world["mine"]["document_no_knowledge"]).status_code == 201


# ---------------------------------------------------------------------------
# One document, one note stream (open question 2, recommended default)
# ---------------------------------------------------------------------------


def test_legacy_video_id_and_document_id_address_one_note_stream(client, world):
    mine = world["mine"]
    a = _post(client, "document", mine["document_video_id"], "written from the shelf")
    b = _post(client, "document", mine["document"], "written from the job page")
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["target_id"] == b.json()["target_id"] == "doc-mine-uuid"

    by_video = client.get(NOTES, params={"target": f"document:{mine['document_video_id']}"}).json()
    by_doc = client.get(NOTES, params={"target": f"document:{mine['document']}"}).json()
    assert by_video["total"] == by_doc["total"] == 2
    assert {n["body_md"] for n in by_video["items"]} == {
        "written from the shelf", "written from the job page",
    }
    # Newest first.
    assert by_doc["items"][0]["body_md"] == "written from the job page"


def test_list_by_target_rejects_bad_shapes_and_foreign_targets(client, world):
    assert client.get(NOTES, params={"target": "document"}).status_code == 422
    assert client.get(NOTES, params={"target": "wiki:abc"}).status_code == 422
    assert client.get(NOTES, params={"target": "document:"}).status_code == 422
    r = client.get(NOTES, params={"target": f"document:{world['theirs']['document']}"})
    assert r.status_code == 404


def test_list_by_type_and_text_filter(client, world):
    _post(client, "job", world["mine"]["job"], "job note about tariffs")
    _post(client, "document", world["mine"]["document"], "doc note about dumplings")
    _post(client, "channel", world["mine"]["channel"], "channel note about tariffs")

    r = client.get(NOTES, params={"target_type": "job"})
    assert r.status_code == 200
    assert [n["body_md"] for n in r.json()["items"]] == ["job note about tariffs"]

    r = client.get(NOTES, params={"q": "TARIFFS"})
    assert r.json()["total"] == 2
    assert {n["target_type"] for n in r.json()["items"]} == {"job", "channel"}

    r = client.get(NOTES, params={"limit": 1, "offset": 1})
    assert r.json()["total"] == 3 and len(r.json()["items"]) == 1

    assert client.get(NOTES, params={"target_type": "wiki"}).status_code == 422


# ---------------------------------------------------------------------------
# Two-tenant isolation on every verb
# ---------------------------------------------------------------------------


def test_two_tenants_never_see_each_others_notes(client, db, world, other_headers):
    headers_b, _ = other_headers
    mine = _post(client, "job", world["mine"]["job"], "A's private thought").json()
    theirs = client.post(
        NOTES,
        json={"target_type": "job", "target_id": world["theirs"]["job"], "body_md": "B's thought"},
        headers=headers_b,
    )
    assert theirs.status_code == 201, theirs.text
    theirs = theirs.json()

    # Lists are disjoint, including the unfiltered and the include_deleted views.
    a_list = client.get(NOTES, params={"include_deleted": True}).json()
    b_list = client.get(NOTES, params={"include_deleted": True}, headers=headers_b).json()
    assert {n["id"] for n in a_list["items"]} == {mine["id"]}
    assert {n["id"] for n in b_list["items"]} == {theirs["id"]}
    assert "A's private thought" not in client.get(NOTES, headers=headers_b).text
    assert "B's thought" not in client.get(NOTES).text

    # B cannot read, edit or delete A's note; all three are the same 404.
    assert client.get(f"{NOTES}/{mine['id']}", headers=headers_b).status_code == 404
    assert client.put(f"{NOTES}/{mine['id']}", json={"body_md": "vandalised"},
                      headers=headers_b).status_code == 404
    assert client.delete(f"{NOTES}/{mine['id']}", headers=headers_b).status_code == 404
    # ...and A's note is untouched.
    row = db.get(Note, mine["id"])
    assert row.body_md == "A's private thought" and row.deleted_at is None

    # Listing by A's target as B is a 404 on the target, not an empty list.
    r = client.get(NOTES, params={"target": f"job:{world['mine']['job']}"}, headers=headers_b)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update and soft delete
# ---------------------------------------------------------------------------


def test_update_changes_body_keeps_created_at(client, world):
    created = _post(client, "job", world["mine"]["job"], "first draft").json()
    r = client.put(f"{NOTES}/{created['id']}", json={"body_md": "second draft"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["body_md"] == "second draft"
    assert got["created_at"] == created["created_at"]
    assert got["updated_at"] >= created["updated_at"]

    # Motivation and selector are independently updatable; `selector: null` clears.
    r = client.put(f"{NOTES}/{created['id']}",
                   json={"motivation": "tagging", "selector": {"exact": "q"}})
    assert r.json()["motivation"] == "tagging" and r.json()["selector"]["exact"] == "q"
    r = client.put(f"{NOTES}/{created['id']}", json={"selector": None})
    assert r.json()["selector"] is None and r.json()["motivation"] == "tagging"

    assert client.put(f"{NOTES}/{created['id']}", json={"body_md": " "}).status_code == 422
    assert client.put(f"{NOTES}/missing", json={"body_md": "x"}).status_code == 404


def test_delete_is_soft(client, db, world):
    created = _post(client, "job", world["mine"]["job"], "to be withdrawn").json()
    r = client.delete(f"{NOTES}/{created['id']}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True and r.json()["deleted_at"]

    # Gone from reads and live lists...
    assert client.get(f"{NOTES}/{created['id']}").status_code == 404
    assert client.get(NOTES).json()["total"] == 0
    # ...present with deleted_at when asked for (exports carry deletions)...
    withdrawn = client.get(NOTES, params={"include_deleted": True}).json()
    assert withdrawn["total"] == 1 and withdrawn["items"][0]["deleted_at"]
    # ...and still a row, body intact.
    row = db.get(Note, created["id"])
    assert row is not None and row.body_md == "to be withdrawn"

    # A second delete is a 404: the live note is gone.
    assert client.delete(f"{NOTES}/{created['id']}").status_code == 404
    assert client.delete(f"{NOTES}/missing").status_code == 404


def test_note_outlives_its_target(client, db, world):
    """Deleting the job keeps the user's words; the label just goes."""
    created = _post(client, "job", world["mine"]["job"], "kept").json()
    assert created["target_label"] == "Tariff history"
    db.query(QAExchange).filter(QAExchange.job_id == "job-mine").delete()
    db.query(Job).filter(Job.id == "job-mine").delete()
    db.commit()
    r = client.get(f"{NOTES}/{created['id']}")
    assert r.status_code == 200
    assert r.json()["body_md"] == "kept" and r.json()["target_label"] is None

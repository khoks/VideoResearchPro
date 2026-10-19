"""Notes export (S-8.5.3): `GET /exports/notes.jsonl` and `GET /exports/notes.md`.

The JSON-LD stream is the lossless one. The round-trip test holds every
stored column to it, withdrawn notes included: ``parse_note_jsonld`` is the
exact inverse of ``serialize_note_jsonld``, and the stream carries the same
rows the database does, for this tenant and nobody else.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.note import Note
from app.services import auth_service, note_service
from app.services.note_export_service import (
    JSONLD_CONTEXT,
    note_to_columns,
    parse_note_jsonld,
)

JSONL = "/api/v1/exports/notes.jsonl"
MD = "/api/v1/exports/notes.md"


@pytest.fixture
def notes_world(db, test_user):
    """Three notes for the caller (one with a selector, one withdrawn) on two
    target types, plus one note that belongs to another tenant."""
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    doc = Document(
        document_id="doc-mine-uuid", video_id="minevid0001",
        title="My video about tariffs", url="https://youtu.be/minevid0001",
    )
    db.add(doc)
    db.commit()
    db.add(DocumentVisibility(video_id="minevid0001", tenant_id=test_user.id, source="job"))
    db.add_all([
        Job(id="job-mine", tenant_id=test_user.id, job_type="topic",
            topic="Tariff history", status="completed"),
        Job(id="job-theirs", tenant_id=other.id, job_type="topic",
            topic="SECRET", status="completed"),
    ])
    db.commit()

    base = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    n1 = note_service.create_note(
        db, test_user.id, target_type="job", target_id="job-mine",
        body_md="First thought on the **run**.",
    )
    n2 = note_service.create_note(
        db, test_user.id, target_type="document", target_id="minevid0001",
        body_md="Anchored to a moment.\n\nSecond paragraph, with 日本語.",
        motivation="highlighting",
        selector={"type": "TextQuoteSelector", "exact": "tariff of abominations",
                  "prefix": "the ", "start_seconds": 83.5},
    )
    n3 = note_service.create_note(
        db, test_user.id, target_type="document", target_id="doc-mine-uuid",
        body_md="Withdrawn later.",
    )
    foreign = note_service.create_note(
        db, other.id, target_type="job", target_id="job-theirs",
        body_md="THEIR PRIVATE NOTE",
    )
    # Pin distinct, known timestamps so order and round trip are exact.
    for i, n in enumerate((n1, n2, n3, foreign)):
        n.created_at = base + timedelta(minutes=i)
        n.updated_at = base + timedelta(minutes=i, seconds=30)
    db.commit()
    note_service.delete_note(db, test_user.id, n3.id)
    return {"mine": [n1.id, n2.id, n3.id], "foreign": foreign.id}


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------


def test_jsonld_round_trip_is_lossless(client, db, notes_world):
    r = client.get(JSONL)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert 'filename="notes.jsonl"' in r.headers["content-disposition"]

    lines = _lines(r.text)
    assert len(lines) == 3, "every note of this tenant, withdrawn included"
    parsed = [parse_note_jsonld(ln) for ln in lines]

    # Exactly the stored columns, typed, for every row — the inverse holds.
    expected = {
        n.id: note_to_columns(n)
        for n in db.query(Note).filter(Note.id.in_(notes_world["mine"]))
    }
    assert {p["id"]: p for p in parsed} == expected

    # Oldest first.
    assert [p["id"] for p in parsed] == notes_world["mine"]

    # W3C shape on the wire.
    docs = [json.loads(ln) for ln in lines]
    for d in docs:
        assert d["@context"] == JSONLD_CONTEXT
        assert d["type"] == "Annotation"
        assert d["body"]["type"] == "TextualBody"
        assert d["body"]["format"] == "text/markdown"
        assert d["generator"]["name"] == "Pratidhvani"
    anchored = docs[1]
    assert anchored["motivation"] == "highlighting"
    assert anchored["target"]["selector"]["exact"] == "tariff of abominations"
    assert anchored["target"]["selector"]["start_seconds"] == 83.5
    assert anchored["target"]["label"] == "My video about tariffs"
    assert anchored["pratidhvani"]["target_id"] == "doc-mine-uuid"
    assert anchored["pratidhvani"]["target_video_id"] == "minevid0001"
    assert anchored["body"]["value"].endswith("日本語.")
    withdrawn = docs[2]
    assert withdrawn["deleted"] is not None and withdrawn["deleted"].endswith("+00:00")
    assert docs[0]["deleted"] is None


def test_jsonld_never_carries_another_tenants_notes(client, notes_world):
    r = client.get(JSONL)
    assert "THEIR PRIVATE NOTE" not in r.text
    assert notes_world["foreign"] not in r.text


def test_jsonld_can_leave_withdrawn_notes_out(client, notes_world):
    r = client.get(JSONL, params={"include_deleted": "false"})
    lines = _lines(r.text)
    assert len(lines) == 2
    assert all(json.loads(ln)["deleted"] is None for ln in lines)


def test_parse_rejects_foreign_shapes():
    with pytest.raises(ValueError):
        parse_note_jsonld(json.dumps({"id": "x", "type": "Thing"}))
    with pytest.raises(ValueError):
        parse_note_jsonld(json.dumps({"id": "not-a-urn", "type": "Annotation"}))


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_groups_by_target_and_marks_withdrawn(client, notes_world):
    r = client.get(MD)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    text = r.text
    assert text.startswith("# Your notes\n")
    assert "3 notes (1 withdrawn)" in text
    # Type headings in page order, target headings with the raw key.
    assert text.index("## Sources") < text.index("## Research runs")
    assert "### My video about tariffs\n`document:doc-mine-uuid`" in text
    assert "### Tariff history\n`job:job-mine`" in text
    # Bodies verbatim, the anchor rendered, the withdrawal visible.
    assert "First thought on the **run**." in text
    assert "Second paragraph, with 日本語." in text
    assert "*at 1:23 · “tariff of abominations”*" in text
    assert "(withdrawn 2026-" in text
    # Every column survives in the comment line.
    assert "· highlighting · created 2026-10-01T09:01:00+00:00" in text
    assert "THEIR PRIVATE NOTE" not in text


def test_markdown_empty_export_says_so(client):
    r = client.get(MD)
    assert r.status_code == 200
    assert "0 notes" in r.text and "Nothing written yet." in r.text


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_notes_exports_require_auth(unauthenticated_client):
    assert unauthenticated_client.get(JSONL).status_code == 401
    assert unauthenticated_client.get(MD).status_code == 401


def test_notes_exports_accept_query_token(unauthenticated_client, auth_token, db, test_user, notes_world):
    r = unauthenticated_client.get(JSONL, params={"token": auth_token})
    assert r.status_code == 200
    assert len(_lines(r.text)) == 3
    r = unauthenticated_client.get(MD, params={"token": auth_token})
    assert r.status_code == 200
    assert "First thought" in r.text

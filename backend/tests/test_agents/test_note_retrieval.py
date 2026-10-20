"""Notes in retrieval and citations (M5 / S-8.5.2).

Against an in-memory Chroma with the real embedder, as the E-7.1 tests do,
because every guarantee here is about distances:

- the index follows the note: written on create, re-embedded on edit, gone on
  soft delete; the backfill is idempotent and never indexes a withdrawn note;
- every query is per tenant and fail-closed, and job Q&A only sees notes on
  that job's material; a note on a document reaches EVERY job that contains
  the document (D-074 item 1);
- a note that bears on the question reaches the context with its marker and
  the note contract, and an equally relevant note ranks above a transcript
  chunk (weight 1.5); an off-topic note never gets in, whatever its weight;
- an empty library still answers from a matching note;
- an answer that cites the note yields a `note` reference that survives the
  API's response schema;
- the routers pass the asker's tenant and the job scope (verified at the
  caller, not at the function that implements it).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent
from app.agents.prompts.shared import NOTE_ANNOTATION_CONTRACT, NOTE_MARKER_PREFIX
from app.config import settings
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.qa_exchange import QAExchange
from app.schemas.library_qa import LibraryReference
from app.schemas.qa import Reference
from app.services import auth_service, note_index, note_service

DNS_TEXT = (
    "DNS resolves a domain name to an IP address by asking recursive resolvers, "
    "root servers and authoritative name servers in turn."
)
BREAD_TEXT = (
    "Feed the sourdough starter with rye flour, fold the dough every thirty minutes "
    "and bake it in a covered cast-iron pot."
)
QUESTION = "How does DNS resolve a domain name to an IP address?"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", True)
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def world(db, chroma):
    """Two tenants; A owns two jobs sharing one document, B owns a job."""
    a = auth_service.create_user(db, email="notes-a@example.com", password="pw" * 6)
    b = auth_service.create_user(db, email="notes-b@example.com", password="pw" * 6)
    docs = [
        Document(document_id="doc-dns", video_id="dnsvid00001", channel_id=None,
                 title="DNS explained", url="https://youtu.be/dnsvid00001"),
        Document(document_id="doc-bread", video_id="breadvid001", title="Sourdough at home",
                 url="https://youtu.be/breadvid001"),
    ]
    db.add_all(docs)
    db.commit()
    db.add_all([
        DocumentVisibility(document_id="doc-dns", tenant_id=a.id, source="job"),
        DocumentVisibility(document_id="doc-bread", tenant_id=a.id, source="job"),
        DocumentVisibility(document_id="doc-dns", tenant_id=b.id, source="job"),
        Job(id="job-a1", tenant_id=a.id, job_type="topic", topic="networking", status="completed"),
        Job(id="job-a2", tenant_id=a.id, job_type="topic", topic="internet history", status="completed"),
        Job(id="job-a3", tenant_id=a.id, job_type="topic", topic="baking", status="completed"),
        Job(id="job-b", tenant_id=b.id, job_type="topic", topic="b's", status="completed"),
    ])
    db.commit()
    db.add_all([
        JobVideo(job_id="job-a1", video_id="dnsvid00001", approved=True),
        JobVideo(job_id="job-a2", video_id="dnsvid00001", approved=True),
        JobVideo(job_id="job-a3", video_id="breadvid001", approved=True),
        QAExchange(id="qa-a1", job_id="job-a1", tenant_id=a.id, question="q", answer="a"),
    ])
    db.commit()
    return {"a": a, "b": b}


def _note(db, user, target_type, target_id, body):
    note = note_service.create_note(
        db, user.id, target_type=target_type, target_id=target_id, body_md=body
    )
    note_index.sync_note(db, note)
    return note


def _stored(doc: str, title: str, text: str, idx: int = 0) -> dict:
    return {"text": text, "metadata": {
        "document_id": doc, "video_id": doc, "chunk_index": idx,
        "video_title": title, "channel_name": "Net Channel", "timestamp_start": 0.0,
    }}


def _llms(recorded: list, answers: dict | None = None):
    answers = answers or {}

    def factory(use_case, **_kw):
        llm = MagicMock()

        def invoke(messages):
            text = "\n".join(getattr(m, "content", str(m)) for m in messages)
            recorded.append((use_case, text))
            resp = MagicMock()
            if use_case in answers:
                resp.content = answers[use_case]
            elif "sub_query" in use_case:
                resp.content = ""
            elif use_case == "qa_extract_references":
                resp.content = "[]"
            else:
                resp.content = "ok"
            resp.usage_metadata = None
            resp.response_metadata = {}
            return resp

        llm.invoke.side_effect = invoke
        return llm

    return factory


def _sent(recorded, needle: str) -> str:
    return next(text for use_case, text in recorded if needle in use_case)


# ---------------------------------------------------------------------------
# The index follows the note
# ---------------------------------------------------------------------------


def test_index_follows_create_edit_and_soft_delete(db, world, chroma):
    a = world["a"]
    note = _note(db, a, "job", "job-a1", "Ask about DNSSEC next time.")
    col = note_index.get_notes_collection()
    got = col.get(ids=[note_index.note_vector_id(note.id)], include=["documents", "metadatas"])
    assert got["documents"] == ["Ask about DNSSEC next time."]
    meta = got["metadatas"][0]
    assert meta["tenant_id"] == a.id and meta["source_type"] == "note"
    assert meta["target_key"] == "job:job-a1" and meta["channel_name"] == "you"
    assert meta["video_title"].startswith("Your note of ") and "networking" in meta["video_title"]

    note = note_service.update_note(db, a.id, note.id, body_md="Ask about DoH next time.")
    note_index.sync_note(db, note)
    assert col.get(ids=[note_index.note_vector_id(note.id)])["documents"] == ["Ask about DoH next time."]

    note_service.delete_note(db, a.id, note.id)
    note_index.remove_note(note.id)
    assert col.get(ids=[note_index.note_vector_id(note.id)])["ids"] == []


def test_backfill_is_idempotent_and_skips_withdrawn_notes(db, world, chroma):
    a = world["a"]
    live = note_service.create_note(db, a.id, target_type="job", target_id="job-a1", body_md="kept")
    gone = note_service.create_note(db, a.id, target_type="job", target_id="job-a1", body_md="withdrawn")
    note_service.delete_note(db, a.id, gone.id)

    from tests.conftest import TestingSessionLocal

    first = note_index.backfill(TestingSessionLocal)
    second = note_index.backfill(TestingSessionLocal)
    assert first == second == {"upserted": 1, "removed": 1}
    ids = note_index.get_notes_collection().get()["ids"]
    assert ids == [note_index.note_vector_id(live.id)]


def test_disabled_index_writes_and_reads_nothing(db, world, chroma, monkeypatch):
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", False)
    note = _note(db, world["a"], "job", "job-a1", DNS_TEXT)
    assert note_index.query_notes(QUESTION, world["a"].id) == []
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", True)
    assert note_index.get_notes_collection().get(ids=[note_index.note_vector_id(note.id)])["ids"] == []


# ---------------------------------------------------------------------------
# Per tenant, fail-closed, job scope
# ---------------------------------------------------------------------------


def test_query_is_per_tenant_and_fail_closed(db, world, chroma):
    _note(db, world["a"], "document", "doc-dns", DNS_TEXT)
    _note(db, world["b"], "document", "doc-dns", DNS_TEXT + " (B's private copy)")

    a_hits = note_index.query_notes(QUESTION, world["a"].id)
    b_hits = note_index.query_notes(QUESTION, world["b"].id)
    assert len(a_hits) == 1 and a_hits[0]["metadata"]["tenant_id"] == world["a"].id
    assert len(b_hits) == 1 and "B's private copy" in b_hits[0]["text"]
    assert note_index.query_notes(QUESTION, None) == []
    assert note_index.query_notes(QUESTION, "") == []
    assert note_index.query_notes(QUESTION, world["a"].id, target_keys=[]) == []


def test_off_topic_note_fails_the_raw_threshold(db, world, chroma):
    _note(db, world["a"], "job", "job-a3", BREAD_TEXT)
    hits = note_index.query_notes(QUESTION, world["a"].id, distance_threshold=float("inf"))
    assert hits and hits[0]["distance"] > settings.RAG_DISTANCE_THRESHOLD, "precondition"
    assert note_index.query_notes(QUESTION, world["a"].id) == []


def test_job_scope_covers_the_jobs_material_and_follows_the_document(db, world, chroma):
    a = world["a"]
    keys_a1 = note_index.job_target_keys(db, "job-a1", ["doc-dns"])
    assert {"job:job-a1", "document:doc-dns", "knowledge_artifact:doc-dns", "qa_exchange:qa-a1"} <= set(keys_a1)

    _note(db, a, "document", "doc-dns", DNS_TEXT)  # written from job a1's page
    _note(db, a, "job", "job-a3", "DNS notes do not belong to the baking run: " + DNS_TEXT)

    keys_a2 = note_index.job_target_keys(db, "job-a2", ["doc-dns"])
    a2 = note_index.query_notes(QUESTION, a.id, target_keys=keys_a2)
    assert [h["metadata"]["target_key"] for h in a2] == ["document:doc-dns"], (
        "a note on a document reaches every job that contains it, and nothing else"
    )


# ---------------------------------------------------------------------------
# Through the agent
# ---------------------------------------------------------------------------


def test_library_qa_brings_a_matching_note_with_its_marker_and_contract(db, world, chroma):
    chroma.insert_chunks([_stored("doc-bread", "Sourdough at home", BREAD_TEXT)])
    note = _note(db, world["a"], "document", "doc-dns", "My take: " + DNS_TEXT)
    recorded: list = []
    with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded)):
        qa_agent.run_library_qa_agent(
            question=QUESTION, visible_document_ids=["doc-bread"], notes_tenant_id=world["a"].id
        )
    # Notes skip the lossy refine step (the live check found it dropping
    # them) and reach the answer step verbatim, under their marker.
    refines = [text for use_case, text in recorded if "refine_context" in use_case]
    assert all("My take" not in r and NOTE_MARKER_PREFIX not in r for r in refines)
    answer_call = _sent(recorded, "formulate_answer")
    assert f"{NOTE_MARKER_PREFIX}, {note.created_at.date().isoformat()}" in answer_call
    assert "My take: DNS resolves" in answer_call
    assert NOTE_ANNOTATION_CONTRACT.splitlines()[0] in answer_call
    assert "by you" in answer_call, "the note is on the allowed-sources list"


def test_without_notes_the_prompts_carry_no_note_contract(db, world, chroma):
    chroma.insert_chunks([_stored("doc-dns", "DNS explained", DNS_TEXT)])
    recorded: list = []
    with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded)):
        qa_agent.run_library_qa_agent(
            question=QUESTION, visible_document_ids=["doc-dns"], notes_tenant_id=world["a"].id
        )
    everything = "\n".join(t for _u, t in recorded)
    assert NOTE_ANNOTATION_CONTRACT.splitlines()[0] not in everything


def test_an_equally_relevant_note_ranks_above_the_transcript_chunk(db, world, chroma, monkeypatch):
    chroma.insert_chunks([_stored("doc-dns", "DNS explained", DNS_TEXT)])
    _note(db, world["a"], "document", "doc-dns", DNS_TEXT)

    def first_in_refine(weight: float) -> str:
        monkeypatch.setattr(settings, "NOTE_RETRIEVAL_WEIGHT", weight)
        recorded: list = []
        with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded)):
            qa_agent.run_library_qa_agent(
                question=QUESTION, visible_document_ids=["doc-dns"], notes_tenant_id=world["a"].id
            )
        # The allowed-sources list follows the merged rank order.
        answer_call = _sent(recorded, "formulate_answer")
        listed = answer_call[answer_call.index("Allowed sources ("):]
        listed = listed[: listed.index("Relevant context")]
        note_at, chunk_at = listed.index("by you"), listed.index("by Net Channel")
        return "note" if note_at < chunk_at else "chunk"

    assert first_in_refine(1.5) == "note"
    # Same text, so the raw distances tie; below 1.0 the note sinks.
    assert first_in_refine(0.5) == "chunk"


def test_an_off_topic_note_never_enters_even_at_the_max_weight(db, world, chroma, monkeypatch):
    monkeypatch.setattr(settings, "NOTE_RETRIEVAL_WEIGHT", 2.0)
    chroma.insert_chunks([_stored("doc-dns", "DNS explained", DNS_TEXT)])
    _note(db, world["a"], "job", "job-a3", BREAD_TEXT)
    recorded: list = []
    with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded)):
        qa_agent.run_library_qa_agent(
            question=QUESTION, visible_document_ids=["doc-dns"], notes_tenant_id=world["a"].id
        )
    everything = "\n".join(t for _u, t in recorded)
    assert "rye flour" not in everything and NOTE_MARKER_PREFIX not in everything


def test_an_empty_library_still_answers_from_a_matching_note_only(db, world, chroma):
    _note(db, world["a"], "job", "job-a1", "DNS resolves names to IP addresses; I tested it with dig.")
    _note(db, world["a"], "job", "job-a3", BREAD_TEXT)
    recorded: list = []
    with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded)):
        qa_agent.run_library_qa_agent(
            question=QUESTION, visible_document_ids=[], notes_tenant_id=world["a"].id
        )
    answer_call = _sent(recorded, "formulate_answer")
    assert "I tested it with dig" in answer_call
    assert "rye flour" not in answer_call
    assert not any("refine_context" in u for u, _t in recorded), "only notes matched: nothing to refine"


def test_another_tenants_note_never_reaches_the_prompt(db, world, chroma):
    _note(db, world["b"], "document", "doc-dns", "B ONLY: " + DNS_TEXT)
    recorded: list = []
    with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded)):
        qa_agent.run_library_qa_agent(
            question=QUESTION, visible_document_ids=[], notes_tenant_id=world["a"].id
        )
        qa_agent.run_qa_agent(
            job_id="job-a1", job_type="channel", question=QUESTION, document_ids=["doc-dns"],
            notes_tenant_id=world["a"].id,
            note_target_keys=note_index.job_target_keys(db, "job-a1", ["doc-dns"]),
        )
    assert "B ONLY" not in "\n".join(t for _u, t in recorded)


def test_job_qa_cites_the_note_as_a_note_reference(db, world, chroma):
    note = _note(db, world["a"], "document", "doc-dns", DNS_TEXT)
    meta = note_index.get_notes_collection().get(ids=[note_index.note_vector_id(note.id)])["metadatas"][0]
    title = meta["video_title"]
    recorded: list = []
    answers = {"qa_formulate_answer": f'You noted that DNS walks the resolver chain [Source: "{title}" by you].'}
    with patch.object(qa_agent, "get_llm_for", side_effect=_llms(recorded, answers)):
        answer, refs = qa_agent.run_qa_agent(
            job_id="job-a2", job_type="channel", question=QUESTION, document_ids=["doc-dns"],
            notes_tenant_id=world["a"].id,
            note_target_keys=note_index.job_target_keys(db, "job-a2", ["doc-dns"]),
        )
    assert "unverified" not in answer, "the note citation is grounded, not stripped"
    note_refs = [r for r in refs if r.get("source_type") == "note"]
    assert len(note_refs) == 1
    ref = note_refs[0]
    assert ref["note_id"] == note.id
    assert ref["note_target_type"] == "document" and ref["note_target_id"] == "doc-dns"
    assert ref["note_created_at"].startswith(note.created_at.date().isoformat())
    assert ref["quote"].startswith("DNS resolves")
    # The API's response schemas keep every field (they used to drop them).
    assert Reference.model_validate(ref).model_dump()["note_id"] == note.id
    lib = LibraryReference.model_validate({**ref, "video_id": ""}).model_dump()
    assert lib["source_type"] == "note" and lib["note_target_id"] == "doc-dns"


def test_reference_schemas_keep_polymorphic_fields():
    """Regression: `extra="ignore"` stripped source_type and permalink, so a
    Reddit citation reached the browser as a YouTube link."""
    reddit = {
        "source_type": "reddit_post", "permalink": "https://reddit.com/r/x/comments/1#comment-2",
        "video_url": "https://reddit.com/r/x/comments/1", "video_title": "t", "channel_name": "r/x",
        "timestamp_seconds": 0.0, "timestamp_display": "", "youtube_link": "",
    }
    dumped = Reference.model_validate(reddit).model_dump()
    assert dumped["source_type"] == "reddit_post" and dumped["permalink"].endswith("#comment-2")


# ---------------------------------------------------------------------------
# At the callers
# ---------------------------------------------------------------------------


def test_job_router_passes_the_tenant_and_the_job_scope(client, db, test_user):
    db.add(Document(document_id="d1", video_id="vid00000001", title="t", url="https://youtu.be/vid00000001"))
    job = Job(job_type="topic", topic="t", status="completed", tenant_id=test_user.id)
    db.add(job)
    db.commit()
    db.add(JobVideo(job_id=job.id, video_id="vid00000001", approved=True))
    db.commit()
    with patch("app.agents.qa_agent.run_qa_agent", return_value=("answer", [])) as agent, \
         patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True):
        r = client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me"})
    assert r.status_code == 200, r.text
    kwargs = agent.call_args.kwargs
    assert kwargs["notes_tenant_id"] == test_user.id
    assert {f"job:{job.id}", "document:d1", "knowledge_artifact:d1"} <= set(kwargs["note_target_keys"])


def test_library_router_passes_the_tenant(client, test_user):
    with patch("app.agents.qa_agent.run_library_qa_agent",
               return_value={"answer": "a", "references": []}) as agent, \
         patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True):
        r = client.post("/api/v1/library/qa", json={"question": "What is DNS?"})
    assert r.status_code == 200, r.text
    assert agent.call_args.kwargs["notes_tenant_id"] == test_user.id


def test_notes_router_keeps_the_index_in_step(client, db, test_user, chroma):
    db.add(Job(id="job-r", tenant_id=test_user.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    created = client.post("/api/v1/notes", json={"target_type": "job", "target_id": "job-r",
                                                  "body_md": "indexed on write"}).json()
    col = note_index.get_notes_collection()
    vid = note_index.note_vector_id(created["id"])
    assert col.get(ids=[vid])["documents"] == ["indexed on write"]
    client.put(f"/api/v1/notes/{created['id']}", json={"body_md": "re-embedded on edit"})
    assert col.get(ids=[vid])["documents"] == ["re-embedded on edit"]
    client.delete(f"/api/v1/notes/{created['id']}")
    assert col.get(ids=[vid])["ids"] == []

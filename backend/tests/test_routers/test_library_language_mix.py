"""T-1.16.1.7 at the library's production callers.

``/library/upload-pdf`` and ``/library/paste-urls`` chunk a document inside
the request; both must store the language profile on the document, and the
library and job listings must expose it read-only. The connector's text
extraction is the only thing faked; chunking and the Chroma insert run for
real against an ephemeral collection.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.services import code_mixing_service
from app.sources.types import ExtractedText

# Romanised Hindi-English, the case the caption-track label cannot see: the
# extractor calls it `en`.
HINGLISH = [
    "yaar ye video bahut accha hai, maine socha ki main bhi try karunga.",
    "taaki baadme koi kasar koi zarra na reh jaye, sab kuch dhyan se dekhna.",
    "mujhe lagta hai ki ye tareeka sabke liye kaam karega agar aap mehnat karo.",
    "phir bhi kuch log kehte hain ki isme time bahut lagta hai aur paisa bhi.",
]
ENGLISH = [
    "Tidal energy storage works by holding water behind a barrage.",
    "Pumped storage moves water uphill when electricity is cheap.",
    "The stored water is released through turbines when demand peaks.",
]


class _FakeConnector:
    def __init__(self, extracted):
        self._extracted = extracted

    def fetch_text(self, candidate, **_kw):
        return self._extracted


def _extracted(sentences: list[str], *, text_source: str, language: str = "en") -> ExtractedText:
    return ExtractedText(
        segments=[{"text": s, "start": float(i), "duration": 0.0} for i, s in enumerate(sentences)],
        language=language,
        text_source=text_source,
        word_count=sum(len(s.split()) for s in sentences),
        extra={"page_count": 1, "extracted_title": "A page", "extracted_author": "A. Writer"},
    )


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))
    return tmp_path / "pdf"


def _upload_pdf(client, sentences: list[str]) -> str:
    extracted = _extracted(sentences, text_source="pdf")
    with patch("app.routers.library._connector_for", return_value=_FakeConnector(extracted)):
        resp = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": ("notes.pdf", b"%PDF-1.4\n% language mix\n", "application/pdf")},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


def _paste(client, sentences: list[str], url: str = "https://example.com/tidal") -> str:
    extracted = _extracted(sentences, text_source="trafilatura")
    with patch("app.routers.library._connector_for", return_value=_FakeConnector(extracted)):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": [url]})
    assert resp.status_code == 201, resp.text
    (row,) = resp.json()["results"]
    assert row["status"] == "created", row
    return row["document_id"]


def _listed(client, doc_id: str) -> dict:
    resp = client.get("/api/v1/library/videos", params={"document_id": doc_id})
    assert resp.status_code == 200, resp.text
    (row,) = resp.json()
    return row


def test_a_pdf_upload_stores_and_lists_its_language_mix(client, db, upload_dir, ephemeral_chroma):
    doc_id = _upload_pdf(client, HINGLISH)

    db.expire_all()
    stored = json.loads(db.get(Document, doc_id).language_mix)
    assert stored == code_mixing_service.profile_transcript(
        [{"text": s, "start": float(i), "duration": 0.0} for i, s in enumerate(HINGLISH)]
    )
    assert stored["primary_language"] == "hi" and stored["native_script"] == "Latin"

    # The chunks were built from the same profile.
    chunks = ephemeral_chroma.get_document_chunks(doc_id)
    assert chunks and all(c["metadata"]["code_mix_primary"] == "hi" for c in chunks)
    assert all(c["metadata"]["code_mix_script"] == "Latin" for c in chunks)

    row = _listed(client, doc_id)
    assert row["transcript_language"] == "en"  # the extractor's label
    assert row["language_mix"] == {
        "primary_language": "hi",
        "native_script": "Latin",
        "hi_share": stored["hi_share"],
        "named_share": stored["named_share"],
        "matrix_hi_share": stored["matrix_hi_share"],
        "quote_mode": stored["quote_mode"],
        "code_mixed": True,
    }


def test_a_pasted_english_page_is_profiled_as_plain_english(client, db, ephemeral_chroma):
    doc_id = _paste(client, ENGLISH)

    row = _listed(client, doc_id)
    mix = row["language_mix"]
    assert mix["primary_language"] == "en"
    assert mix["hi_share"] == 0.0
    assert mix["code_mixed"] is False
    # English chunks carry no code_mix_* fields, as before.
    chunks = ephemeral_chroma.get_document_chunks(doc_id)
    assert chunks and not any(k.startswith("code_mix") for c in chunks for k in c["metadata"])


def test_mutation_without_the_wiring_the_upload_leaves_no_profile(
    client, db, upload_dir, ephemeral_chroma, monkeypatch
):
    """Mutation check: the pre-T-1.16.1.7 router (no profile stored). The
    chunks still carry the mix, the listing shows none — what the first
    test catches."""
    from app.routers import library

    monkeypatch.setattr(library.language_mix_service, "ensure", lambda doc, segments: None)
    doc_id = _upload_pdf(client, HINGLISH)

    assert _listed(client, doc_id)["language_mix"] is None
    chunks = ephemeral_chroma.get_document_chunks(doc_id)
    assert chunks and all(c["metadata"]["code_mix_primary"] == "hi" for c in chunks)


@pytest.fixture
def seeded(db, test_user):
    """Two YouTube documents the test user ingested through one job."""
    from app.models.job import Job
    from app.models.job_video import JobVideo
    from app.services import visibility_service

    docs = [
        Document(video_id=f"mix{i:03d}abcXY", title=f"Seeded {i}",
                 url=f"https://www.youtube.com/watch?v=mix{i:03d}abcXY",
                 transcript_status="fetched", transcript_language="en")
        for i in range(2)
    ]
    job = Job(tenant_id=test_user.id, job_type="topic", topic="Seeded", status="completed")
    db.add_all([*docs, job])
    db.flush()
    db.add_all([
        JobVideo(job_id=job.id, video_id=d.video_id, document_id=d.document_id, approved=True)
        for d in docs
    ])
    db.commit()
    visibility_service.grant(db, [d.document_id for d in docs], test_user.id)
    db.commit()
    return {"docs": docs, "job": job}


def test_job_and_library_listings_expose_the_stored_profile(client, db, seeded):
    profiled, unprofiled = seeded["docs"]
    profile = code_mixing_service.profile_transcript([{"text": " ".join(HINGLISH)}])
    profiled.language_mix = json.dumps(profile)
    db.commit()

    rows = {r["id"]: r for r in client.get("/api/v1/library/videos").json()}
    assert rows[profiled.document_id]["language_mix"]["primary_language"] == "hi"
    assert rows[profiled.document_id]["language_mix"]["code_mixed"] is True
    assert rows[unprofiled.document_id]["language_mix"] is None

    resp = client.get(f"/api/v1/jobs/{seeded['job'].id}/videos")
    assert resp.status_code == 200, resp.text
    by_id = {r["document_id"]: r for r in resp.json()}
    assert by_id[profiled.document_id]["language_mix"]["native_script"] == "Latin"
    assert by_id[unprofiled.document_id]["language_mix"] is None


def test_an_unreadable_stored_profile_lists_as_none(client, db, seeded):
    doc = seeded["docs"][0]
    doc.language_mix = "{not json"
    db.commit()

    rows = {r["id"]: r for r in client.get("/api/v1/library/videos").json()}
    assert rows[doc.document_id]["language_mix"] is None


# --- what `code_mixed` means ------------------------------------------------


def test_code_mixed_is_documented_as_a_property_of_the_text(client):
    """The served API contract says what the flag is: the chunker's rule
    applied to the measured words, not a fact about the stored chunks, which
    may predate S-1.16.2 and carry no ``code_mix_*`` for a document profiled
    since (the backfill, or a job that reused its chunks)."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    field = resp.json()["components"]["schemas"]["LanguageMixView"]["properties"]["code_mixed"]
    description = field.get("description") or ""
    assert "measured text" in description
    assert "not of its stored chunks" in description
    assert "S-1.16.2" in description and "re-chunked" in description


def test_code_mixed_follows_the_profile_even_when_the_chunks_predate_it(
    client, db, seeded, ephemeral_chroma
):
    """A document chunked before S-1.16.2 (its chunks carry no ``code_mix_*``)
    and profiled by the backfill since lists as code-mixed: the flag reads
    the stored profile, as documented, and is not evidence about the chunks."""
    from app.utils.chunking import chunk_transcript

    doc = seeded["docs"][0]
    segments = [{"text": s, "start": float(i), "duration": 1.0} for i, s in enumerate(HINGLISH)]
    chunks = chunk_transcript(
        segments, chunk_size=40, chunk_overlap=8,
        video_metadata={"video_id": doc.video_id, "document_id": doc.document_id},
    )
    for chunk in chunks:
        for key in [k for k in chunk["metadata"] if k.startswith("code_mix_")]:
            chunk["metadata"].pop(key)
    ephemeral_chroma.insert_chunks(chunks)
    doc.language_mix = json.dumps(code_mixing_service.profile_transcript(segments))
    db.commit()

    rows = {r["id"]: r for r in client.get("/api/v1/library/videos").json()}
    assert rows[doc.document_id]["language_mix"]["code_mixed"] is True
    stored = ephemeral_chroma.get_document_chunks(doc.document_id, doc.video_id)
    assert stored and not any(
        k.startswith("code_mix_") for c in stored for k in (c.get("metadata") or {})
    )

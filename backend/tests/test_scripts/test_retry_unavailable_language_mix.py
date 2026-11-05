"""T-1.16.1.7 at scripts/retry_unavailable_transcripts.py, run through its ``main``.

The retry script is one of the chunking paths that must store the language
profile on ``documents.language_mix`` and hand the same profile to the
chunker. Only the connector and the Chroma insert are faked; the session is
the test database, the chunker and the profiler run for real.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import code_mixing_service, language_mix_service
from app.sources.types import DEFAULT_AUDIO_LANGUAGE, ExtractedText

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import retry_unavailable_transcripts as retry  # noqa: E402

VIDEO_ID = "retryHI0001"
HINDI = [
    "आज हम मशीन लर्निंग के बारे में बात करेंगे और समझेंगे कि यह कैसे काम करता है।",
    "डीप लर्निंग इसका एक हिस्सा है जिसमें न्यूरल नेटवर्क का इस्तेमाल होता है।",
    "अगर आप ध्यान से देखेंगे तो हर उदाहरण में डेटा सबसे ज़रूरी चीज़ है।",
    "इसलिए पहले डेटा को साफ़ करना और समझना बहुत ज़रूरी होता है।",
]
SEGMENTS = [{"text": s, "start": float(i * 5), "duration": 5.0} for i, s in enumerate(HINDI)]


class _FakeConnector:
    def fetch_text(self, candidate, **_kw):
        return ExtractedText(
            segments=[dict(s) for s in SEGMENTS],
            language="hi",
            text_source="whisper",
            word_count=sum(len(s.split()) for s in HINDI),
        )


@pytest.fixture
def unavailable(db, monkeypatch):
    from tests import conftest as _conftest

    doc = Document(video_id=VIDEO_ID, source_id=VIDEO_ID, title="Hindi lecture",
                   url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
                   transcript_status="unavailable")
    job = Job(tenant_id="tenant-retry", job_type="topic", topic="ML in Hindi", status="completed")
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=VIDEO_ID, document_id=doc.document_id, approved=True))
    db.commit()

    monkeypatch.setattr(retry, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(retry, "connector_for", lambda source_type: _FakeConnector())
    chroma = MagicMock()
    chroma.insert_chunks = MagicMock(return_value=1)
    monkeypatch.setattr(retry, "chroma_service", chroma)

    handed: list[dict] = []
    real_chunk = retry.chunk_transcript

    def spy(segments, **kwargs):
        handed.append(kwargs)
        return real_chunk(segments, **kwargs)

    monkeypatch.setattr(retry, "chunk_transcript", spy)
    return {"job": job, "document_id": doc.document_id, "chroma": chroma, "handed": handed}


def _doc(db, document_id: str) -> Document:
    db.expire_all()
    return db.get(Document, document_id)


def test_the_retry_script_stores_the_profile_its_chunks_are_built_from(db, unavailable):
    assert retry.main(["--job", unavailable["job"].id]) == 0

    doc = _doc(db, unavailable["document_id"])
    assert doc.transcript_status == "fetched"
    # Committed with the document (read back through a fresh session state).
    stored = language_mix_service.load(doc)
    assert stored == code_mixing_service.profile_transcript(SEGMENTS)
    assert (stored["primary_language"], stored["native_script"]) == ("hi", "Devanagari")

    # The chunker was handed that profile instead of profiling again...
    assert [k.get("language_profile") for k in unavailable["handed"]] == [stored]
    # ...and the chunks sent to Chroma carry the fields it yields.
    expected = code_mixing_service.chunk_metadata_from_profile(stored)
    assert expected
    chunks = unavailable["chroma"].insert_chunks.call_args[0][0]
    assert chunks and all(
        {k: c["metadata"].get(k) for k in expected} == expected for c in chunks
    )


def test_mutation_without_the_wiring_the_retry_leaves_no_profile(db, unavailable, monkeypatch):
    """Mutation check: the call gone (``ensure`` returns None and stores
    nothing) and the document stays unprofiled while its chunks still carry
    ``code_mix_*``, which the test above catches."""
    monkeypatch.setattr(language_mix_service, "ensure", lambda document, segments: None)

    assert retry.main(["--job", unavailable["job"].id]) == 0

    doc = _doc(db, unavailable["document_id"])
    assert doc.transcript_status == "fetched" and doc.language_mix is None
    assert [k.get("language_profile") for k in unavailable["handed"]] == [None]
    chunks = unavailable["chroma"].insert_chunks.call_args[0][0]
    assert all(c["metadata"].get("code_mix_primary") == "hi" for c in chunks)


def test_the_retry_hands_the_connector_what_the_document_knows(db, unavailable, monkeypatch):
    """T-1.11.11.4: a recovered document does not pay for the lookup either."""
    doc = _doc(db, unavailable["document_id"])
    doc.source_metadata_json = json.dumps({DEFAULT_AUDIO_LANGUAGE: "hi"})
    db.commit()

    seen = []

    class _Recording(_FakeConnector):
        def fetch_text(self, candidate, **kw):
            seen.append(candidate.extra)
            return super().fetch_text(candidate, **kw)

    monkeypatch.setattr(retry, "connector_for", lambda source_type: _Recording())

    assert retry.main(["--job", unavailable["job"].id]) == 0
    assert seen == [{DEFAULT_AUDIO_LANGUAGE: "hi"}]

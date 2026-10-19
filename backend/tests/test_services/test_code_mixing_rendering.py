"""English renderings for retrieval — N-002 / T-1.16.2.5 part B (D-084).

A non-English chunk is embedded as its English rendering while its stored
text stays the original. Rendering is OFF for the suite (conftest) so no test
can reach a provider; these tests opt in with a stubbed model.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.services import chroma_service
from app.services import code_mixing_service as cm
from app.utils.chunking import chunk_transcript

HINDI = [
    {"text": "तो आज हम बात करेंगे मशीन लर्निंग के बारे में और देखेंगे कि यह कैसे काम करती है", "start": 0.0, "duration": 6.0},
    {"text": "मशीन को डाटा दिया जाता है और वह खुद से सीखती है कि आगे क्या करना है", "start": 6.0, "duration": 6.0},
]
HINDI_ENGLISH = (
    "So today we will talk about machine learning and see how it works. "
    "The machine is given data and learns by itself what to do next."
)


@pytest.fixture
def rendering_on(monkeypatch):
    monkeypatch.setattr(settings, "CODE_MIX_ENGLISH_RENDERING_ENABLED", True)


def _llm_returning(*payloads):
    llm = MagicMock()
    responses = []
    for p in payloads:
        if isinstance(p, Exception):
            responses.append(p)
        else:
            r = MagicMock()
            r.content = json.dumps(p)
            responses.append(r)
    llm.invoke.side_effect = responses
    return llm


def _chunks(segments, vid="hi1"):
    return chunk_transcript(segments, video_metadata={
        "video_id": vid, "document_id": f"doc-{vid}", "title": "t", "channel_name": "c",
    })


# --- which chunks ------------------------------------------------------------------
def test_only_non_english_chunks_need_a_rendering():
    assert cm.needs_english_rendering({"code_mix_primary": "hi", "code_mix_chunk_share": 0.9})
    # A Hindi-grammar passage needs one even when most of its words are English.
    assert cm.needs_english_rendering(
        {"code_mix_primary": "en", "code_mix_chunk_share": 0.1, "code_mix_chunk_matrix": "hi"})
    # An English passage inside a Hindi talk embeds fine as written.
    assert not cm.needs_english_rendering(
        {"code_mix_primary": "hi", "code_mix_chunk_share": 0.05, "code_mix_chunk_matrix": "en"})
    # English sources carry no code_mix fields at all; done chunks are skipped.
    assert not cm.needs_english_rendering({"video_id": "x"})
    assert not cm.needs_english_rendering({"code_mix_primary": "hi", "code_mix_chunk_share": 1.0, "text_en": "x"})


def test_render_payload_parsing():
    out = cm.parse_render_payload('```json\n{"chunks": [{"i": 1, "english": "b"}]}\n```', 2)
    assert out == [None, "b"]
    assert cm.parse_render_payload("nope", 1) is None


# --- rendering ---------------------------------------------------------------------
def test_ensure_is_a_no_op_when_disabled():
    chunks = _chunks(HINDI)
    llm = _llm_returning()
    assert cm.ensure_english_renderings(chunks, llm=llm) == 0
    llm.invoke.assert_not_called()


def test_ensure_renders_only_what_needs_it_and_survives_a_failed_batch(rendering_on, monkeypatch):
    monkeypatch.setattr(cm, "RENDER_BATCH_SIZE", 1)
    hindi = _chunks(HINDI)
    english = _chunks([{"text": "Plain English about context windows.", "start": 0, "duration": 3}], "en1")
    assert not any(k.startswith("code_mix") for k in english[0]["metadata"])
    second = _chunks(HINDI, "hi2")
    llm = _llm_returning({"chunks": [{"i": 0, "english": HINDI_ENGLISH}]}, RuntimeError("down"))
    n = cm.ensure_english_renderings(hindi + english + second, llm=llm)
    assert n == 1
    assert hindi[0]["metadata"]["text_en"] == HINDI_ENGLISH
    assert "text_en" not in english[0]["metadata"]
    assert "text_en" not in second[0]["metadata"]      # its batch failed: embeds as written
    assert llm.invoke.call_count == 2                   # the English chunk was never sent
    prompt = llm.invoke.call_args_list[0].args[0][0].content
    assert HINDI[0]["text"] in prompt and "Translate the WHOLE chunk" in prompt


# --- at the caller: chroma_service.insert_chunks -----------------------------------------
@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def test_insert_embeds_the_rendering_and_stores_the_original(rendering_on, ephemeral_chroma):
    chunks = _chunks(HINDI)
    llm = _llm_returning({"chunks": [{"i": 0, "english": HINDI_ENGLISH}]})
    with patch("app.services.llm_service.get_llm_for", return_value=llm):
        assert chroma_service.insert_chunks(chunks) == 1

    col = chroma_service.get_global_collection()
    got = col.get(include=["documents", "metadatas", "embeddings"])
    # The quoted text is the original; the rendering rides in metadata.
    assert got["documents"][0] == chunks[0]["text"]
    assert got["metadatas"][0]["text_en"] == HINDI_ENGLISH
    # The vector is the rendering's, not the original's.
    ef = chroma_service._get_embedding_function()
    rendered_vec = ef([HINDI_ENGLISH])[0]
    original_vec = ef([chunks[0]["text"]])[0]
    stored = got["embeddings"][0]
    assert sum((a - b) ** 2 for a, b in zip(stored, rendered_vec)) < 1e-6
    assert sum((a - b) ** 2 for a, b in zip(stored, original_vec)) > 1e-3


def test_insert_without_rendering_is_unchanged(ephemeral_chroma):
    chunks = _chunks(HINDI)          # rendering off (suite default)
    chroma_service.insert_chunks(chunks)
    got = chroma_service.get_global_collection().get(include=["documents", "metadatas", "embeddings"])
    assert "text_en" not in got["metadatas"][0]
    ef = chroma_service._get_embedding_function()
    original_vec = ef([chunks[0]["text"]])[0]
    assert sum((a - b) ** 2 for a, b in zip(got["embeddings"][0], original_vec)) < 1e-6


def test_insert_survives_a_renderer_crash(rendering_on, ephemeral_chroma):
    chunks = _chunks(HINDI)
    with patch.object(cm, "ensure_english_renderings", side_effect=RuntimeError("boom")):
        assert chroma_service.insert_chunks(chunks) == 1

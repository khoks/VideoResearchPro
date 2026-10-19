"""N-002 at its callers (T-1.16.2.5): the quotation half of the bidirectional split.

Each test drives a production caller — the chunker, the report map and
compose stages, the job and library Q&A context builders, knowledge
extraction — and asserts on what reaches the model, because a helper that is
correct and never called is how R4's Q&A half shipped unwired.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.agents import knowledge_agent, qa_agent, report_agent
from app.agents.prompts.qa_prompts import LIBRARY_QA_SYSTEM_PROMPT, QA_SYSTEM_PROMPT
from app.agents.prompts.shared import CODE_MIXED_QUOTE_FORMS, CODE_MIXING_NOTE
from app.utils.chunking import chunk_transcript

HINDI_SEGMENTS = [
    {"text": "तो आज हम बात करेंगे मशीन लर्निंग के बारे में और देखेंगे कि यह कैसे काम करती है", "start": 0.0, "duration": 6.0},
    {"text": "मशीन को डाटा दिया जाता है और वह खुद से सीखती है कि आगे क्या करना है", "start": 6.0, "duration": 6.0},
    {"text": "इसको हम एक्सप्लीसिटली प्रोग्राम नहीं करते हैं बल्कि मशीन पैटर्न ढूंढती है", "start": 12.0, "duration": 6.0},
]
ROMANISED_SEGMENTS = [
    {"text": "and this is how we were preparing taaki baadme koi kasar koi zarra na reh jaye", "start": 0.0, "duration": 5.0},
    {"text": "and so we kept on you know adding hum jodte rahe cheezein", "start": 5.0, "duration": 5.0},
]
# The user's own example: English grammar, 46% Hindi words -> Roman quotes.
ENGLISH_SEGMENTS = [
    {"text": "Today we talk about context engineering for coding agents and why it matters.", "start": 0.0, "duration": 5.0},
    {"text": "The window is finite, so every token you add has to earn its place.", "start": 5.0, "duration": 5.0},
]


def _chunks(segments, vid, title):
    return chunk_transcript(segments, video_metadata={
        "video_id": vid, "document_id": f"doc-{vid}", "title": title,
        "channel_name": "Ch", "url": f"https://www.youtube.com/watch?v={vid}",
    })


# --- chunker -------------------------------------------------------------------
def test_chunker_writes_the_profile_onto_non_english_chunks_only():
    hindi = _chunks(HINDI_SEGMENTS, "hi1", "ML in Hindi")[0]["metadata"]
    assert hindi["code_mix_primary"] == "hi"
    assert hindi["code_mix_script"] == "Devanagari"
    assert hindi["code_mix_quote"] == "native_script"
    assert hindi["code_mix_chunk_matrix"] == "hi"

    roman = _chunks(ROMANISED_SEGMENTS, "rm1", "Founder story")[0]["metadata"]
    assert roman["code_mix_script"] == "Latin"
    assert roman["code_mix_share"] > 0.3

    english = _chunks(ENGLISH_SEGMENTS, "en1", "Context engineering")[0]["metadata"]
    assert not any(k.startswith("code_mix") for k in english)


def test_chunker_survives_a_profile_failure():
    with patch("app.services.code_mixing_service.chunk_metadata_for_transcript",
               side_effect=RuntimeError("boom")):
        chunks = _chunks(HINDI_SEGMENTS, "hi1", "ML in Hindi")
    assert chunks and not any(k.startswith("code_mix") for k in chunks[0]["metadata"])


# --- report map ----------------------------------------------------------------
def _map_prompt(chunks) -> str:
    response = MagicMock()
    response.content = '{"facts": [], "comments": [], "conclusions": [], "references": [], "speakers": []}'
    llm = MagicMock()
    llm.invoke.return_value = response
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        report_agent.map_chunks({"job_type": "topic", "transcript_chunks": chunks, "topic": "t"})
    return "\n".join(call.args[0][0].content for call in llm.invoke.call_args_list)


def test_map_prompt_names_each_sources_language_and_quote_form():
    prompt = _map_prompt(
        _chunks(ROMANISED_SEGMENTS, "rm1", "Founder story")
        + _chunks(ENGLISH_SEGMENTS, "en1", "Context engineering")
    )
    # The romanised source is announced as Hindi with its quote form...
    assert "speech: mostly English with Hindi (romanised)" in prompt or "speech: Hindi (romanised)" in prompt
    assert "quote in Roman script + English translation" in prompt
    # ...the English source's header carries no speech note...
    english_header = next(l for l in prompt.splitlines() if l.startswith("[Context engineering"))
    assert "speech:" not in english_header
    # ...and the model is told what the note means and how to keep wording.
    assert "A source header may carry `speech: ...`" in prompt
    assert "`original`" in prompt


# --- report compose ----------------------------------------------------------------
def test_compose_gives_kept_wording_its_sources_quote_form():
    chunks = _chunks(HINDI_SEGMENTS, "hi1", "ML in Hindi") + _chunks(ENGLISH_SEGMENTS, "en1", "Context engineering")
    item = {
        "content": "Machines are not explicitly programmed; they find patterns.",
        "original": "इसको हम एक्सप्लीसिटली प्रोग्राम नहीं करते हैं",
        "video_title": "ML in Hindi", "channel_name": "Ch",
        "video_url": "https://www.youtube.com/watch?v=hi1&t=12",
        "timestamp_display": "0:12", "timestamp_seconds": 12, "speaker": "",
    }
    english_item = {"content": "The window is finite.", "video_title": "Context engineering",
                    "channel_name": "Ch", "video_url": "https://www.youtube.com/watch?v=en1"}
    summaries = [{"facts": [item, english_item], "comments": [], "conclusions": [],
                  "references": [], "speakers": []}]
    prompts: list[str] = []

    def fake_invoke(use_case, prompt, **kw):
        prompts.append(prompt)
        return "<h2>x</h2>"

    with patch.object(report_agent, "_invoke_with_retry", side_effect=fake_invoke):
        report_agent.compose_report({
            "job_type": "topic", "topic": "t", "chunk_summaries": summaries,
            "statistics": {"video_count": 2}, "transcript_chunks": chunks,
        })
    facts_prompt = next(p for p in prompts if "SECTION: Key Facts" in p)
    material = facts_prompt.split("Source material for this section")[1]
    assert '"quote_form": "quote in Devanagari + transliteration + English translation"' in material
    # Only the item that kept wording gets a form; the English item does not.
    assert material.count('"quote_form"') == 1
    assert CODE_MIXED_QUOTE_FORMS in facts_prompt
    assert "CODE-MIXED SOURCES: 1 source(s)" in facts_prompt


# --- Q&A ---------------------------------------------------------------------------
def test_qa_context_header_and_allowed_sources_carry_the_speech_note():
    chunk = _chunks(ROMANISED_SEGMENTS, "rm1", "Founder story")[0]
    header = qa_agent._chunk_header(1, {"metadata": chunk["metadata"], "timestamp_display": "0:00"})
    assert "speech:" in header and "quote in Roman script" in header

    english = _chunks(ENGLISH_SEGMENTS, "en1", "Context engineering")[0]
    assert "speech:" not in qa_agent._chunk_header(2, {"metadata": english["metadata"]})


def test_qa_system_prompts_carry_the_code_mixing_contracts_once():
    assert QA_SYSTEM_PROMPT.count(CODE_MIXED_QUOTE_FORMS) == 1
    assert QA_SYSTEM_PROMPT.count(CODE_MIXING_NOTE) == 1
    # Library Q&A answers in a requested language with its own excerpt rule,
    # so it gets recognition, not the English quote forms.
    assert LIBRARY_QA_SYSTEM_PROMPT.count(CODE_MIXING_NOTE) == 1
    assert CODE_MIXED_QUOTE_FORMS not in LIBRARY_QA_SYSTEM_PROMPT


# --- knowledge extraction ------------------------------------------------------------
def _knowledge_prompts(transcript: str) -> list[str]:
    response = MagicMock()
    response.content = json.dumps({"topics": [], "concepts": [], "events": [], "facts": []})
    llm = MagicMock()
    llm.invoke.return_value = response
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        knowledge_agent.extract_per_batch({
            "transcript_batches": [transcript], "video_title": "v", "channel_name": "c",
            "full_transcript_text": transcript,
        })
    return [call.args[0][0].content for call in llm.invoke.call_args_list]


def test_knowledge_extraction_is_told_the_videos_language_and_quote_form():
    hindi = " ".join(s["text"] for s in HINDI_SEGMENTS)
    (prompt,) = _knowledge_prompts(hindi)
    assert "SOURCE LANGUAGE (measured from this transcript)" in prompt
    assert "quote in Devanagari" in prompt

    english = " ".join(s["text"] for s in ENGLISH_SEGMENTS)
    (prompt,) = _knowledge_prompts(english)
    assert "SOURCE LANGUAGE" not in prompt


# --- found by the held-out evaluation (T-1.16.2.6) -------------------------------------
def test_an_english_primary_source_with_real_hindi_still_carries_the_profile():
    """Comment threads under Hinglish videos are English-primary with 13–17%
    Hindi words. The first cut treated "English-primary, plain-English quote
    mode" as English and wrote nothing, so their Hindi comments never got a
    speech note. A 3% presence floor separates them from English talks
    (0.0–0.6%, all 214 in the library)."""
    thread = [{"text": t, "start": float(i), "duration": 1.0} for i, t in enumerate([
        "Great video sir, very helpful for beginners like me",
        "Sir ye aapne bahut ache se samjhaya hai, mujhe sab samajh aa gaya",
        "Please make a video on mutual funds and SIP",
        "Thanks for the clear explanation of emergency funds",
        "Can you explain term insurance next time",
        "Very informative, keep it up",
    ])]
    meta = _chunks(thread, "th1", "Comments")[0]["metadata"]
    assert meta["code_mix_primary"] == "en"
    assert 0.03 <= meta["code_mix_share"] < 0.5
    # Its Hindi comments are quoted in the Roman script they were typed in.
    from app.services import code_mixing_service

    assert code_mixing_service.quote_form(meta).startswith("quote in Roman script")


def test_compose_lets_an_english_original_stay_english_in_a_hindi_source():
    """The source decides the script; the span still decides whether it is
    English. The held-out run quoted an English sentence from a Hindi talk in
    full three-part form before this."""
    chunks = _chunks(HINDI_SEGMENTS, "hi1", "ML in Hindi")
    hindi = {"content": "Machines find patterns.", "original": "मशीन पैटर्न ढूंढती है और खुद से सीखती है",
             "video_title": "ML in Hindi", "video_url": "https://www.youtube.com/watch?v=hi1"}
    english = {"content": "We are not entrepreneurs.", "original": "We are not entrepreneurs bhai, we need a salary",
               "video_title": "ML in Hindi", "video_url": "https://www.youtube.com/watch?v=hi1"}
    consolidated = {"facts": [hindi, english]}
    metas = [c["metadata"] for c in chunks]
    assert report_agent._attach_quote_forms(consolidated, report_agent._quote_forms_by_source(metas)) == 2
    assert hindi["quote_form"].startswith("quote in Devanagari")
    assert english["quote_form"].startswith("plain English")

"""The knowledge prompts name the source by its type, and keep every contract.

Before non-video documents could be extracted, both prompts said "YouTube
video" and "transcript" whatever the source. A PDF now reads as a PDF; a
video's prompts are unchanged; and the rules that are not about the medium —
English output, the quote forms, the publish-date anchoring, the measured
language note — reach every source type's prompt.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents import knowledge_agent
from app.agents.prompts import knowledge_prompts as kp

_EMPTY = json.dumps({"topics": [], "concepts": [], "events": [], "facts": []})

# A Hindi passage, so the measured language note has something to say.
_HINDI = (
    "भारत की नदियों में गंगा सबसे पवित्र मानी जाती है। "
    "हर साल लाखों लोग इसके किनारे स्नान करने आते हैं। "
    "सरकार ने नदी को साफ करने के लिए कई योजनाएं शुरू की हैं।"
)


def _llm(content: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=content)
    return llm


def _prompts(document, text: str) -> tuple[str, str]:
    extract, synth = _llm(json.dumps({"topics": ["x"], "concepts": [], "events": [], "facts": []})), _llm("# R")
    with patch.object(knowledge_agent, "get_llm_for", side_effect=[extract, synth]):
        knowledge_agent.run_knowledge_extract_agent(document, text)
    return (
        extract.invoke.call_args.args[0][0].content,
        synth.invoke.call_args.args[0][0].content,
    )


def _doc(source_type: str | None, **kw):
    base = dict(video_id=None, document_id="doc-1", title="The Ganges", channel_name="",
                published_at=None, discussed_era_json=None, source_metadata_json=None)
    if source_type is not None:
        base["source_type"] = source_type
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_pdf_reads_as_a_pdf_in_both_prompts():
    extract, synth = _prompts(_doc("pdf"), "The river is long. It floods every year.")
    assert "one batch of the text of a PDF document" in extract
    assert 'Document: "The Ganges"' in extract
    assert "Text batch:" in extract
    assert "the author clearly speculates" in extract
    assert "knowledge report for a single PDF document" in synth
    assert "Text excerpt (opening portion only" in synth
    assert 'No "In this document..."' in synth
    for prompt in (extract, synth):
        assert "YouTube" not in prompt
        assert "Channel:" not in prompt, "a PDF has no channel and no 'Unknown' line either"


def test_a_video_reads_as_before():
    video = _doc("video", video_id="vid1", channel_name="River Talks")
    extract, synth = _prompts(video, "The river is long.")
    assert "one batch of a YouTube video transcript" in extract
    assert 'Video: "The Ganges"\nChannel: River Talks' in extract
    assert "Transcript batch:" in extract
    assert "the speaker clearly speculates" in extract
    assert "knowledge report for a single YouTube video" in synth
    assert 'No "In this video..."' in synth


def test_a_document_without_a_source_type_is_a_video():
    """SimpleNamespace callers and rows from before L1 carry no source_type."""
    extract, _ = _prompts(_doc(None, channel_name=""), "Text.")
    assert "a YouTube video transcript" in extract
    assert "Channel: Unknown" in extract


def test_a_pasted_page_names_its_author_from_the_extractor():
    page = _doc("article", source_metadata_json=json.dumps({"author": "A. Writer", "extractor": "trafilatura"}))
    extract, synth = _prompts(page, "An essay paragraph.")
    assert 'Article: "The Ganges"\nAuthor: A. Writer' in extract
    assert "Author: A. Writer" in synth


def test_a_thread_is_a_thread():
    extract, _ = _prompts(_doc("reddit_post"), "OP text. A reply.")
    assert "a Reddit thread (the post and its comments)" in extract
    assert "the author or a commenter clearly speculates" in extract


def test_an_unknown_source_type_still_reads_correctly():
    extract, _ = _prompts(_doc("carrier_pigeon"), "A note.")
    assert "the text of a document" in extract
    assert "YouTube" not in extract


@pytest.mark.parametrize("source_type", ["video", *sorted(set(kp.SOURCE_PROFILES) - {"video"})])
def test_every_source_type_keeps_the_shared_contracts(source_type):
    """English output, the three quote forms, the date anchoring and the
    measured language note are not about the medium: every type gets them."""
    doc = _doc(source_type, published_at=None)
    extract, synth = _prompts(doc, _HINDI)
    assert "OUTPUT LANGUAGE IS ENGLISH" in extract
    assert "THE REPORT IS WRITTEN IN ENGLISH" in synth
    assert "romanised transliteration, then an English translation" in extract
    assert "original script, transliteration, then English translation" in synth
    for prompt in (extract, synth):
        assert "Published: unknown — keep relative time expressions verbatim" in prompt
        assert "SOURCE LANGUAGE (measured from this transcript)" in prompt
    assert "TIME: anchor relative time expressions" in extract
    assert "DATE YOUR CLAIMS" in synth
    assert "ON-SCREEN VISUAL ANNOTATIONS" in extract


def test_every_profile_fills_both_prompts():
    for source_type, profile in kp.SOURCE_PROFILES.items():
        header = kp.source_header(profile, "T", "")
        kp.EXTRACT_BATCH_PROMPT.format(
            source_subject=profile.subject, source_header=header, source_voice=profile.voice,
            text_label=profile.text_label, temporal_note="", language_note="",
            batch_text="b", visual_annotations="",
        )
        kp.SYNTHESIZE_REPORT_PROMPT.format(
            source_noun=profile.noun, source_short=profile.short, source_header=header,
            text_label=profile.text_label, temporal_note="", language_note="",
            merged_extraction_json="{}", full_transcript_text="t",
        )
        assert profile.subject and profile.noun and profile.short, source_type

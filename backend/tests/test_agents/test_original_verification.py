"""Kept `original` wording must trace back to the source's own speech (N-002 fix).

The R1 run-5 replay (2026-10-19) packed a Bengali and two Hindi sources into
one map batch; the model wrote `original` values for a Hindi speaker in
BENGALI script — strings in no transcript — spliced Bengali letters into
Devanagari words, and the composer quoted him in Bengali seven times. These
tests drive the production map and compose stages with a stubbed model and
assert that such wording never survives, using the same rule as the run-6
gate (`scripts/audit_quote_fidelity.py`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents import report_agent
from app.config import settings
from app.services import quote_fidelity as qf
from app.utils.chunking import chunk_transcript


@pytest.fixture(autouse=True)
def _packed_batching(monkeypatch):
    # These stubs answer each map call with one payload naming SEVERAL
    # sources (the run-5 shape). The production default since D-090 maps one
    # source per call, which would hand that payload to every source's call.
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "packed")
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 120_000)

HINDI = [
    {"text": "बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों प्लॉट हमारे लिए सिमिलर टाइप हैं", "start": 0.0, "duration": 6.0},
    {"text": "इसको हम ज़्यादा यूज़ करेंगे जब डेटा में १४९ रोज़ होंगी", "start": 6.0, "duration": 6.0},
    {"text": "लिमिटेशंस ऑफ मैटप्लॉटलिब के बारे में जानेंगे और फिर सीबॉर्न पर आएंगे", "start": 12.0, "duration": 6.0},
]
BENGALI = [
    {"text": "আজকে আমরা পাইথনে সিবর্ন লাইব্রেরি নিয়ে কথা বলব এবং দেখব কীভাবে প্লট করতে হয়", "start": 0.0, "duration": 6.0},
    {"text": "প্রথমে আমরা ডেটাসেট লোড করব তারপর ২৫টি সারি দেখব", "start": 6.0, "duration": 6.0},
]
HI_URL = "https://www.youtube.com/watch?v=hi1hi1hi1hi"
BN_URL = "https://www.youtube.com/watch?v=bn1bn1bn1bn"


def _chunks():
    hi = chunk_transcript(HINDI, video_metadata={
        "video_id": "hi1hi1hi1hi", "document_id": "doc-hi1", "title": "Seaborn in Hindi",
        "channel_name": "DeepLoop Circle", "url": HI_URL,
    })
    bn = chunk_transcript(BENGALI, video_metadata={
        "video_id": "bn1bn1bn1bn", "document_id": "doc-bn1", "title": "Seaborn in Bengali",
        "channel_name": "CodeWithMunnaX", "url": BN_URL,
    })
    return hi + bn


def _item(original, url=HI_URL, title="Seaborn in Hindi", content="A point in English."):
    return {"content": content, "original": original, "video_title": title,
            "channel_name": "x", "video_url": url, "timestamp_seconds": 0, "speaker": ""}


def _run_map(items):
    response = MagicMock()
    response.content = json.dumps({"facts": items, "comments": [], "conclusions": [],
                                   "references": [], "speakers": []}, ensure_ascii=False)
    llm = MagicMock()
    llm.invoke.return_value = response
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        return report_agent.map_chunks({"job_type": "topic", "transcript_chunks": _chunks(), "topic": "t"})


# --- the shared rule --------------------------------------------------------------------
def test_normalisation_folds_spellings_not_scripts():
    n = qf.normalise
    assert n("ज़्यादा") == n("ज़्यादा") == n("ज्यादा")          # nukta, either encoding
    assert n("১৪৯ রোজ") == n("149 রোজ") and n("१४९") == "149"   # native digits
    assert n("है। तो") == n("है तो") and n("Hello, World!") == n("hello world")
    assert n("প্লট") != n("प्लॉट")                                # scripts never fold


def test_problem_reasons():
    hindi = qf.VideoText.from_raw("h", " ".join(s["text"] for s in HINDI))
    assert qf.problem("बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों", hindi) is None
    # Elided with an ellipsis: each fragment is checked on its own.
    assert qf.problem("बॉक्स प्लॉट और वायलिन प्लॉट … सिमिलर टाइप हैं", hindi) is None
    assert qf.problem("বক্স প্লট এবং ভায়োলিন প্লট এই দুটো প্লট", hindi) == "script_mismatch"
    assert qf.problem("लिमিটेशंस ऑफ मैटप्लॉटलिब के बारे में", hindi) == "mixed_script"
    assert qf.problem("बॉक्स प्लॉट और वायलिन प्लॉट कभी यूज़ नहीं करने चाहिए क्योंकि गलत हैं", hindi) == "not_in_speech"
    assert qf.problem("कोई भी बात", None) == "no_source"


def test_merged_chunks_match_a_quote_across_a_boundary():
    merged = qf.merge_chunk_texts(["one two three four five", "four five six seven", "six seven eight"])
    assert merged == "one two three four five six seven eight"
    assert qf.problem("three four five six", qf.VideoText.from_raw("t", merged)) is None


# --- at the caller: the map stage ----------------------------------------------------------
def test_map_drops_every_failing_original_and_keeps_true_and_near_ones():
    true_hindi = "इसको हम ज़्यादा यूज़ करेंगे जब डेटा में 149 रोज होंगी"   # nukta and digit variants
    near_hindi = "बॉक्स प्लॉट और वायलन प्लॉट ये दोनों प्लॉट हमारे लिये सिमिलर टाइप हैं"  # spelling regularised
    true_bengali = "প্রথমে আমরা ডেটাসেট লোড করব"
    items = [
        _item("বক্স প্লট এবং ভায়োলিন প্লট এই দুটো প্লট"),                       # Hindi speaker in Bengali
        _item("लिमিটेशंस ऑफ मैटप्लॉटलिब के बारे में জানेंगे"),                    # Bengali letters spliced in
        _item("बॉक्स प्लॉट और वायलिन प्लॉट कभी यूज़ नहीं करने चाहिए क्योंकि गलत हैं"),  # invented
        _item("बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों", url=BN_URL, title="Seaborn in Bengali"),  # other video
        _item("बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों", url="https://www.youtube.com/watch?v=zzzzzzzzzzz",
              title="Not in this job"),                                                  # unresolvable
        _item(true_hindi),
        _item(near_hindi),
        _item(true_bengali, url=BN_URL, title="Seaborn in Bengali"),
        {"content": "No original at all.", "video_url": HI_URL, "video_title": "Seaborn in Hindi"},
    ]
    out = _run_map(items)
    facts = out["chunk_summaries"][0]["facts"]
    assert [f.get("original") for f in facts if f.get("original")] == [true_hindi, near_hindi, true_bengali]
    reasons = [f["original_rejected_reason"] for f in facts if f.get("original_rejected")]
    assert reasons == ["script_mismatch", "mixed_script", "not_in_speech", "script_mismatch", "no_source"]
    # The English point survives every drop.
    assert len(facts) == 9 and all(f["content"] for f in facts)
    notes = out["processing_notes"]
    assert notes["map_originals_kept"] == 3 and notes["map_originals_dropped"] == 5
    assert notes["map_originals_dropped_by_reason"] == {
        "mixed_script": 1, "no_source": 1, "not_in_speech": 1, "script_mismatch": 2,
    }
    # The audit record shows what was removed and why.
    record = json.loads(out["map_batch_records"][0]["payload_json"])
    assert sum(1 for f in record["facts"] if "original_rejected" in f) == 5


def test_what_the_pipeline_keeps_the_run6_gate_passes():
    """Same rule, same answer: no original the map stage keeps is one the
    audit would fail against the same transcript."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import audit_quote_fidelity as aq

    out = _run_map([
        _item("बॉक्स प्लॉट और वायलन प्लॉट ये दोनों प्लॉट हमारे लिये सिमिलर टाइप हैं"),
        _item("বক্স প্লট এবং ভায়োলিন প্লট এই দুটো প্লট"),
        _item("প্রথমে আমরা ডেটাসেট লোড করব", url=BN_URL, title="Seaborn in Bengali"),
    ])
    transcript = "\n".join(
        [f"=== Seaborn in Hindi ({HI_URL}) ==="] + [s["text"] for s in HINDI]
        + [f"=== Seaborn in Bengali ({BN_URL}) ==="] + [s["text"] for s in BENGALI]
    )
    corpus = aq.parse_transcript(transcript)
    findings = aq.audit_items({"map": out["map_batch_records"]}, corpus)
    assert len(findings) == 2 and not any(aq.fails(f) for f in findings)


def test_a_quote_spanning_two_chunks_survives(monkeypatch):
    long_hindi = [
        {"text": f"वाक्य नंबर {i} में हम प्लॉट के बारे में बात करते हैं और आगे बढ़ते हैं", "start": float(i), "duration": 1.0}
        for i in range(40)
    ]
    chunks = chunk_transcript(long_hindi, chunk_size=128, chunk_overlap=32, video_metadata={
        "video_id": "hi2hi2hi2hi", "document_id": "doc-hi2", "title": "Long", "channel_name": "c", "url": HI_URL,
    })
    assert len(chunks) >= 3
    texts = report_agent._source_texts_for_verification(chunks)
    merged = qf.merge_chunk_texts(c["text"] for c in chunks)
    start = len(chunks[0]["text"].split()) - 5
    quote = " ".join(merged.split()[start:start + 12])
    assert quote not in chunks[0]["text"] and quote not in chunks[1]["text"]
    assert qf.problem(quote, texts["videos"]["doc-hi2"]) is None


# --- at the caller: compose ----------------------------------------------------------------
def test_compose_never_sees_a_rejected_original_and_discloses_the_drop():
    out = _run_map([
        _item("বক্স প্লট এবং ভায়োলিন প্লট এই দুটো প্লট", content="Box and violin plots are similar."),
        _item(HINDI[1]["text"], content="It is used more when the data has 149 rows."),
    ])
    prompts: list[str] = []

    def fake_invoke(use_case, prompt, **kw):
        prompts.append(prompt)
        return "<h2>x</h2>"

    with patch.object(report_agent, "_invoke_with_retry", side_effect=fake_invoke):
        html = report_agent.compose_report({
            "job_type": "topic", "topic": "t", "chunk_summaries": out["chunk_summaries"],
            "statistics": {"video_count": 2}, "transcript_chunks": _chunks(),
            "processing_notes": out["processing_notes"],
        })["final_html"]
    assert prompts and all("বক্স" not in p and "original_rejected" not in p for p in prompts)
    # The kept original reaches the composer as readable text, not JSON escapes.
    assert any(HINDI[1]["text"] in p for p in prompts)
    assert not any(chr(92) + "u0907" in p for p in prompts)   # a JSON-escaped "इ"
    assert "1 quoted passage(s)" in html and "not found word for word" in html


# --- R1 run 7: speech + transliteration + translation in one `original` ----------------
# Real caption lines of the Bengali source (CodeWithMunnaX, job 419e691d) —
# including the caption's own "( Seaborn)".
MUNNA = [
    {"text": t, "start": float(i), "duration": 1.0}
    for i, t in enumerate([
        "আজ আমি সি-বর্ন (", "Seaborn) ব্যাখ্যা", "করতে যাচ্ছি।", "সি-বর্ন কী?",
        "সবার আগে এই", "বিষয়টি বোঝো।", "এরপর আমরা", "এটিকে ইনস্টল", "করব। তারপর এর",
        "মাধ্যমে আমরা", "গ্রাফ তৈরি করব", "। ঠিক আছে?",
    ])
]
MUNNA_URL = "https://www.youtube.com/watch?v=5AuuOZ4vuxI"
# Verbatim from run 7's map output (original_rejected, reason not_in_speech).
RUN7_ORIGINAL = (
    "আজ আমি সি-বর্ন ( Seaborn) ব্যাখ্যা করতে যাচ্ছি। সি-বর্ন কী?\n"
    "Āj āmi si-born (Seaborn) byākhyā korte yācchi. Si-born kī?\n"
    "Today I am going to explain Seaborn. What is Seaborn?"
)


def _munna_map(items):
    chunks = chunk_transcript(MUNNA, video_metadata={
        "video_id": "5AuuOZ4vuxI", "document_id": "doc-munna", "title": "Seaborn in Python",
        "channel_name": "CodeWithMunnaX", "url": MUNNA_URL,
    })
    response = MagicMock()
    response.content = json.dumps({"facts": items, "comments": [], "conclusions": [],
                                   "references": [], "speakers": []}, ensure_ascii=False)
    llm = MagicMock()
    llm.invoke.return_value = response
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        return report_agent.map_chunks({"job_type": "topic", "transcript_chunks": chunks, "topic": "t"})


def test_the_speech_line_of_an_overfull_original_is_kept():
    source = qf.VideoText.from_raw("m", " ".join(s["text"] for s in MUNNA))
    assert qf.problem(RUN7_ORIGINAL, source) == "not_in_speech"        # what run 7 did
    out = _munna_map([_item(RUN7_ORIGINAL, url=MUNNA_URL, title="Seaborn in Python")])
    (fact,) = out["chunk_summaries"][0]["facts"]
    assert fact["original"] == "আজ আমি সি-বর্ন ( Seaborn) ব্যাখ্যা করতে যাচ্ছি। সি-বর্ন কী?"
    assert fact["original_stripped"].startswith("Āj āmi si-born")
    assert "Today I am going to explain Seaborn" in fact["original_stripped"]
    notes = out["processing_notes"]
    assert (notes["map_originals_kept"], notes["map_originals_dropped"], notes["map_originals_trimmed"]) == (1, 0, 1)


def test_a_gloss_the_speaker_never_said_is_stripped_too():
    original = "এরপর আমরা এটিকে ইনস্টল (install it) করব। তারপর এর মাধ্যমে আমরা গ্রাফ তৈরি করব\nEbar āmrā..."
    out = _munna_map([_item(original, url=MUNNA_URL, title="Seaborn in Python")])
    (fact,) = out["chunk_summaries"][0]["facts"]
    assert fact["original"] == "এরপর আমরা এটিকে ইনস্টল করব। তারপর এর মাধ্যমে আমরা গ্রাফ তৈরি করব"
    assert "(install it)" in fact["original_stripped"]


def test_stripping_never_rescues_invented_speech():
    invented = "সি-বর্ন দিয়ে আমরা মেশিন লার্নিং মডেল ট্রেন করব এবং ডিপ্লয় করব\nSi-born diye āmrā..."
    out = _munna_map([_item(invented, url=MUNNA_URL, title="Seaborn in Python")])
    (fact,) = out["chunk_summaries"][0]["facts"]
    assert "original" not in fact and fact["original_rejected_reason"] == "not_in_speech"
    assert out["processing_notes"]["map_originals_trimmed"] == 0


def test_compose_never_sees_the_stripped_remainder():
    out = _munna_map([_item(RUN7_ORIGINAL, url=MUNNA_URL, title="Seaborn in Python")])
    rendered = report_agent._render_items_for_compose(out["chunk_summaries"][0]["facts"], tagged=False)
    assert "original_stripped" not in rendered[0] and rendered[0]["original"].startswith("আজ আমি")


def test_romanised_sources_are_not_split_by_line():
    # No native script: a transliteration line cannot be told from speech.
    roman = qf.VideoText.from_raw("r", "mujhe nahi pata ki ye kaise kaam karta hai")
    assert roman.script is None
    two_lines = "mujhe nahi pata ki ye kaise kaam karta hai" + chr(10) + "I do not know how this works"
    assert qf.keepable(two_lines, roman) == (None, "", "not_in_speech")
    assert qf.keepable("mujhe nahi pata ki ye kaise", roman) == ("mujhe nahi pata ki ye kaise", "", None)


def test_a_kept_original_loses_only_glosses_the_speaker_did_not_say():
    source = qf.VideoText.from_raw("m", " ".join(s["text"] for s in MUNNA))
    # The caption's own "( Seaborn)" stays...
    assert qf.keepable("আজ আমি সি-বর্ন ( Seaborn) ব্যাখ্যা করতে যাচ্ছি।", source)[0] == (
        "আজ আমি সি-বর্ন ( Seaborn) ব্যাখ্যা করতে যাচ্ছি।"
    )
    # ...a gloss the model added goes, even when the quote already passed.
    reading, removed, reason = qf.keepable("এরপর আমরা এটিকে ইনস্টল (install it) করব।", source)
    assert (reading, removed, reason) == ("এরপর আমরা এটিকে ইনস্টল করব।", "(install it)", None)

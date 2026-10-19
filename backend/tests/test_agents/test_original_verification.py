"""Kept `original` wording must be the source's own words (N-002 regression fix).

The R1 run-5 replay (2026-10-19) packed a Bengali and two Hindi sources into
one map batch; the model wrote `original` values for the Hindi speaker in
BENGALI script — strings in no transcript — and the composer quoted him in
Bengali seven times. These tests drive the production map and compose stages
with a stubbed model and assert that such wording never survives.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.agents import report_agent
from app.services import code_mixing_service as cm
from app.utils.chunking import chunk_transcript

HINDI = [
    {"text": "बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों प्लॉट हमारे लिए सिमिलर टाइप हैं", "start": 0.0, "duration": 6.0},
    {"text": "इसको हम ज़्यादा यूज़ करेंगे जब डेटा में १४९ रोज़ होंगी", "start": 6.0, "duration": 6.0},
]
BENGALI = [
    {"text": "আজকে আমরা পাইথনে সিবর্ন লাইব্রেরি নিয়ে কথা বলব এবং দেখব কীভাবে প্লট করতে হয়", "start": 0.0, "duration": 6.0},
    {"text": "প্রথমে আমরা ডেটাসেট লোড করব তারপর ২৫টি সারি দেখব", "start": 6.0, "duration": 6.0},
]
HI_URL = "https://www.youtube.com/watch?v=hi1"
BN_URL = "https://www.youtube.com/watch?v=bn1"


def _chunks():
    hi = chunk_transcript(HINDI, video_metadata={
        "video_id": "hi1", "document_id": "doc-hi1", "title": "Seaborn in Hindi",
        "channel_name": "DeepLoop Circle", "url": HI_URL,
    })
    bn = chunk_transcript(BENGALI, video_metadata={
        "video_id": "bn1", "document_id": "doc-bn1", "title": "Seaborn in Bengali",
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


# --- normalisation ------------------------------------------------------------------
def test_normalisation_folds_spellings_not_scripts():
    n = cm.normalise_for_match
    # Precomposed nukta letter == base + nukta == no nukta at all.
    assert n("ज़्यादा") == n("ज़्यादा") == n("ज्यादा")
    # Chandrabindu and anusvara spell the same nasal.
    assert n("हूँ") == n("हूं")
    # Native digits are digits.
    assert n("१४९ रोज़") == n("149 रोज") and n("২৫টি") == n("25টি")
    # Punctuation, danda and case do not matter.
    assert n("Hello, World!") == n("hello world") and n("है। तो") == n("है तो")
    # Script does: Bengali never equals Devanagari.
    assert n("প্লট") != n("प्लॉट")


def test_merged_text_matches_a_quote_across_a_chunk_boundary():
    merged = cm.merge_chunk_texts(["one two three four five", "four five six seven", "six seven eight"])
    assert merged == "one two three four five six seven eight"
    assert cm.verbatim_in("three four five six", cm.normalise_for_match(merged))


def test_verbatim_fragments_and_short_originals():
    src = cm.normalise_for_match(" ".join(s["text"] for s in HINDI))
    assert cm.verbatim_in("बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों", src)
    # Elided with an ellipsis: each long fragment must be present.
    assert cm.verbatim_in("बॉक्स प्लॉट और वायलिन प्लॉट … सिमिलर टाइप हैं", src)
    assert not cm.verbatim_in("बॉक्स प्लॉट और वायलिन प्लॉट … बिल्कुल अलग चीज़ हैं", src)
    # A short original must match as a whole.
    assert cm.verbatim_in("टाइप हैं", src)
    assert not cm.verbatim_in("टाइप थे", src)
    assert not cm.verbatim_in("", src)


# --- at the caller: the map stage ------------------------------------------------------
def test_map_drops_wrong_script_invented_and_borrowed_originals_and_keeps_true_ones():
    true_hindi = "इसको हम ज़्यादा यूज़ करेंगे जब डेटा में 149 रोज होंगी"   # nukta and digit variants
    true_bengali = "প্রথমে আমরা ডেটাসেট লোড করব"
    items = [
        _item("বক্স প্লট এবং ভায়োলিন প্লট এই দুটো প্লট"),          # Hindi speaker, Bengali script
        _item("बॉक्स प्लॉट और वायलिन प्लॉट कभी यूज़ नहीं करने चाहिए"),   # invented wording
        _item(true_hindi),
        _item(true_bengali, url=BN_URL, title="Seaborn in Bengali"),
        _item("बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों", url=BN_URL, title="Seaborn in Bengali"),  # other video's words
        _item("बॉक्स प्लॉट और वायलिन प्लॉट ये दोनों", url="https://www.youtube.com/watch?v=zz",
              title="Not in this job"),                                     # unresolvable source
        {"content": "No original at all.", "video_url": HI_URL, "video_title": "Seaborn in Hindi"},
    ]
    out = _run_map(items)
    facts = out["chunk_summaries"][0]["facts"]
    kept = [f.get("original") for f in facts if f.get("original")]
    assert kept == [true_hindi, true_bengali]
    rejected = [f for f in facts if f.get("original_rejected")]
    assert len(rejected) == 4
    # The English point survives every drop.
    assert all(f["content"] for f in facts) and len(facts) == 7
    assert out["processing_notes"]["map_originals_kept"] == 2
    assert out["processing_notes"]["map_originals_dropped"] == 4
    # The audit record shows what was removed.
    record = json.loads(out["map_batch_records"][0]["payload_json"])
    assert sum(1 for f in record["facts"] if "original_rejected" in f) == 4


def test_a_quote_spanning_two_chunks_survives(monkeypatch):
    monkeypatch.setattr(report_agent, "_batch_budget", lambda *a, **k: 100_000)
    long_hindi = [
        {"text": f"वाक्य नंबर {i} में हम प्लॉट के बारे में बात करते हैं और आगे बढ़ते हैं", "start": float(i), "duration": 1.0}
        for i in range(40)
    ]
    chunks = chunk_transcript(long_hindi, chunk_size=128, chunk_overlap=32, video_metadata={
        "video_id": "hi2", "document_id": "doc-hi2", "title": "Long", "channel_name": "c", "url": HI_URL,
    })
    assert len(chunks) >= 3
    texts = report_agent._source_texts_for_verification(chunks)
    # The last words of chunk 0 followed by the first NEW words of chunk 1.
    merged = cm.merge_chunk_texts(c["text"] for c in chunks)
    first = chunks[0]["text"]
    start = len(first.split()) - 5
    quote = " ".join(merged.split()[start:start + 12])
    assert quote not in first and cm.verbatim_in(quote, texts["text"]["doc-hi2"])


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
    # The kept original reaches the composer as readable text, not \u escapes.
    assert any(HINDI[1]["text"] in p for p in prompts)
    assert not any(r"\u0907" in p for p in prompts)
    assert "1 quoted passage(s)" in html and "not found word for word" in html

"""Native-script text in a composed report must be some source's own words (N-002).

R1 run 7: the map item's `original` was verbatim — garbled ASR included,
"दिस इज़ अ वेरी वेरीेंट लाइब्रेरी" — and its English content said "a very
important library". The composer wrote "वेरी इंपॉर्टेंट लाइब्रेरी (very
important library)": the English back-translated into Devanagari and put in
the speaker's mouth. The map-level check cannot see that; these tests drive
the production compose stage with a stubbed composer and assert that such
text is removed, the English kept, and the removal disclosed — with the same
rule as the run-gate (`scripts/audit_quote_fidelity.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from app.agents import report_agent
from app.services import code_mixing_service as cm
from app.services import quote_fidelity as qf
from app.utils.chunking import chunk_transcript

# Real caption lines of the Gate Smashers source in job 419e691d (run 7).
GATE = [
    {"text": t, "start": float(i * 3), "duration": 3.0}
    for i, t in enumerate([
        "डियर स्टूडेंट्स वेलकम टू गेट्स मेशर्स।", "आज की इस वीडियो से स्टार्ट करने जा रहा",
        "हूं डेटा विजुअलाइजेशन यूजिंग मैट प्लॉट", "एलआईबी इन पython। तो यहां पे जो मैक",
        "प्लॉट एलआईबी है, दिस इज़ अ वेरी वेरीेंट", "लाइब्रेरी व्हिच इज़ यूज़्ड इन Python और ये",
        "स्पेशली यूज़ क्यों की जाती है? डेटा", "विजुअलाइज़ेशन एज़ वेल ऐज़ डेटा एनालिसिस।",
        "क्योंकि एनालिसिस और विजुअलाइजेशन आपस में", "रिलेटेड टर्म्स ही हैं। एनालिसिस में हम",
    ])
]
URL = "https://www.youtube.com/watch?v=0sk72TEs3zc"
TITLE = "मैटप्लॉटलिब से ग्राफ़ बनाना सीखें"          # a Devanagari title, cited in prose
BACK_TRANSLATED = "वेरी इंपॉर्टेंट लाइब्रेरी"           # run 7, verbatim
TRUE_ORIGINAL = "दिस इज़ अ वेरी वेरीेंट लाइब्रेरी व्हिच इज़ यूज़्ड इन Python"


def _chunks():
    return chunk_transcript(GATE, video_metadata={
        "video_id": "0sk72TEs3zc", "document_id": "doc-gate", "title": TITLE,
        "channel_name": "Gate Smashers", "url": URL,
    })


def _compose(section_html: str) -> dict:
    item = {"content": "Calls Matplotlib a very important library.", "original": TRUE_ORIGINAL,
            "video_title": TITLE, "channel_name": "Gate Smashers", "video_url": URL}
    calls = iter([section_html, "<h2>Executive Summary</h2><p>Plain English.</p>"])

    def fake_invoke(use_case, prompt, **kw):
        return next(calls, "")

    with patch.object(report_agent, "_invoke_with_retry", side_effect=fake_invoke):
        return report_agent.compose_report({
            "job_type": "topic", "topic": "t", "statistics": {"video_count": 1},
            "chunk_summaries": [{"facts": [item]}], "transcript_chunks": _chunks(),
        })


SECTION = (
    "<h2>Key Facts</h2>"
    f"<p>In <em>{TITLE}</em> — Gate Smashers (0:00), the instructor, having already called "
    f"Matplotlib {BACK_TRANSLATED} (very important library), moves to plotting.</p>"
    f"<p>He says <strong>{TRUE_ORIGINAL}</strong> (dis iz a verī verīṇṭ lāibrerī) — "
    "\"this is a very important library which is used in Python\".</p>"
    "<p>He adds एकदम नई बात जो किसी ने कभी नहीं कही (ekdam naī bāt) — \"a brand new claim\".</p>"
)


def test_the_run7_back_translation_is_removed_and_the_english_kept():
    out = _compose(SECTION)
    html = out["final_html"]
    # The back-translated Devanagari is gone; its plain-English gloss stays in the sentence.
    assert BACK_TRANSLATED not in html
    assert "called Matplotlib very important library, moves to plotting" in html
    # The verbatim original — caption errors and all — survives in full three-part form.
    assert TRUE_ORIGINAL in html and "(dis iz a verī verīṇṭ lāibrerī)" in html
    # Invented speech in three-part form: original and transliteration go, the translation stays.
    assert "एकदम नई बात" not in html and "(ekdam naī bāt)" not in html
    assert "He adds \"a brand new claim\"" in html
    # A Devanagari title in a citation is attribution, not quotation: untouched.
    assert f"<em>{TITLE}</em>" in html
    # Counted and disclosed.
    assert out["processing_notes"]["report_quotes_removed"] == 2
    assert "2 passage(s) of non-English text" in html and "did not match any source's speech" in html


def test_a_report_with_only_true_quotes_is_untouched():
    section = f"<h2>Key Facts</h2><p>He says {TRUE_ORIGINAL} — \"this is a very important library\".</p>"
    out = _compose(section)
    assert section in out["final_html"]
    assert out["processing_notes"]["report_quotes_removed"] == 0
    assert "did not match any source's speech" not in out["final_html"]


def test_what_the_pipeline_leaves_the_run_gate_passes():
    """Same rule, same answer: after the scrub, the gate finds nothing to fail."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import audit_quote_fidelity as aq

    html = _compose(SECTION)["final_html"]
    corpus = aq.parse_transcript(
        "\n".join([f"=== {TITLE} ({URL}) ==="] + [s["text"] for s in GATE])
    )
    failing = [f for f in aq.audit_report(html, corpus) if aq.fails(f)]
    # The only native run the gate may still see is the title, which it reads
    # as a quotation; everything the composer invented is gone.
    assert all(f.quote.startswith("मैटप्लॉटलिब") for f in failing)


def test_scrub_keeps_plain_english_glosses_and_drops_transliterations():
    corpus = {"g": qf.VideoText.from_raw("g", " ".join(s["text"] for s in GATE))}
    html, removed = qf.scrub_report(
        "<p>A एकदम नई बात कही (a brand new thing) here; B एकदम नई बात कही (ekdam naī bāt kahī) there.</p>", corpus
    )
    assert html == "<p>A a brand new thing here; B there.</p>"
    assert removed[0]["occurrences"] == 2 and removed[0]["verdict"] == "absent"


def test_scrub_matches_a_run_split_by_markup():
    corpus = {"g": qf.VideoText.from_raw("g", " ".join(s["text"] for s in GATE))}
    html, removed = qf.scrub_report("<p>X <em>एकदम नई</em> बात कही Y</p>", corpus)
    assert "एकदम" not in html and removed


def test_a_romanised_source_is_quoted_in_roman_even_when_hindi_dominant():
    meta = {"code_mix_primary": "hi", "code_mix_script": "Latin", "code_mix_quote": "native_script",
            "code_mix_share": 0.8}
    assert cm.quote_form(meta) == "quote in Roman script + English translation"
    meta_deva = dict(meta, code_mix_script="Devanagari")
    assert cm.quote_form(meta_deva).startswith("quote in Devanagari")

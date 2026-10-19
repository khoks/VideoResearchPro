"""audit_quote_fidelity.py — the verdicts R1 run 6 is judged by.

The strings are from run 5 (job 419e691d): a Hindi speaker quoted in
Bengali, Bengali letters spliced into Devanagari words, and a Bengali speaker
whose caption spelling the model regularised. The first two are defects; the
third is not, and treating it as one would make the audit cry wolf.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import audit_quote_fidelity as aq  # noqa: E402

HINDI = "aaaaaaaaaaa"
BENGALI = "bbbbbbbbbbb"
ENGLISH = "ccccccccccc"

TRANSCRIPT = f"""=== Seaborn in Hindi (https://www.youtube.com/watch?v={HINDI}) ===
माय नेम इज विवेक और आज हम पढ़ने वाले हैं सीबॉर्न।
हिस्टोग्राम में आपके x और y वेरिएबल दो नहीं होते। सिर्फ x वेरिएबल होता है।
=== Seaborn in Bengali (https://www.youtube.com/watch?v={BENGALI}) ===
এমন কিছু নেই যা আপনি ম্যাটপ্লোটলিব এ করতে পারেন
কিন্তু সি বর্নে পারেন না। আউটপুট স্ক্রিনে এভাবে আসবে: ০.১৩.২।
[VISUAL @ 3:10 — A notebook cell prints “সিবর্ন ভার্সন চেক করুন” above the version.]
=== Matplotlib (https://www.youtube.com/watch?v={ENGLISH}&t=5) ===
So we are using a retail sales data set.
"""


def corpus():
    return aq.parse_transcript(TRANSCRIPT)


def test_normalise_drops_danda_nukta_and_maps_native_digits():
    assert aq.normalise("आसवे: ০.১৩.২।") == aq.normalise("आसवे 0 13 2")
    assert aq.normalise("डिफ़ॉल्ट") == aq.normalise("डिफॉल्ट")


def test_transcript_splits_speech_from_visual_spans_per_video():
    c = corpus()
    assert set(c) == {HINDI, BENGALI, ENGLISH}
    assert "সিবর্ন ভার্সন" in c[BENGALI].visual
    assert "সিবর্ন ভার্সন" not in c[BENGALI].speech
    assert c[HINDI].script == "DEVANAGARI"
    assert c[BENGALI].script == "BENGALI"
    assert c[ENGLISH].script is None


def test_elided_quote_is_verbatim():
    verdict, vid = aq.classify("माय नेम इज विवेक ... सिर्फ x वेरिएबल होता है।", HINDI, corpus())
    assert (verdict, vid) == ("verbatim", HINDI)


def test_regularised_caption_spelling_is_near_not_absent():
    quote = "এমন কিছু নেই যা আপনি ম্যাটপ্লটলিবে করতে পারেন কিন্তু সি বর্নে পারেন না"
    assert aq.classify(quote, BENGALI, corpus())[0] == "near"


def test_hindi_speaker_quoted_in_bengali_fails_twice():
    # Run 5's report put this in Vivek's mouth; he said it in Hindi.
    f = aq._finding("হিস্টোগ্রামে আপনার x এবং y ভেরিয়েবল দুটো থাকে না। শুধু x ভেরিয়েবল থাকে।", HINDI, corpus())
    assert f.verdict == "absent"
    assert f.script_mismatch and (f.script, f.video_script) == ("BENGALI", "DEVANAGARI")
    assert aq.fails(f)


def test_screen_text_is_not_speech():
    assert aq.classify("সিবর্ন ভার্সন চেক করুন", BENGALI, corpus())[0] == "visual_only"


def test_quote_from_another_video_is_caught():
    verdict, vid = aq.classify("माय नेम इज विवेक और आज हम", BENGALI, corpus())
    assert (verdict, vid) == ("other_video", HINDI)


def test_bengali_letters_spliced_into_devanagari_words_are_flagged():
    assert aq.mixed_script_words("लिमিটेशंस ऑफ़ मैटिली के बारे में জানेंगे") == ["लिमিটेशंस", "জানेंगे"]
    assert aq.mixed_script_words("plt ডট টাইটেল और हिंदी") == []


def test_report_runs_bridge_code_tokens_and_skip_single_terms():
    html = ("<p>He calls it <em>अहिंसा</em> and moves on.</p>"
            "<blockquote>plt ডট টাইটেল এখন টাইটেল (plt dot title) — “now the title”</blockquote>")
    assert aq.report_native_runs(html) == ["ডট টাইটেল এখন টাইটেল"]


def test_report_audit_locates_quotes_anywhere_in_the_corpus():
    # The first quote spans two caption lines, which the parser joins.
    html = "<p>“সি বর্নে পারেন না। আউটপুট স্ক্রিনে এভাবে আসবে” — and a made-up line: “এটা কখনো বলা হয়নি একদম”</p>"
    findings = aq.audit_report(html, corpus())
    assert [(f.verdict, f.matched_video) for f in findings] == [("verbatim", BENGALI), ("absent", None)]
    assert aq.summarise(findings)["failing"] == 1


def test_items_are_read_from_persisted_map_payloads():
    payload = {"facts": [
        {"content": "x", "original": "माय नेम इज विवेक", "video_url": f"https://www.youtube.com/watch?v={HINDI}&t=0"},
        {"content": "y", "video_url": f"https://www.youtube.com/watch?v={HINDI}"},
    ], "speakers": "not a list"}
    inter = {"map": [{"payload_json": json.dumps(payload)}, {"payload_json": "{broken"}]}
    findings = aq.audit_items(inter, corpus())
    assert [(f.verdict, f.video_id, f.category) for f in findings] == [("verbatim", HINDI, "facts")]


def test_check_flag_fails_only_on_report_level_defects(tmp_path):
    (tmp_path / "transcript_annotated.txt").write_text(TRANSCRIPT, encoding="utf-8")
    (tmp_path / "on.html").write_text("<p>“এটা কখনো বলা হয়নি একদম”</p>", encoding="utf-8")
    (tmp_path / "off.html").write_text("<p>“माय नेम इज विवेक”</p>", encoding="utf-8")
    assert aq.main([str(tmp_path), "--arms", "off", "--check"]) == 0
    assert aq.main([str(tmp_path), "--check", "--out", str(tmp_path / "q.json")]) == 1
    assert json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))["on"]["report"]["summary"]["failing"] == 1

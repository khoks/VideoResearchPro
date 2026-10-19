"""modality_check.py — the pieces whose failure produced wrong conclusions.

Each case here is something that went wrong while measuring R1 on a
multilingual corpus: Bengali digits that hid a spoken version number, a video
title ("01. Seaborn in Python") that split a sentence away from its citation,
and ASR rendering `plt.plot` as words.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import modality_check as mc  # noqa: E402


def test_native_digits_normalise_to_ascii():
    assert "0.13.2" in mc.normalise("আউটপুট স্ক্রিনে এভাবে আসবে: ০.১৩.২")
    assert "50000" in mc.normalise("above $50,000")


def test_identifier_counts_as_spoken_when_its_parts_are_spoken():
    speech = mc.normalise("then plt dot plot and we pass the list")
    assert mc.present("plt.plot", speech)
    assert not mc.present("fig.savefig", speech)


def test_word_pair_needs_both_words():
    assert mc.present("confidence band", mc.normalise("the shaded band shows confidence"))
    assert not mc.present("confidence band", mc.normalise("a fitted regression line"))


def test_enumerated_title_does_not_split_a_sentence_from_its_citation():
    html = (
        '<p>The video displays Seaborn version 0.13.2 at 03:10 — 01. Seaborn in Python — CodeWithMunnaX '
        '(<a href="https://www.youtube.com/watch?v=5AuuOZ4vuxI&amp;t=190">03:10</a>).</p>'
    )
    sents = mc.report_sentences(html)
    assert len(sents) == 1
    assert sents[0][1] == [("5AuuOZ4vuxI", 190)]


def test_timestamps_and_title_tail_are_not_details():
    toks = [t for t, _ in mc.specific_tokens("Axis limits use 2013 and 2019 — Python Tutorial 2026 — Academind (9:17)")]
    assert "2013" in toks and "2019" in toks
    assert "2026" not in toks and "17" not in toks


def _report(sentence: str, vid: str = "abcdefghijk", t: int = 190) -> str:
    return f'<p>{sentence} (<a href="https://www.youtube.com/watch?v={vid}&t={t}">{t // 60}:{t % 60:02d}</a>).</p>'


def test_screen_claim_without_a_nearby_frame_is_flagged():
    ev = {"abcdefghijk": mc.Evidence(speech=[(185.0, "print seaborn version and the output is 0.13.2")],
                                     visual=[(158.0, "a notebook importing pandas")])}
    found = mc.check_report(_report("The video displays Seaborn version 0.13.2 on screen at 3:10"), ev)
    assert [f.kind for f in found] == ["screen_claim_without_span"]


def test_screen_detail_credited_to_a_speaker_is_flagged_in_latin_speech_only():
    span = (600.0, "A regression plot with a fitted line and a shaded confidence band")
    latin = {"abcdefghijk": mc.Evidence(speech=[(610.0, "a regression plot shows the best fit line")], visual=[span])}
    found = mc.check_report(_report("The presenter says a regression plot adds a confidence band", t=600), latin)
    assert found and found[0].kind == "screen_detail_attributed_to_speaker"
    assert "confidence band" in found[0].tokens

    bengali = {"abcdefghijk": mc.Evidence(speech=[(610.0, "এখানে রিগ্রেশন প্লট দেখাচ্ছে")], visual=[span])}
    assert mc.check_report(_report("The presenter says a regression plot adds a confidence band", t=600), bengali) == []

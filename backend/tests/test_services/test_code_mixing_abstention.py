"""Abstention and English in Devanagari: T-1.16.2.15 and T-1.16.2.8.

The tagger knows English and Hindi. Before T-1.16.2.15 a word in neither list
had to land on one of them, so a Spanish source measured as Hindi and every
prompt said so. It now abstains (`OTHER`) on Latin text with no Hindi evidence.
Before T-1.16.2.8 every Devanagari word outside a closed list of function
words read as Hindi, English content words included.

The floors here restate the acceptance rule in PR #403, on the DEV split and
the foreign sample only; the held-out figures stay in test_code_mixing_service.
The sample is hand-written: `tuning` languages set the parameters, `unseen`
ones set nothing, `romanised_control` is Hindi that must stay Hindi.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents import knowledge_agent, report_agent
from app.services import code_mixing_eval as ev
from app.services import code_mixing_service as cm
from app.utils.chunking import chunk_transcript

SAMPLE = json.loads(
    (Path(ev.FIXTURE).parent / "foreign_latin_sample.json").read_text(encoding="utf-8")
)
FOREIGN = [d for d in SAMPLE if d["group"] in ("tuning", "unseen")]
CONTROLS = [d for d in SAMPLE if d["group"] == "romanised_control"]


def _by(doc_id: str) -> dict:
    return next(d for d in SAMPLE if d["id"] == doc_id)


def _tag_counts(text: str) -> Counter:
    counts: Counter = Counter()
    for window in cm.transcript_windows(text):
        counts.update(tag for _, tag in cm.tag_tokens(window))
    return counts


def _dev() -> list[dict]:
    return [u for u in ev.load_units() if u["split"] == "dev"]


def _dev_scores() -> dict:
    units = _dev()
    return ev.score(units, {u["id"]: [t for _, t in cm.tag_tokens(u["text"])] for u in units})


# --- the sample's shape ---------------------------------------------------------
def test_sample_covers_the_languages_the_rule_names():
    groups = {d["group"]: {x["language"] for x in SAMPLE if x["group"] == d["group"]} for d in SAMPLE}
    assert groups["tuning"] == {"es", "fr", "de"}
    assert groups["unseen"] == {"pt", "it", "id", "tl", "tr"}
    assert len({d["id"] for d in SAMPLE}) == len(SAMPLE)
    assert all(len(cm.tokenize(d["text"])) > 70 for d in SAMPLE)


# --- T-1.16.2.15: a language the tagger does not know ------------------------------
@pytest.mark.parametrize("doc", FOREIGN, ids=lambda d: d["id"])
def test_no_foreign_source_measures_as_hindi(doc):
    profile = cm.profile_transcript(doc["text"])
    meta = cm.chunk_metadata_from_profile(profile)

    assert profile["primary_language"] == "other"
    assert profile["native_script"] == "Latin"
    assert "Hindi (romanised)" not in cm.source_note(meta)
    assert "not English or Hindi" in cm.source_note(meta)
    # A script's worth of quoting: Spanish is shown in the letters it is written in.
    assert cm.quote_form(meta) == "quote in Roman script + English translation"


@pytest.mark.parametrize("doc", FOREIGN, ids=lambda d: d["id"])
def test_at_least_nine_in_ten_foreign_words_are_abstained(doc):
    counts = _tag_counts(doc["text"])
    assert counts[cm.OTHER] / (counts[cm.OTHER] + counts["hi"]) >= 0.9


@pytest.mark.parametrize("doc", CONTROLS, ids=lambda d: d["id"])
def test_romanised_hindi_still_measures_as_hindi(doc):
    profile = cm.profile_transcript(doc["text"])
    note = cm.source_note(cm.chunk_metadata_from_profile(profile))

    assert profile["named_share"] == 1.0
    assert "Hindi (romanised)" in note
    expected = "en" if doc["style"] == "english_matrix" else "hi"
    assert profile["primary_language"] == expected


def test_the_two_margins_are_wide_at_window_level():
    """What the thresholds rest on: Hindi-lexicon words over Hindi-lexicon +
    unplaced words. Romanised Hindi reads 0.51 and up, foreign windows 0.23 at
    most, so `EVIDENCE_MIN_SHARE` 0.3 sits between them, and DEV's token
    scores do not move anywhere from 0.15 to 0.4."""
    lex = cm.lexicons()

    def evidence(window: str) -> float:
        words = [t.norm for t in cm.tokenize(window)
                 if t.script == "Latin" and t.norm not in cm._NEUTRAL_WORDS]
        hindi = sum(w in lex.hindi and w not in lex.english_zipf for w in words)
        unplaced = sum(w not in lex.hindi and w not in lex.english_zipf for w in words)
        return hindi / max(1, hindi + unplaced)

    prose = [d for d in CONTROLS if d["style"] != "english_matrix"]
    assert min(evidence(w) for d in prose for w in cm.transcript_windows(d["text"])) > 0.45
    assert max(evidence(w) for d in FOREIGN for w in cm.transcript_windows(d["text"])) < 0.3


def test_a_foreign_span_is_tagged_other_and_counts_as_non_english():
    span = "el perro de mi hermana come en la cocina todos los dias porque tiene mucha hambre"
    tags = Counter(tag for _, tag in cm.tag_tokens(span))
    a = cm.analyse_span(span)

    assert tags[cm.OTHER] > 8 and tags["hi"] == 0
    # Every share and rendering decision still sees "not English", so such a
    # chunk is translated and rendered for retrieval as before.
    assert a["hi_share"] > 0.5
    assert a["matrix"] == "hi"
    assert cm.rendering_mode(a) != cm.PLAIN_ENGLISH


def test_a_homograph_of_an_english_word_does_not_make_a_span_english():
    # "no" and "a" vote English in the morpheme vote. With most of the span
    # unplaced there is no grammar to vote on.
    span = "no me gusta nada ir a la tienda con tanta gente porque siempre tardamos mucho"
    assert cm.matrix_language(cm.tag_tokens(span)) == "hi"


def test_an_english_span_keeps_its_words_and_only_loses_the_guess():
    """Stray words in English are not another language: only the n-gram's
    "Hindi" guess goes, and the share stays as it was."""
    span = "Lakshmi and Bhavani talked about Sundarbans for an hour on the show"
    tagged = cm.tag_tokens(span)
    other = [t.text for t, tag in tagged if tag == cm.OTHER]

    assert other and not [t for t, tag in tagged if tag == "hi"]
    assert cm.matrix_language(tagged) == "en"


def test_a_short_span_proves_nothing_about_a_language():
    """Below `UNPLACED_MIN_WORDS` an English span of unknown words must not
    jump to another language: on DEV that flipped three rendering decisions."""
    s = cm.shares(tag for _, tag in cm.tag_tokens("Sugar cosmetics are they making profit"))
    assert s["hi_share"] < 0.2


def test_a_language_close_to_english_is_not_called_english_or_hindi():
    """Dutch shares enough words with English that half its windows keep a
    majority of known words and an English vote, so its grammar reads English.
    Its unplaced words still outnumber anything an English source shows, and
    none of them is Hindi: the source is "other", not "mostly English with
    Hindi (romanised)"."""
    dutch = (
        "Ik was in de winkel en mijn broer was met zijn vrouw in het park. We hadden over de "
        "film gesproken en de man in de bus was er ook. Het is een goed idee om de hand op de "
        "tafel te leggen want de kinderen hebben veel water nodig in de winter. Wij zijn in de "
        "stad en de lamp is warm in de avond, dus we gaan naar huis met de trein van acht uur. "
    ) * 2
    profile = cm.profile_transcript(dutch)

    assert profile["matrix_hi_share"] < 0.5  # the case this test is for
    assert profile["primary_language"] == "other"
    assert "Hindi" not in cm.source_note(cm.chunk_metadata_from_profile(profile)).replace(
        "not English or Hindi", ""
    )


def test_english_with_unplaced_names_is_plain_english():
    """English talks full of Indian names read 3 to 4% "non-English" and were
    told to the prompts as romanised Hindi. The floor now counts the words the
    tagger can name."""
    profile = {"primary_language": "en", "native_script": "Latin", "hi_share": 0.045,
               "named_share": 0.06, "matrix_hi_share": 0.01, "quote_mode": cm.PLAIN_ENGLISH}
    assert cm.chunk_metadata_from_profile(profile) == {}
    # Real Hindi in the same amount still counts.
    assert cm.chunk_metadata_from_profile({**profile, "named_share": 0.9})["code_mix_primary"] == "en"


def test_a_profile_stored_before_named_share_reads_as_it_did():
    stored = {"primary_language": "en", "native_script": "Latin", "hi_share": 0.045,
              "matrix_hi_share": 0.01, "quote_mode": cm.PLAIN_ENGLISH}
    meta = cm.chunk_metadata_from_profile(stored)
    assert meta["code_mix_primary"] == "en"
    assert "Hindi (romanised)" in cm.source_note(meta)


# --- at the callers ----------------------------------------------------------------
def _segments(text: str) -> list[dict]:
    words = text.split()
    return [
        {"text": " ".join(words[i:i + 12]), "start": float(i), "duration": 4.0}
        for i in range(0, len(words), 12)
    ]


def _chunks(doc_id: str) -> list[dict]:
    return chunk_transcript(_segments(_by(doc_id)["text"]), video_metadata={
        "video_id": doc_id, "document_id": f"doc-{doc_id}", "title": doc_id,
        "channel_name": "Ch", "url": f"https://www.youtube.com/watch?v={doc_id}",
    })


def test_the_chunker_writes_the_abstention_and_keeps_the_rendering_decision():
    meta = _chunks("es-speech")[0]["metadata"]

    assert meta["code_mix_primary"] == "other" and meta["code_mix_script"] == "Latin"
    assert cm.needs_english_rendering(meta)  # D-084 still applies to Spanish


def test_a_report_map_prompt_does_not_call_a_spanish_source_hindi():
    response = MagicMock()
    response.content = '{"facts": [], "comments": [], "conclusions": [], "references": [], "speakers": []}'
    llm = MagicMock()
    llm.invoke.return_value = response
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        report_agent.map_chunks({"job_type": "topic", "transcript_chunks": _chunks("es-essay"), "topic": "t"})
    prompt = "\n".join(call.args[0][0].content for call in llm.invoke.call_args_list)

    headers = [line for line in prompt.splitlines() if line.startswith("[es-essay")]
    assert headers and all("speech: not English or Hindi" in h for h in headers)
    assert not any("Hindi (romanised)" in h for h in headers)


def test_knowledge_extraction_is_not_told_a_german_source_is_hindi():
    response = MagicMock()
    response.content = '{"topics": [], "concepts": [], "events": [], "facts": []}'
    llm = MagicMock()
    llm.invoke.return_value = response
    text = _by("de-speech")["text"]
    with patch.object(knowledge_agent, "get_llm_for", return_value=llm):
        knowledge_agent.extract_per_batch({
            "transcript_batches": [text], "video_title": "v", "channel_name": "c",
            "full_transcript_text": text,
        })
    prompt = llm.invoke.call_args.args[0][0].content

    assert "SOURCE LANGUAGE (measured from this transcript) — speech: not English or Hindi" in prompt
    assert "Hindi written in Latin letters is Hindi" not in prompt


def test_rule_a_on_the_tuning_split():
    """A1 to A3 of the rule in PR #403: abstention costs at most 2 of DEV's 106
    gold Hindi tokens, no Hindi-bearing unit, and no decision. Today it costs
    none. Measured with `_abstain` in place: P 0.981, R 0.962, 12 of 12."""
    latin = _dev_scores()["latin"]
    assert latin["token_hindi"]["recall"] >= 0.943
    assert latin["token_hindi"]["fp"] <= 2
    assert (latin["unit_contains_hindi"]["tp"], latin["unit_contains_hindi"]["fn"]) == (12, 0)
    assert latin["unit_contains_hindi"]["fp"] == 0

    units = _dev()
    matrix = ev.matrix_accuracy(units, {u["id"]: cm.matrix_language(cm.tag_tokens(u["text"])) for u in units})
    assert matrix["accuracy"] >= 27 / 28 - 1e-3
    agreement = ev.policy_agreement(units)["agreement"]
    assert agreement["latin"] >= 0.9877 and agreement["mixed"] >= 0.9285


def test_mutation_without_abstaining_a_spanish_source_is_hindi_again(monkeypatch):
    """Mutation check: drop the pass and the bug this task fixes comes back."""
    monkeypatch.setattr(cm, "_abstain", lambda *a: None)
    profile = cm.profile_transcript(_by("id-speech")["text"])
    note = cm.source_note(cm.chunk_metadata_from_profile(profile))
    assert profile["primary_language"] == "hi" and "Hindi (romanised)" in note


# --- T-1.16.2.8: English content words in Devanagari ----------------------------------
def _hindi(text: str) -> list[str]:
    return [t.text for t, tag in cm.tag_tokens(text) if tag == "hi"]


def test_english_content_words_in_devanagari_are_english():
    assert _hindi("आज हम मशीन लर्निंग का कांसेप्ट समझेंगे") == ["आज", "हम", "का", "समझेंगे"]


def test_endings_on_an_english_stem_stay_english():
    assert _hindi("मशीनों कंपनियों प्रोडक्ट्स मॉडल्स") == []


def test_nasal_and_nukta_spellings_are_one_word():
    assert cm.devanagari_key("कम्पनी") == cm.devanagari_key("कंपनी")
    assert cm.devanagari_key("कॉन्सेप्ट") == cm.devanagari_key("कॉंसेप्ट")
    assert cm.devanagari_key("बिज़नेस") == cm.devanagari_key("बिजनेस")
    # A nukta on ड makes another letter: गुड़ is jaggery, not "good".
    assert cm.devanagari_key("गुड़") != cm.devanagari_key("गुड")
    assert _hindi("गुड़ गुड") == ["गुड़"]


def test_a_vowel_sign_only_english_uses_marks_the_word_english():
    assert _hindi("प्लॉट ऑफिसर बॅटरी") == []


@pytest.mark.parametrize("word", [
    "काम", "बात", "लोग", "समय", "बस", "पास", "पर", "मन", "कम", "आई", "दे", "इन", "है", "नहीं", "मेरा",
])
def test_hindi_words_that_look_like_english_ones_stay_hindi(word):
    assert _hindi(word) == [word]


def test_the_lexicon_holds_single_devanagari_words_and_no_hindi_system_word():
    path = Path(cm.__file__).parent / "lexicons" / "english_devanagari.txt"
    words = [w.strip() for w in path.read_text(encoding="utf-8").splitlines()
             if w.strip() and not w.startswith("#")]
    assert len(words) == len(set(words)) and len(words) > 900
    for word in words:
        tokens = cm.tokenize(word)
        assert [t.text for t in tokens] == [word]
        assert tokens[0].script == "Devanagari"
    hindi = {cm.devanagari_key(w) for w in cm.HINDI_VERBAL_MORPHEMES | cm.HINDI_FUNCTION_MORPHEMES}
    assert not cm.lexicons().devanagari_english & hindi


def test_a_clash_with_a_hindi_system_word_is_resolved_for_hindi(monkeypatch):
    real = cm._read_words
    monkeypatch.setattr(
        cm, "_read_words",
        lambda path: real(path) + (["है"] if path.name == "english_devanagari.txt" else []),
    )
    assert "है" not in cm.lexicons.__wrapped__().devanagari_english


def test_the_share_of_devanagari_hinglish_falls_to_what_it_is():
    a = cm.analyse_span("तो आज हम बात करेंगे मशीन लर्निंग के बारे में और डेटा साइंस का कोर्स देखेंगे")
    assert 0.6 < a["hi_share"] < 0.85
    assert a["matrix"] == "hi"


def test_rule_b_on_the_tuning_split():
    """B1 to B5 of the rule in PR #403. Before: P 0.808, R 1.000, MAE 0.195.
    Base list alone, before any DEV-derived entry: P 0.921, MAE 0.066."""
    s = _dev_scores()
    deva = s["devanagari"]
    assert deva["token_hindi"]["precision"] >= 0.87
    assert deva["token_hindi"]["recall"] >= 0.971
    assert deva["hindi_share_mae"] <= 0.13
    assert ev.policy_agreement(_dev())["agreement"]["devanagari"] >= 0.9375
    # B5: the Latin figures are the ones rule A pins.
    assert s["latin"]["token_hindi"]["tp"] == 102


def test_mutation_without_the_lexicon_the_blind_spot_is_back(monkeypatch):
    """Mutation check: an empty lexicon reads every content word as Hindi."""
    empty = cm.lexicons().__class__(**{
        **{f: getattr(cm.lexicons(), f) for f in cm.lexicons().__dataclass_fields__},
        "devanagari_english": frozenset(),
    })
    monkeypatch.setattr(cm, "lexicons", lambda: empty)
    assert _hindi("मशीन लर्निंग") == ["मशीन", "लर्निंग"]

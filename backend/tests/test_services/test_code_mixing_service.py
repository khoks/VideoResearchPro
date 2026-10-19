"""Romanised code-mixing detection — S-1.16.2 / N-002.

The evaluation tests score both detectors against the hand-labelled set in
`tests/fixtures/code_mixing/`. The lexicon detector runs live (it is free and
deterministic); the LLM detector is scored from its cached answers, so no
test calls a provider. The floors sit just under the measured held-out
numbers: a lexicon or parameter change that costs real accuracy fails here.
Method and numbers: docs/notes/2026-10-19-code-mixing-detection.md.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.services import code_mixing_eval as ev
from app.services import code_mixing_service as cm
from app.services import language_service as ls

USER_EXAMPLE = (
    "and this is how we were preparing taaki baadme koi kasar koi zarra na "
    "reh jaye and so we kept on you know adding hum jodte rahe cheezein"
)


def _hindi_words(text: str) -> list[str]:
    return [t.text for t, tag in cm.tag_tokens(text) if tag == "hi"]


# --- tokenizer -----------------------------------------------------------------
def test_tokenizer_keeps_devanagari_words_whole():
    # `\w` would split कांसेप्ट into four pieces at its vowel signs.
    toks = cm.tokenize("कांसेप्ट इसी, आधार पर")
    assert [t.text for t in toks] == ["कांसेप्ट", "इसी", "आधार", "पर"]
    assert {t.script for t in toks} == {"Devanagari"}


def test_tokenizer_offsets_and_numbers():
    toks = cm.tokenize("don't 12th-class")
    assert [t.text for t in toks] == ["don't", "12", "th", "class"]
    assert toks[1].script == "Number"
    assert all("don't 12th-class"[t.start:t.end] == t.text for t in toks)


# --- the gap this story closes ----------------------------------------------------
def test_the_users_example_is_detected_where_script_profiling_sees_english():
    # language_service reads the sentence as 100% Latin; that pinned gap stays
    # (test_language_service) — this module is what answers the other question.
    assert ls.dominant_script(USER_EXAMPLE) == "Latin"
    assert ls.needs_translation(USER_EXAMPLE) is False

    hindi = _hindi_words(USER_EXAMPLE)
    assert hindi == [
        "taaki", "baadme", "koi", "kasar", "koi", "zarra", "na", "reh", "jaye",
        "hum", "jodte", "rahe", "cheezein",
    ]
    p = cm.profile_text(USER_EXAMPLE)
    assert p["hi_tokens"] == 13 and p["en_tokens"] == 15


def test_ambiguous_words_follow_their_clause():
    # "to" / "me" / "main" are English words AND Hindi function words.
    assert _hindi_words("I want to go to the market") == []
    assert _hindi_words("mujhe to pata hi nahi tha") == ["mujhe", "to", "pata", "hi", "nahi", "tha"]
    assert "main" in _hindi_words("main kal ghar ja raha hoon")
    assert _hindi_words("the main thing is to ship") == []


def test_english_nouns_inside_hindi_grammar_stay_english():
    tags = dict((t.text, tag) for t, tag in cm.tag_tokens("model ko train karna padta hai with the data"))
    assert tags["ko"] == tags["karna"] == tags["padta"] == tags["hai"] == "hi"
    assert tags["model"] == tags["train"] == tags["data"] == "en"


def test_plain_english_and_tech_talk_carry_no_hindi():
    for text in (
        "So in this other paper called Reasoning with Exploration and Entropy Perspective",
        "We wanted to expect JSON formats, input and output. So that's a difference.",
    ):
        assert cm.profile_text(text)["hi_tokens"] == 0, text


def test_fillers_and_numbers_are_neutral():
    p = cm.profile_text("um uh 2008 ok")
    assert p == {"en_tokens": 0, "hi_tokens": 0, "hi_share": 0.0}


def test_devanagari_words_are_hindi_by_script():
    tags = [tag for _, tag in cm.tag_tokens("आज हम बात करेंगे about this topic")]
    assert tags == ["hi"] * 4 + ["en"] * 3


# --- labelled set -----------------------------------------------------------------
def test_labelled_set_shape():
    units = ev.load_units()
    assert len(units) == 300
    assert len({u["id"] for u in units}) == 300
    assert {u["split"] for u in units} == {"dev", "test"}
    assert {u["source"] for u in units} == {
        "comment", "caption_latin_indian", "caption_devanagari", "caption_english",
    }
    tokens = sum(len(ev.gold_tags(u)) for u in units)
    assert tokens > 4000


def test_every_annotation_strips_to_its_source_text():
    for u in ev.load_units():
        tags = ev.gold_tags(u)       # raises on a labelling slip
        assert len(tags) == len(cm.tokenize(u["text"]))


def test_gold_parser_rejects_an_annotation_that_drifts_from_the_text():
    unit = {"id": "x", "text": "mujhe nahi pata", "base": "en",
            "annotation": "{mujhe nahi} pataa", "matrix": "hi"}
    with pytest.raises(ValueError, match="does not strip"):
        ev.gold_tags(unit)
    unit["annotation"] = "{mujhe nahi pata"
    with pytest.raises(ValueError, match="unclosed"):
        ev.gold_tags(unit)


def test_gold_parser_markup():
    unit = {"id": "x", "text": "Harry bhai machine learning pe course lao", "base": "en",
            "annotation": "<Harry> {bhai} machine learning {pe} course {lao}", "matrix": "hi"}
    assert ev.gold_tags(unit) == ["ne", "hi", "en", "en", "hi", "en", "hi"]
    unit = {"id": "y", "text": "आपको मशीन दिखती है", "base": "hi",
            "annotation": "आपको |मशीन| दिखती है", "matrix": "hi"}
    assert ev.gold_tags(unit) == ["hi", "en", "hi", "hi"]


# --- measured accuracy (held-out TEST split) ------------------------------------------
def _test_units():
    return [u for u in ev.load_units() if u["split"] == "test"]


def test_lexicon_detector_on_held_out_romanised_text():
    units = _test_units()
    pred = {u["id"]: [t for _, t in cm.tag_tokens(u["text"])] for u in units}
    s = ev.score(units, pred)["latin"]
    # Measured 2026-10-19: token P 0.929 R 0.890; unit P 0.875 R 0.933.
    assert s["token_hindi"]["precision"] >= 0.90
    assert s["token_hindi"]["recall"] >= 0.86
    assert s["unit_contains_hindi"]["recall"] >= 0.90
    assert s["hindi_share_mae"] <= 0.03


def test_lexicon_detector_cannot_see_english_content_words_in_devanagari():
    """The known blind spot, pinned so it is measured rather than forgotten:
    a Devanagari word is Hindi to the lexicon detector unless it is one of
    the closed class of English function words (इज, टू, द), so "मशीन
    लर्निंग" counts as Hindi. Recall stays perfect; precision is what it
    costs. Measured 0.767 before the function-word list (T-1.16.2.1), 0.792
    after (T-1.16.2.2)."""
    units = _test_units()
    pred = {u["id"]: [t for _, t in cm.tag_tokens(u["text"])] for u in units}
    s = ev.score(units, pred)["devanagari"]
    assert s["token_hindi"]["recall"] == 1.0
    assert 0.78 <= s["token_hindi"]["precision"] < 0.82


def test_english_function_words_in_devanagari_are_english_and_hindi_homographs_are_not():
    tags = [tag for _, tag in cm.tag_tokens("इनपुट दिया टू द मशीन")]
    assert tags == ["hi", "hi", "en", "en", "hi"]
    # इन ("these"), आई ("came"), दे ("give") are Hindi words first.
    assert {tag for _, tag in cm.tag_tokens("इन लोगों ने दे दिया वो आई")} == {"hi"}


# --- matrix vs embedded language (T-1.16.2.2) ------------------------------------
def test_matrix_is_grammar_not_word_count():
    # 8 English words, 4 Hindi — but the auxiliary, the light verb and the
    # postposition are Hindi, so the sentence is Hindi with English nouns.
    a = cm.analyse_span("so basically the model ko train karna padta hai with the data")
    assert a["hi_share"] < 0.5
    assert a["matrix"] == "hi" and a["embedded"] == "en"


def test_the_users_example_is_english_matrix_with_hindi_embedded():
    a = cm.analyse_span(USER_EXAMPLE)
    assert (a["matrix"], a["embedded"]) == ("en", "hi")


def test_english_matrix_written_in_devanagari_is_recognised():
    a = cm.analyse_span("इट इज नॉट बीइंग एक्सप्लीसिटली प्रोग्राम")
    assert a["matrix"] == "en"


def test_monolingual_spans_have_no_embedded_language():
    assert cm.analyse_span("I want to go to the market")["embedded"] is None
    assert cm.analyse_span("mujhe nahi pata tha")["matrix"] == "hi"
    assert cm.analyse_span("2008 um ok")["matrix"] == "none"


def test_a_bare_noun_phrase_falls_back_to_word_majority():
    assert cm.analyse_span("machine learning course")["matrix"] == "en"
    assert cm.analyse_span("bahut badhiya video")["matrix"] == "hi"


def test_matrix_on_held_out_mixed_units_beats_word_majority():
    """N-002's claim, measured: on 62 held-out mixed units the system-morpheme
    vote names the grammar's language far more often than "whichever
    language has more words". Measured 2026-10-19: 0.952 vs 0.855 (LLM
    reference 0.968). Every baseline miss is a Hindi-grammar sentence with
    mostly English words, read as English. (The baseline reads 0.871 since
    every non-Latin script counts as non-English: one unit's kaomoji,
    "(ﾉ◕ヮ◕)ﾉ", now tips its word count — a spurious gain.)"""
    units = _test_units()
    vote = ev.matrix_accuracy(units, {u["id"]: cm.matrix_language(cm.tag_tokens(u["text"])) for u in units})
    def majority(text):
        p = cm.profile_text(text)
        return "hi" if p["hi_tokens"] > p["en_tokens"] else "en"
    base = ev.matrix_accuracy(units, {u["id"]: majority(u["text"]) for u in units})
    assert vote["units"] == base["units"] == 62
    assert vote["accuracy"] >= 0.93
    assert base["accuracy"] <= 0.88
    assert base["confusion"].get("hi->en", 0) >= 8


def _llm_cache() -> dict:
    return json.loads((ev.FIXTURE.parent / "llm_predictions.json").read_text(encoding="utf-8"))


def test_llm_detector_cached_answers_score_as_recorded():
    cache = _llm_cache()
    assert cache["model"] == "openai:gpt-5.6-luna:off"
    units = _test_units()
    pred = {
        u["id"]: [t for _, t in cm.spans_to_tags(u["text"], cache["predictions"][u["id"]]["hi"])[0]]
        for u in units
    }
    s = ev.score(units, pred)
    # Measured 2026-10-19 (held-out TEST): Latin token P 0.803 R 0.895,
    # Devanagari token P 0.964 R 0.966, no unit unanswered.
    assert s["missing_units"] == []
    assert 0.78 <= s["latin"]["token_hindi"]["precision"] <= 0.83
    assert s["devanagari"]["token_hindi"]["f1"] >= 0.95
    m = ev.matrix_accuracy(units, {k: v["matrix"] for k, v in cache["predictions"].items()})
    assert m["accuracy"] >= 0.95


# --- span mapping and the LLM payload -----------------------------------------------
def test_spans_map_contiguous_runs():
    tags, missed = cm.spans_to_tags(USER_EXAMPLE, ["taaki baadme koi kasar koi zarra na reh jaye", "hum jodte rahe cheezein"])
    assert missed == 0
    assert [t.text for t, tag in tags if tag == "hi"] == _hindi_words(USER_EXAMPLE)


def test_spans_with_english_words_dropped_still_map_and_leave_english_english():
    text = "विभागीय खोलेंगे तो वहां भी आपको उसी प्रोडक्ट से जुड़े विज्ञापन"
    span = ["खोलेंगे तो वहां भी आपको उसी से जुड़े विज्ञापन"]
    strict, missed = cm.spans_to_tags(text, span, max_gap=0)
    assert missed == 1
    tags, missed = cm.spans_to_tags(text, span)
    assert missed == 0
    by_word = {t.text: tag for t, tag in tags}
    assert by_word["प्रोडक्ट"] == "en" and by_word["उसी"] == "hi" and by_word["विभागीय"] == "en"


def test_repeated_word_is_marked_only_where_the_span_put_it():
    tags, _ = cm.spans_to_tags("to be or not to be, socho to sahi", ["socho to sahi"])
    assert [tag for _, tag in tags] == ["en"] * 6 + ["hi"] * 3


def test_unlocatable_span_is_counted_not_guessed():
    tags, missed = cm.spans_to_tags("mujhe nahi pata", ["mujhe pata nahin"])
    assert missed == 1
    assert all(tag == "en" for _, tag in tags)


def test_parse_llm_payload_tolerates_fences_and_marks_skipped_snippets():
    raw = '```json\n{"snippets": [{"i": 0, "hi": ["nahi pata"], "matrix": "hi"}, {"i": 2, "hi": [], "matrix": "EN"}]}\n```'
    out = cm.parse_llm_payload(raw, 3)
    assert out[0] == {"hi": ["nahi pata"], "matrix": "hi"}
    assert out[1] is None
    assert out[2] == {"hi": [], "matrix": "en"}
    assert cm.parse_llm_payload("not json", 2) is None
    assert cm.parse_llm_payload('{"snippets": [{"i": 9, "hi": []}]}', 2) == [None, None]


def test_llm_detect_batches_and_survives_a_failed_batch(monkeypatch):
    monkeypatch.setattr(cm, "LLM_BATCH_SIZE", 2)
    good = MagicMock()
    good.content = json.dumps({"snippets": [{"i": 0, "hi": ["nahi"], "matrix": "hi"},
                                            {"i": 1, "hi": [], "matrix": "en"}]})
    llm = MagicMock()
    llm.invoke.side_effect = [good, RuntimeError("provider down")]
    out = cm.llm_detect(["pata nahi", "hello there", "kya hua", "ok"], llm=llm)
    assert out[:2] == [{"hi": ["nahi"], "matrix": "hi"}, {"hi": [], "matrix": "en"}]
    assert out[2:] == [None, None]
    prompt = llm.invoke.call_args_list[0].args[0][0].content
    assert "[0] pata nahi" in prompt and "[1] hello there" in prompt
    assert "romanised" in prompt


# --- registry ---------------------------------------------------------------------------
def test_use_case_registered_with_reasoning_off_and_gating_nothing():
    from app.services import llm_smoke
    from app.services.llm_routing import USE_CASE_REGISTRY, resolve_config

    assert resolve_config("code_mixing_detect").reasoning == "off"
    assert USE_CASE_REGISTRY["code_mixing_detect"].typical_output_tokens < cm.LLM_MAX_COMPLETION_TOKENS
    gated = {uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs}
    assert "code_mixing_detect" not in gated


# --- rendering policy (T-1.16.2.3) ------------------------------------------------
def _a(share, matrix):
    return {"hi_share": share, "matrix": matrix}


def test_policy_modes_at_the_default_thresholds():
    assert cm.rendering_mode(_a(0.8, "hi")) == cm.NATIVE_SCRIPT     # Hindi-dominant
    assert cm.rendering_mode(_a(0.1, "en")) == cm.PLAIN_ENGLISH     # light borrowing
    assert cm.rendering_mode(_a(0.45, "en")) == cm.ROMAN            # heavy interleaving
    assert cm.rendering_mode(_a(0.33, "hi")) == cm.ROMAN            # English words in Hindi grammar
    assert cm.rendering_mode(_a(0.0, "en")) == cm.PLAIN_ENGLISH
    assert cm.rendering_mode(_a(0.0, "none")) == cm.PLAIN_ENGLISH


def test_matrix_gates_both_ends_of_the_scale():
    # A Hindi-grammar sentence is never "light borrowing"...
    assert cm.rendering_mode(_a(0.15, "hi")) == cm.ROMAN
    # ...and an English-grammar sentence is never shown in Devanagari.
    assert cm.rendering_mode(_a(0.9, "en")) == cm.ROMAN


def test_policy_on_real_spans():
    assert cm.rendering_mode(cm.analyse_span(USER_EXAMPLE)) == cm.ROMAN
    assert cm.rendering_mode(cm.analyse_span("thank you bhai you are the best")) == cm.PLAIN_ENGLISH
    assert cm.rendering_mode(cm.analyse_span("mujhe ye concept samajh nahi aaya yaar")) == cm.NATIVE_SCRIPT
    assert cm.rendering_mode(cm.analyse_span("We wanted to expect JSON formats")) == cm.PLAIN_ENGLISH


def test_thresholds_come_from_settings(monkeypatch):
    from app.config import settings

    a = _a(0.55, "hi")
    assert cm.rendering_mode(a) == cm.ROMAN
    monkeypatch.setattr(settings, "CODE_MIX_DOMINANT_SHARE", 0.5)
    assert cm.rendering_mode(a) == cm.NATIVE_SCRIPT
    b = _a(0.25, "en")
    assert cm.rendering_mode(b) == cm.ROMAN
    monkeypatch.setattr(settings, "CODE_MIX_BORROWING_MAX_SHARE", 0.3)
    assert cm.rendering_mode(b) == cm.PLAIN_ENGLISH
    # Explicit arguments win over settings.
    assert cm.rendering_mode(a, dominant=0.9) == cm.ROMAN


def test_policy_decisions_on_held_out_units_match_gold_decisions():
    """Measured 2026-10-19 at the defaults (0.6 / 0.2): the mode computed from
    the detector's analysis equals the mode computed from the labels for
    0.970 of Latin units and 0.823 of mixed units."""
    r = ev.policy_agreement(_test_units())
    assert r["agreement"]["latin"] >= 0.95
    assert r["agreement"]["mixed"] >= 0.80


def test_the_open_question_on_the_dominant_threshold_is_pinned():
    """D-080 records it: the tagger cannot see English nouns in Devanagari, so
    it overstates the Hindi share of Devanagari Hinglish, and a HIGHER
    dominant threshold flips more Devanagari decisions. Measured on TEST:
    0.912 agreement at 0.5, 0.824 at 0.6, 0.647 at 0.8. If this ever
    inverts, the detector changed and the default deserves a second look."""
    units = _test_units()
    by = {d: ev.policy_agreement(units, d, 0.2)["agreement"]["devanagari"] for d in (0.5, 0.6, 0.8)}
    assert by[0.5] > by[0.6] > by[0.8]


def test_known_limitation_unseen_names_count_as_hindi():
    """Out-of-vocabulary names look Hindi to the character n-gram model
    ("harry", "pranjali"), so a name adds a Hindi word to the share. The
    labels mark names as neither language and do not score them, so this
    costs nothing in the token scores; it shows up as policy flips on short
    spans. Pinned so a name-handling fix is noticed, not to endorse it."""
    a = cm.analyse_span("harry bhai you are the best")
    assert a["hi_tokens"] == 2
    assert cm.rendering_mode(a) == cm.ROMAN


# --- transcript-level primary language (T-1.16.2.4) -------------------------------
def test_windows_merge_caption_segments_into_sentence_sized_spans():
    segs = [{"text": "one two three four five"}] * 5          # 25 words
    wins = cm.transcript_windows(segs)
    assert [len(w.split()) for w in wins] == [15, 10]
    long = [{"text": " ".join(["w"] * 95)}]
    assert [len(w.split()) for w in cm.transcript_windows(long)] == [40, 40, 15]
    # A short tail joins the window before it rather than standing alone.
    assert [len(w.split()) for w in cm.transcript_windows("a " * 14)] == [14]
    assert cm.transcript_windows([]) == []


def test_flicker_counts_script_changes_between_quotable_windows_only():
    m = [cm.NATIVE_SCRIPT, cm.PLAIN_ENGLISH, cm.ROMAN, cm.ROMAN, cm.NATIVE_SCRIPT]
    assert cm.script_flicker(m) == 2
    assert cm.script_flicker([cm.PLAIN_ENGLISH] * 3) == 0


def _labelled_document(video_id: str) -> list[dict]:
    """A video's caption windows from the labelled set (not its comments)."""
    return [
        {"text": u["text"]} for u in ev.load_units()
        if u["video_id"] == video_id and u["source"].startswith("caption")
    ]


def test_a_devanagari_hinglish_lecture_is_hindi_primary_quoted_in_devanagari():
    p = cm.profile_transcript(_labelled_document("Y4qO9unerGs"))
    assert p["primary_language"] == "hi"
    assert p["native_script"] == "Devanagari"
    assert p["quote_mode"] == cm.NATIVE_SCRIPT


def test_an_indian_english_podcast_is_english_primary():
    p = cm.profile_transcript(_labelled_document("P24WbUcIwSk"))
    assert p["primary_language"] == "en"
    assert p["quote_mode"] == cm.PLAIN_ENGLISH


def test_a_bengali_transcript_is_not_passed_off_as_english():
    """Regression: before 2026-10-19 only Devanagari, Arabic and Gurmukhi
    words counted as non-English, so a Bengali transcript measured 0% and
    would have been quoted as plain English — the library holds two."""
    segs = [{"text": "আমরা আজকে মেশিন লার্নিং নিয়ে কথা বলব এবং দেখব কীভাবে এটা কাজ করে"}] * 3
    p = cm.profile_transcript(segs)
    assert p["primary_language"] == "other"
    assert p["native_script"] == "Bengali"
    assert p["hi_share"] == 1.0
    assert p["quote_mode"] == cm.NATIVE_SCRIPT


def test_romanised_hindi_primary_text_reports_latin_script():
    segs = [{"text": "mujhe lagta hai ki ye wala tarika sabse accha hai aur hum isko hi follow karenge"}] * 2
    p = cm.profile_transcript(segs)
    assert (p["primary_language"], p["native_script"]) == ("hi", "Latin")


def test_the_users_example_as_a_transcript():
    p = cm.profile_transcript(USER_EXAMPLE)
    assert p["primary_language"] == "en"
    assert p["quote_mode"] == cm.ROMAN


def test_resolution_lets_the_span_decide_english_and_the_transcript_decide_script():
    native_doc = {"quote_mode": cm.NATIVE_SCRIPT}
    roman_doc = {"quote_mode": cm.ROMAN}
    english_doc = {"quote_mode": cm.PLAIN_ENGLISH}
    # An English sentence in a Hindi talk is English.
    assert cm.resolve_quote_mode(cm.PLAIN_ENGLISH, native_doc) == cm.PLAIN_ENGLISH
    # Kept wording takes the transcript's script, whatever the span would pick.
    assert cm.resolve_quote_mode(cm.ROMAN, native_doc) == cm.NATIVE_SCRIPT
    assert cm.resolve_quote_mode(cm.NATIVE_SCRIPT, roman_doc) == cm.ROMAN
    # A Hindi clause in an English source stays in the Roman it was written in.
    assert cm.resolve_quote_mode(cm.NATIVE_SCRIPT, english_doc) == cm.ROMAN
    assert cm.resolve_quote_mode(cm.ROMAN, {}) == cm.ROMAN


def test_resolution_removes_the_flicker_a_per_quote_policy_would_produce():
    """Measured 2026-10-19 on the library's seven Devanagari Hinglish
    transcripts: 25 script changes quote by quote; on 11 YouTube comment
    threads, 128. After resolution every quote from a source shares one
    script."""
    doc = _labelled_document("O0jiCtwO-Ig") + _labelled_document("Y4qO9unerGs")
    p = cm.profile_transcript(doc)
    span_modes = [cm.rendering_mode(cm.analyse_span(w)) for w in cm.transcript_windows(doc)]
    resolved = [cm.resolve_quote_mode(m, p) for m in span_modes]
    assert cm.script_flicker(resolved) == 0
    assert {m for m in resolved if m != cm.PLAIN_ENGLISH} == {cm.NATIVE_SCRIPT}

"""R5 / D-066 — script profiling for code-mixed transcripts.

These pin both what the service guarantees and what it deliberately does not.
The honest boundary matters: script mixing is solved exactly, romanised
code-mixing (Hinglish in Latin letters) is NOT solvable here and is handled by
the prompt contract instead. A test asserting the gap keeps a future change
from quietly claiming otherwise.
"""
from app.services import language_service as ls


# --- exact cases ------------------------------------------------------------
def test_pure_english_needs_no_translation() -> None:
    t = "The model achieved 94% accuracy on the benchmark."
    assert ls.dominant_script(t) == "Latin"
    assert ls.needs_translation(t) is False
    assert ls.is_code_mixed(t) is False


def test_pure_devanagari_is_flagged_for_translation() -> None:
    t = "अहिंसा परमो धर्मः इति वेदेषु उक्तम्"
    assert ls.dominant_script(t) == "Devanagari"
    assert ls.needs_translation(t) is True


def test_script_level_code_mixing_is_detected() -> None:
    """The realistic Indian-speaker case: Hindi grammar, English nouns."""
    t = "मैंने deep learning का course complete किया है"
    assert ls.is_code_mixed(t) is True
    assert ls.needs_translation(t) is True


def test_arabic_latin_mixing_is_detected() -> None:
    t = "السلام عليكم and welcome to the show"
    prof = ls.script_profile(t)
    assert "Arabic" in prof and "Latin" in prof
    assert ls.is_code_mixed(t) is True


# --- the bug that mattered --------------------------------------------------
def test_combining_marks_count_toward_their_script() -> None:
    """Indic vowel signs are Mn/Mc, for which isalpha() is False. Counting only
    'letters' undercounted Devanagari by ~40% in a real sentence — enough to
    flip the dominant script to Latin and hide the language switch entirely."""
    t = "आज हम context engineering के बारे में बात करेंगे"
    prof = ls.script_profile(t)
    assert prof["Devanagari"] > prof["Latin"], "matras must count as Devanagari"
    assert ls.dominant_script(t) == "Devanagari"


# --- per-segment profile ----------------------------------------------------
def test_switch_points_locate_where_the_language_changes() -> None:
    """A per-video language label is a lie for a transcript that switches; the
    switch points are the thing that label cannot express."""
    segs = [
        {"text": "Welcome everyone to the session"},
        {"text": "आज हम इस विषय पर विस्तार से बात करेंगे"},
        {"text": "so the key idea is fairly simple"},
    ]
    p = ls.profile_segments(segs)
    assert p["switch_points"] == [1, 2]
    assert p["code_mixed"] is True
    assert 0 < p["non_latin_share"] < 1


def test_single_language_transcript_has_no_switch_points() -> None:
    segs = [{"text": "one two three"}, {"text": "four five six"}]
    p = ls.profile_segments(segs)
    assert p["switch_points"] == []
    assert p["dominant"] == "Latin"
    assert p["non_latin_share"] == 0.0


def test_empty_and_punctuation_only_inputs_are_safe() -> None:
    assert ls.script_profile("") == {}
    assert ls.script_profile("... --- 123 !!!") == {}
    assert ls.dominant_script("") is None
    assert ls.needs_translation("") is False
    p = ls.profile_segments([])
    assert p["dominant"] is None and p["switch_points"] == []


def test_segments_without_text_are_skipped_not_fatal() -> None:
    p = ls.profile_segments([{"text": ""}, {}, {"text": "hello world"}])
    assert p["dominant"] == "Latin"


# --- the documented limitation ---------------------------------------------
def test_romanised_code_mixing_is_NOT_detected_by_design() -> None:
    """Hinglish in Latin script is invisible to script analysis, and
    statistical detectors are weakest exactly here (short text, Hindi grammar,
    Latin characters). It is handled by the English-output prompt contract
    instead. If this ever starts passing, the module docstring and D-066 both
    need updating — do not just flip the assertion."""
    t = "mujhe ye concept samajh nahi aaya properly"
    assert ls.needs_translation(t) is False
    assert ls.dominant_script(t) == "Latin"


# --- prompt hand-off --------------------------------------------------------
def test_prompt_description_is_empty_for_english_sources() -> None:
    p = ls.profile_segments([{"text": "plain english content here"}])
    assert ls.describe_for_prompt(p) == ""


def test_prompt_description_names_the_scripts_for_mixed_sources() -> None:
    p = ls.profile_segments([{"text": "आज हम बात करेंगे about this topic"}])
    line = ls.describe_for_prompt(p)
    assert "Devanagari" in line
    assert "English" in line

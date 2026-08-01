"""Script and language profiling for transcripts — R5 / D-066.

WHAT THIS DOES AND DELIBERATELY DOES NOT DO
--------------------------------------------
The requirement asks for near-perfect language detection on speech that mixes
English, Urdu, Arabic, Persian and Hindi inside a single sentence while using
Hindi grammar. That decomposes into two very different problems:

1. **Different SCRIPTS in one text** (Devanagari + Latin, Arabic + Latin).
   Solved exactly here, by Unicode block analysis. No model, no dependency, no
   confidence score to tune — a Devanagari codepoint *is* Devanagari. This is
   the case that actually threatens the pipeline, because a Devanagari string
   flowing into extraction propagates untouched to the final report.

2. **Romanised code-mixing** — Hinglish written in Latin script ("mujhe ye
   samajh nahi aaya"). Script analysis cannot see this, and statistical
   detectors are at their *weakest* here: the text is short, the grammar is
   Hindi, and the character distribution is Latin. Rather than pretend a
   library solves it, this is handled at the PROMPT layer: the model reads the
   text and is instructed to emit English regardless of input language. The
   model is genuinely better at this than any detector we could bolt on.

So: exact where exactness is achievable, explicit about where it is not.
Storing a per-video language label as if it were the truth was the original
sin here — a 2-hour lecture that switches languages at minute 40 is not "hi".
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter

logger = logging.getLogger(__name__)

# Unicode block ranges -> ISO 15924 script codes, ordered most-specific first.
# Only scripts plausibly present in this corpus; anything else lands in "Other".
_SCRIPT_RANGES: tuple[tuple[str, int, int], ...] = (
    ("Latin", 0x0041, 0x024F),
    ("Greek", 0x0370, 0x03FF),
    ("Cyrillic", 0x0400, 0x04FF),
    ("Hebrew", 0x0590, 0x05FF),
    ("Arabic", 0x0600, 0x06FF),
    ("Arabic", 0x0750, 0x077F),      # Arabic Supplement (Urdu/Persian letters)
    ("Arabic", 0xFB50, 0xFDFF),      # Presentation Forms-A
    ("Devanagari", 0x0900, 0x097F),
    ("Bengali", 0x0980, 0x09FF),
    ("Gurmukhi", 0x0A00, 0x0A7F),
    ("Gujarati", 0x0A80, 0x0AFF),
    ("Tamil", 0x0B80, 0x0BFF),
    ("Telugu", 0x0C00, 0x0C7F),
    ("Kannada", 0x0C80, 0x0CFF),
    ("Malayalam", 0x0D00, 0x0D7F),
    ("Thai", 0x0E00, 0x0E7F),
    ("Han", 0x4E00, 0x9FFF),
    ("Hiragana", 0x3040, 0x309F),
    ("Katakana", 0x30A0, 0x30FF),
    ("Hangul", 0xAC00, 0xD7AF),
)

# A script needs at least this share of letters to count as present, so a
# stray emoji or one borrowed word does not flip a document's profile.
_PRESENCE_THRESHOLD = 0.05

# Below this share of non-Latin, treat the text as effectively English-script.
_LATIN_DOMINANT = 0.95


def script_of_char(ch: str) -> str | None:
    """ISO 15924-ish script name for one character, or None if not script-bearing.

    Combining marks count. Indic and Arabic scripts carry a large share of
    their content in vowel signs (Mn/Mc/Me categories), for which ``isalpha()``
    is False — counting only "letters" undercounted Devanagari by ~40% in a
    real code-mixed sentence, enough to flip the dominant script from
    Devanagari to Latin and hide a language switch entirely.
    """
    if not (ch.isalpha() or unicodedata.category(ch) in ("Mn", "Mc", "Me")):
        return None
    cp = ord(ch)
    for name, lo, hi in _SCRIPT_RANGES:
        if lo <= cp <= hi:
            return name
    # Anything script-bearing we did not enumerate — keep it visible rather
    # than silently folding it into Latin.
    try:
        return unicodedata.name(ch).split()[0].title()
    except ValueError:
        return "Other"


def script_profile(text: str) -> dict[str, float]:
    """Share of alphabetic characters per script. Empty dict for no letters."""
    if not text:
        return {}
    counts: Counter[str] = Counter()
    for ch in text:
        s = script_of_char(ch)
        if s:
            counts[s] += 1
    total = sum(counts.values())
    if not total:
        return {}
    return {k: v / total for k, v in counts.most_common()}


def dominant_script(text: str) -> str | None:
    prof = script_profile(text)
    return next(iter(prof), None) if prof else None


def is_code_mixed(text: str, threshold: float = _PRESENCE_THRESHOLD) -> bool:
    """Whether two or more scripts are meaningfully present.

    Detects script-level mixing only — romanised Hinglish reads as pure Latin
    and is handled by the prompt contract (see module docstring).
    """
    prof = script_profile(text)
    return sum(1 for share in prof.values() if share >= threshold) >= 2


def needs_translation(text: str) -> bool:
    """Whether this text contains enough non-Latin script to require an
    explicit translate-to-English step in downstream prompts."""
    prof = script_profile(text)
    if not prof:
        return False
    latin = prof.get("Latin", 0.0)
    return latin < _LATIN_DOMINANT


def profile_segments(segments: list[dict]) -> dict:
    """Language/script profile for a whole transcript, per segment and rolled up.

    Returns ``{scripts, dominant, code_mixed, non_latin_share,
    switch_points}``. ``switch_points`` are segment indices where the dominant
    script CHANGES — the thing a per-video label cannot express, and the reason
    a 2-hour lecture that switches at minute 40 was previously mislabelled.
    """
    if not segments:
        return {
            "scripts": {}, "dominant": None, "code_mixed": False,
            "non_latin_share": 0.0, "switch_points": [],
        }

    totals: Counter[str] = Counter()
    switch_points: list[int] = []
    prev: str | None = None
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "") if isinstance(seg, dict) else str(seg)
        prof = script_profile(text)
        if not prof:
            continue
        for k, share in prof.items():
            totals[k] += share
        top = next(iter(prof))
        if prev is not None and top != prev:
            switch_points.append(i)
        prev = top

    grand = sum(totals.values()) or 1.0
    scripts = {k: round(v / grand, 4) for k, v in totals.most_common()}
    non_latin = round(1.0 - scripts.get("Latin", 0.0), 4)
    return {
        "scripts": scripts,
        "dominant": next(iter(scripts), None),
        "code_mixed": sum(1 for s in scripts.values() if s >= _PRESENCE_THRESHOLD) >= 2,
        "non_latin_share": non_latin,
        "switch_points": switch_points[:200],   # bounded; only a signal
    }


def describe_for_prompt(profile: dict) -> str:
    """One line of context for a prompt, or empty when the source is plain
    English and nothing needs saying."""
    if not profile or not profile.get("scripts"):
        return ""
    if profile.get("non_latin_share", 0.0) < (1 - _LATIN_DOMINANT):
        return ""
    parts = ", ".join(
        f"{k} {share:.0%}" for k, share in list(profile["scripts"].items())[:4]
    )
    mixed = " The source switches script mid-transcript." if profile.get("switch_points") else ""
    return (
        f"SOURCE LANGUAGE: this transcript is not primarily English "
        f"({parts}).{mixed} Translate faithfully into English as instructed; "
        f"preserve original-script quotes per the quoting rules."
    )

"""Does a quotation trace back to its speaker's own words? — N-002 / T-1.18.8.4.

One definition, used twice:

- the report pipeline (`report_agent._verify_originals`) drops a map item's
  ``original`` wording that fails it, before anything is composed;
- `scripts/audit_quote_fidelity.py` (the R1 run-6 gate) audits replays with it.

So the pipeline keeps exactly what the gate passes. R1 run 5 (2026-10-19) is
why both exist: one map batch mixed eight channels and the model quoted a
Hindi speaker in Bengali — strings in no transcript — and spliced Bengali
letters into Devanagari words.

A quote PASSES against its own source's speech when every fragment (split on
an ellipsis, because elision is legitimate) is ``verbatim`` after
normalisation, or ``near``: at least ``NEAR`` of its characters align with
one stretch of the speech. "Near" is deliberate — the model regularises
caption spelling ("ম্যাটপ্লোটলিব এ" quoted as "ম্যাটপ্লটলিবে"), and an exact
check would drop real quotes. Two flags FAIL a quote whatever its match:
``mixed_script`` (a word mixing letters of two non-Latin scripts, which no
speaker produces and no caption contains — fuzzy alignment would otherwise
score it as near) and ``script_mismatch`` (its script differs from the
dominant non-Latin script of the speech). Normalisation is NFKC, lower-case,
native digits to ASCII, nukta and zero-width marks dropped, punctuation
(the danda included) to spaces.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

NEAR = 0.8
MIN_FRAGMENT_CHARS = 6

_NATIVE_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯", "01234567890123456789")
_DROP = {"़", "়", "‌", "‍", "﻿"}   # nukta (Deva, Beng), ZWNJ, ZWJ, BOM
_ELLIPSIS = re.compile(r"\.{3,}|…")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_NATIVE_DIGITS).lower()
    out = []
    for ch in t:
        if ch in _DROP:
            continue
        cat = unicodedata.category(ch)
        out.append(" " if cat[0] in "PSZC" else ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def script_of(ch: str) -> str | None:
    if not ch.isalpha() and unicodedata.category(ch) not in ("Mn", "Mc"):
        return None
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return None


def dominant_native_script(text: str) -> str | None:
    """Most frequent non-Latin script among letters, or None for Latin-only text."""
    counts = Counter(s for s in map(script_of, text or "") if s and s != "LATIN")
    return counts.most_common(1)[0][0] if counts else None


def mixed_script_words(text: str) -> list[str]:
    """Words whose letters come from two or more non-Latin scripts."""
    out = []
    for word in (text or "").split():
        scripts = {s for s in map(script_of, word) if s and s != "LATIN"}
        if len(scripts) > 1:
            out.append(word)
    return out


def fragments(quote: str) -> list[str]:
    parts = [normalise(p) for p in _ELLIPSIS.split(quote or "")]
    kept = [p for p in parts if len(p) >= MIN_FRAGMENT_CHARS]
    return kept or ([normalise(quote)] if normalise(quote) else [])


@dataclass
class VideoText:
    title: str
    speech: str          # normalised
    visual: str          # normalised
    script: str | None   # dominant non-Latin script of the raw speech
    _matcher: SequenceMatcher | None = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, title: str, speech: str, visual: str = "") -> "VideoText":
        return cls(title, normalise(speech), normalise(visual), dominant_native_script(speech))

    def _anchor(self, piece: str) -> int:
        """Where in the speech the fragment ``piece`` most plausibly starts."""
        if self._matcher is None:
            self._matcher = SequenceMatcher(None, autojunk=False)
            self._matcher.set_seq2(self.speech)
        self._matcher.set_seq1(piece)
        m = self._matcher.find_longest_match(0, len(piece), 0, len(self.speech))
        return m.b - m.a

    def coverage(self, fragment: str) -> float:
        """Share of the fragment's characters that align with one stretch of speech.

        Anchored on the longest common run of the whole fragment and of each
        half, so one common phrase elsewhere cannot hide the true location.
        """
        n = len(fragment)
        if not n or not self.speech:
            return 0.0
        half = n // 2
        anchors = {self._anchor(fragment)}
        if half >= MIN_FRAGMENT_CHARS:
            anchors.add(self._anchor(fragment[:half]))
            anchors.add(self._anchor(fragment[half:]) - half)
        best = 0.0
        for start in anchors:
            lo = max(0, start - n // 4)
            window = self.speech[lo:lo + n + n // 2]
            sm = SequenceMatcher(None, fragment, window, autojunk=False)
            best = max(best, sum(b.size for b in sm.get_matching_blocks()) / n)
        return best


def match_level(frags: list[str], haystack: str, video: VideoText | None = None) -> str | None:
    """"verbatim", "near" (needs ``video`` for alignment), or None."""
    if not frags or not haystack:
        return None
    if all(f in haystack for f in frags):
        return "verbatim"
    if video is not None and all(video.coverage(f) >= NEAR for f in frags):
        return "near"
    return None


def problem(quote: str, own: VideoText | None) -> str | None:
    """Why ``quote`` cannot stand as its own source's words, or None if it can.

    One of ``mixed_script``, ``script_mismatch``, ``no_source``,
    ``not_in_speech``.
    """
    if mixed_script_words(quote):
        return "mixed_script"
    if own is None:
        return "no_source"
    q_script = dominant_native_script(quote)
    if q_script and own.script and q_script != own.script:
        return "script_mismatch"
    if match_level(fragments(quote), own.speech, own) is None:
        return "not_in_speech"
    return None


def merge_chunk_texts(texts: Iterable[str]) -> str:
    """Rebuild one source's text from its ordered chunks, dropping the overlap.

    Concatenating overlapping chunks would duplicate the overlap; the longest
    suffix of the text so far that equals a prefix of the next chunk
    (word-level) is removed instead.
    """
    words: list[str] = []
    for text in texts:
        w = (text or "").split()
        overlap = 0
        for n in range(min(len(words), len(w), 300), 0, -1):
            if words[-n:] == w[:n]:
                overlap = n
                break
        words.extend(w[overlap:])
    return " ".join(words)

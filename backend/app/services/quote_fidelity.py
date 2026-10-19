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
import threading
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
    _matcher: SequenceMatcher | None = field(default=None, repr=False, compare=False)
    # S-1.14.19: report map batches run concurrently and share one VideoText
    # per source, so the cached matcher's set_seq1 + find_longest_match pair
    # must not interleave across threads (it raised IndexError or anchored
    # one thread's fragment with another's sequence).
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def from_raw(cls, title: str, speech: str, visual: str = "") -> "VideoText":
        return cls(title, normalise(speech), normalise(visual), dominant_native_script(speech))

    def _anchor(self, piece: str) -> int:
        """Where in the speech the fragment ``piece`` most plausibly starts."""
        with self._lock:
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


# --- the speaker's words inside an over-full `original` ---------------------------
#
# With one source per map call (S-1.14.19), the model often writes N-002's
# whole quote form into `original`: the speech, then a transliteration line,
# then an English translation, sometimes with an inline gloss ("সি-বর্ন
# ( Seaborn)"). The speech is real; the added Latin lines push the alignment
# under NEAR and the quote is dropped. R1 run 7 lost 68 of 176 originals that
# way, all from the Bengali source. These readings are retried before an
# original is given up on — each still has to pass `problem` in full.

_LATIN_GLOSS = re.compile(r"\s*\(\s*[A-Za-z][^()]*\)")


def speaker_words(original: str, script: str | None) -> tuple[str, str]:
    """The lines of ``original`` in the source's own script, and the rest.

    ``("", original)`` when no line is in that script; ``(original, "")``
    when the source has no native script (romanised or English speech), since
    a transliteration line cannot then be told apart from the speech.
    """
    if not script:
        return original, ""
    lines = [ln.strip() for ln in (original or "").splitlines() if ln.strip()]
    keep = [ln for ln in lines if dominant_native_script(ln) == script]
    rest = [ln for ln in lines if dominant_native_script(ln) != script]
    return "\n".join(keep), "\n".join(rest)


def strip_unspoken_glosses(text: str, own: VideoText) -> tuple[str, str]:
    """``text`` without parenthesised Latin glosses the speaker did not say.

    A gloss the caption itself carries ("সি-বর্ন ( Seaborn)") is speech and
    stays; one the model added ("ইনস্টল (install it)") goes.
    """
    removed: list[str] = []

    def drop(m: re.Match) -> str:
        gloss = normalise(m.group(0))
        if gloss and gloss in own.speech:
            return m.group(0)
        removed.append(m.group(0).strip())
        return ""

    out = _LATIN_GLOSS.sub(drop, text or "")
    return re.sub(r"[ \t]{2,}", " ", out).strip(), " ".join(removed)


def keepable(original: str, own: VideoText | None) -> tuple[str | None, str, str | None]:
    """``(reading to keep, text removed from it, None)`` or ``(None, "", reason)``.

    The reading is ``original`` itself when it passes, minus any gloss the
    speaker did not say. When it fails as ``not_in_speech`` and the source has
    a native script, the lines in that script are retried (the model wrote
    speech + transliteration + translation into the field). Every reading must
    still pass ``problem`` in full, so nothing invented is ever rescued.
    """
    reason = problem(original, own)
    if own is None or not own.script:
        return (original, "", None) if reason is None else (None, "", reason)
    if reason is None:
        candidates = [(original, "")]
    elif reason == "not_in_speech":
        words, rest = speaker_words(original, own.script)
        if not words:
            return None, "", reason
        candidates = [(words, rest)]
    else:
        return None, "", reason
    for text, removed in candidates:
        stripped, glosses = strip_unspoken_glosses(text, own)
        for reading, gone in ((stripped, "\n".join(x for x in (removed, glosses) if x)), (text, removed)):
            if reading and problem(reading, own) is None:
                return reading, gone, None
    return None, "", reason

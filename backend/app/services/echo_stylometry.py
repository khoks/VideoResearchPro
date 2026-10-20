"""Stylometry with no model (S-3.3.2 layer 1, and S-3.3.4's automatic tier).

How someone writes, measured from the text alone: sentence length,
punctuation habits, function-word rates and character trigrams. All of it
is language-agnostic except the function-word list, which is the closed
English and Hindi classes ``code_mixing_service`` already keeps (Roman and
Devanagari), so a Hinglish note is measured as Hinglish rather than as
English with typos.

Two uses:

- ``cadence_signals``: a handful of plain descriptions ("Writes in short
  sentences", "Asks questions often") the signals panel shows, each with the
  user's own sentences as examples. Thresholds are deliberately coarse so a
  signal does not flicker between runs.
- ``similarity``: how close two profiles are (cosine over function-word and
  character-trigram rates). The voice-match harness scores a draft against
  the user's held-out texts with it. Burrows' Delta needs a reference corpus
  for its z-scores; cosine over relative frequencies needs none and stays
  usable on the short texts a single user has.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from app.services.code_mixing_service import (
    ENGLISH_FUNCTION_MORPHEMES,
    ENGLISH_VERBAL_MORPHEMES,
    HINDI_FUNCTION_MORPHEMES,
    HINDI_VERBAL_MORPHEMES,
)

FUNCTION_WORDS: frozenset[str] = frozenset(
    ENGLISH_FUNCTION_MORPHEMES | ENGLISH_VERBAL_MORPHEMES | HINDI_FUNCTION_MORPHEMES | HINDI_VERBAL_MORPHEMES
)

#: Below this much text in one language, no cadence signal is emitted: a
#: rate measured on a few sentences is noise.
MIN_SENTENCES = 20
MIN_WORDS = 300

_SENTENCE_END = re.compile(r"(?<=[.!?।…])\s+|\n+")
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
_MARKDOWN = re.compile(r"(^|\s)[#>*_`~-]+|\[([^\]]*)\]\([^)]*\)")

PUNCTUATION = {
    "question": "?",
    "exclamation": "!",
    "ellipsis": "…",
    "dash": "—",
    "parenthesis": "(",
    "semicolon": ";",
    "colon": ":",
}


def plain(text: str) -> str:
    """Markdown markers off, link text kept: notes are Markdown."""
    t = _MARKDOWN.sub(lambda m: (m.group(1) or "") + (m.group(2) or ""), text or "")
    return t.replace("...", "…").replace(" -- ", " — ").replace(" - ", " — ")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(plain(text)) if s and len(_WORD.findall(s)) >= 2]


def raw_sentences(text: str) -> list[str]:
    """Sentences as the user wrote them (Markdown and all), for examples:
    an example must be the user's exact words."""
    return [s.strip() for s in _SENTENCE_END.split(text or "") if s and len(_WORD.findall(s)) >= 2]


def words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text)]


@dataclass
class StyleProfile:
    """Counts, not rates, so profiles add up across texts."""

    n_chars: int = 0
    n_words: int = 0
    n_sentences: int = 0
    sentence_lengths: list[int] = field(default_factory=list)
    lowercase_starts: int = 0
    punctuation: Counter = field(default_factory=Counter)
    sentences_with: Counter = field(default_factory=Counter)
    emoji: int = 0
    function_words: Counter = field(default_factory=Counter)
    trigrams: Counter = field(default_factory=Counter)

    def add(self, other: "StyleProfile") -> "StyleProfile":
        self.n_chars += other.n_chars
        self.n_words += other.n_words
        self.n_sentences += other.n_sentences
        self.sentence_lengths.extend(other.sentence_lengths)
        self.lowercase_starts += other.lowercase_starts
        self.punctuation.update(other.punctuation)
        self.sentences_with.update(other.sentences_with)
        self.emoji += other.emoji
        self.function_words.update(other.function_words)
        self.trigrams.update(other.trigrams)
        return self

    @property
    def mean_sentence_words(self) -> float:
        return sum(self.sentence_lengths) / len(self.sentence_lengths) if self.sentence_lengths else 0.0

    def share_of_sentences(self, habit: str) -> float:
        return self.sentences_with[habit] / self.n_sentences if self.n_sentences else 0.0

    def to_json(self) -> dict:
        """Compact form for the input ledger (top trigrams only)."""
        return {
            "n_chars": self.n_chars,
            "n_words": self.n_words,
            "n_sentences": self.n_sentences,
            "sentence_lengths": self.sentence_lengths[:400],
            "lowercase_starts": self.lowercase_starts,
            "punctuation": dict(self.punctuation),
            "sentences_with": dict(self.sentences_with),
            "emoji": self.emoji,
            "function_words": dict(self.function_words),
            "trigrams": dict(self.trigrams.most_common(300)),
        }

    @classmethod
    def from_json(cls, data: dict) -> "StyleProfile":
        return cls(
            n_chars=int(data.get("n_chars", 0)),
            n_words=int(data.get("n_words", 0)),
            n_sentences=int(data.get("n_sentences", 0)),
            sentence_lengths=[int(x) for x in data.get("sentence_lengths", [])],
            lowercase_starts=int(data.get("lowercase_starts", 0)),
            punctuation=Counter(data.get("punctuation", {})),
            sentences_with=Counter(data.get("sentences_with", {})),
            emoji=int(data.get("emoji", 0)),
            function_words=Counter(data.get("function_words", {})),
            trigrams=Counter(data.get("trigrams", {})),
        )


def profile(text: str) -> StyleProfile:
    body = plain(text)
    p = StyleProfile(n_chars=len(body))
    for s in sentences(body):
        ws = words(s)
        p.n_sentences += 1
        p.sentence_lengths.append(len(ws))
        first = s.lstrip("\"'“‘(")[:1]
        if first.isalpha() and first.islower():
            p.lowercase_starts += 1
        for habit, mark in PUNCTUATION.items():
            count = s.count(mark)
            if count:
                p.punctuation[habit] += count
                p.sentences_with[habit] += 1
        if _EMOJI.search(s):
            p.sentences_with["emoji"] += 1
    all_words = words(body)
    p.n_words = len(all_words)
    p.function_words.update(w for w in all_words if w in FUNCTION_WORDS)
    p.emoji = len(_EMOJI.findall(body))
    squashed = " ".join(all_words)
    p.trigrams.update(squashed[i : i + 3] for i in range(max(0, len(squashed) - 2)))
    return p


def combine(profiles: Iterable[StyleProfile]) -> StyleProfile:
    total = StyleProfile()
    for p in profiles:
        total.add(p)
    return total


# ---------------------------------------------------------------------------
# Similarity


def _cosine(a: Counter, b: Counter, na: float, nb: float) -> float:
    if not a or not b or not na or not nb:
        return 0.0
    keys = set(a) | set(b)
    va = [a.get(k, 0) / na for k in keys]
    vb = [b.get(k, 0) / nb for k in keys]
    dot = sum(x * y for x, y in zip(va, vb))
    norm = math.sqrt(sum(x * x for x in va)) * math.sqrt(sum(y * y for y in vb))
    return dot / norm if norm else 0.0


def similarity(a: StyleProfile, b: StyleProfile) -> float:
    """0..1: half function-word cosine, half character-trigram cosine."""
    fw = _cosine(a.function_words, b.function_words, a.n_words, b.n_words)
    tri = _cosine(a.trigrams, b.trigrams, sum(a.trigrams.values()), sum(b.trigrams.values()))
    return round(0.5 * fw + 0.5 * tri, 4)


# ---------------------------------------------------------------------------
# Cadence signals


@dataclass(frozen=True)
class CadenceSignal:
    value: str
    #: Habit name, used to pick example sentences.
    habit: str


def _length_signal(mean: float) -> CadenceSignal:
    if mean < 12:
        return CadenceSignal("Writes in short sentences (under 12 words on average)", "short")
    if mean <= 20:
        return CadenceSignal("Writes in medium-length sentences (12 to 20 words on average)", "medium")
    return CadenceSignal("Writes in long sentences (over 20 words on average)", "long")


#: (habit, share of sentences at or above which it is a signal, wording).
#: Heuristics, not calibrated values: each floor is roughly three times the
#: habit's rate in ordinary prose (questions run about 2-5% of sentences),
#: so a signal means "noticeably more than most writers".
HABITS: tuple[tuple[str, float, str], ...] = (
    ("question", 0.15, "Asks questions often (more than one sentence in seven)"),
    ("exclamation", 0.10, "Uses exclamation marks often"),
    ("ellipsis", 0.08, "Trails off with ellipses"),
    ("dash", 0.12, "Uses dashes for asides"),
    ("parenthesis", 0.10, "Adds asides in parentheses"),
    ("emoji", 0.08, "Uses emoji"),
)


def cadence_signals(p: StyleProfile) -> list[CadenceSignal]:
    """What this much text says about the writer's cadence, or nothing when
    there is too little of it."""
    if p.n_sentences < MIN_SENTENCES or p.n_words < MIN_WORDS:
        return []
    out = [_length_signal(p.mean_sentence_words)]
    for habit, floor, wording in HABITS:
        if p.share_of_sentences(habit) >= floor:
            out.append(CadenceSignal(wording, habit))
    if p.lowercase_starts / p.n_sentences >= 0.5:
        out.append(CadenceSignal("Often starts sentences in lowercase", "lowercase"))
    return out


def exhibits(sentence: str, habit: str, mean: float) -> bool:
    """Does this sentence show the habit? Picks the examples."""
    n = len(words(sentence))
    if habit == "short":
        return 3 <= n < 12
    if habit == "medium":
        return 12 <= n <= 20
    if habit == "long":
        return n > 20
    if habit == "lowercase":
        first = sentence.lstrip("\"'“‘(")[:1]
        return first.isalpha() and first.islower()
    if habit == "emoji":
        return bool(_EMOJI.search(sentence))
    mark = PUNCTUATION.get(habit)
    return bool(mark and mark in sentence)

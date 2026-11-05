"""Turn a research topic into what a keyword search can answer (S-1.5.14).

A topic is written for a person: "Why did the Roman Empire fall and what can
we learn from it today?". YouTube's search takes that, but Hacker News,
Bluesky and Mastodon match every word, or one hashtag, and answer nothing
(T-1.5.14.2). No LLM here: a connector runs at the search phase of every run,
and the words that carry a topic can be found without one.

The topic as written always goes first. A topic that works today costs the
one request it always cost and gets the same answer, so a mistake in the word
list below can only touch a run that was going to find nothing.

Also used to tell whether a podcast episode is about the topic
(T-1.7.1.3), from what its feed already says.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable

_APOSTROPHES = "'’"

# English function words and question words, then the words a research
# question is phrased with. Other languages keep every word: the topic as
# written still goes first, and nothing here reads Hindi.
_STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren't as at
    be because been before being below between both but by can can't cannot
    could couldn't did didn't do does doesn't doing don't down during each even
    ever few for from further get gets getting got had hadn't has hasn't have
    haven't having he her here hers herself him himself his how i if in into is
    isn't it it's its itself just let's like many may me might more most much
    must my myself no nor not of off on once one only or other ought our ours
    ourselves out over own really same shall she should shouldn't so some such
    than that the their theirs them themselves then there these they this those
    through to too under until up upon us use used using very via versus vs was
    wasn't we were weren't what what's when where which while who whom whose why
    will with within without won't would wouldn't you your yours yourself
    yourselves

    actually analysis best better compare comparison currently discuss
    discussion effect effects explain explained explanation future give good
    guide happen happened happens impact impacts introduction know latest learn
    learned nowadays ones overview people recent recently review role show summary
    tell things think today understanding way ways
    """.split()
)

# Enough to reach the shortest phrase below, however the topic is worded.
MAX_QUERIES = 4


def _words(text: str) -> list[str]:
    """The words of ``text``, in order.

    Goes by Unicode category, as ``_topic_to_hashtag`` does: ``str.isalnum``
    rejects combining marks, and would cut a Devanagari word at every vowel
    sign. An apostrophe stays inside a word, so "don't" stays one stopword,
    and a possessive 's goes ("Rome's" is "Rome").
    """
    words: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        word = "".join(current).strip(_APOSTROPHES)
        current.clear()
        if word[-2:].lower() in ("'s", "’s"):
            word = word[:-2]
        if word:
            words.append(word)

    for ch in text or "":
        if unicodedata.category(ch)[0] in ("L", "N", "M") or (ch in _APOSTROPHES and current):
            current.append(ch)
        else:
            flush()
    flush()
    return words


def _is_stopword(word: str) -> bool:
    return word.casefold().replace("’", "'") in _STOPWORDS


def topic_terms(topic: str) -> list[str]:
    """The words that carry the topic, in order, without repeats.

    A topic made only of stopwords ("The Who") keeps them all: they are the
    topic.
    """
    words = _words(topic)
    kept = [w for w in words if not _is_stopword(w)] or words
    return _unique(kept)


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def topic_queries(topic: str) -> list[str]:
    """Queries to try in order, stopping at the first that finds something.

    The topic as written, then its carrying words, then the first three and
    the first two of those. Two is the floor: one word of a phrase matches
    too much to be about the topic ("Empire"). Measured on 2026-11-04: the
    sentence above found nothing on Hacker News or Bluesky, and neither did
    "Roman Empire fall learn today"; "Roman Empire fall" found 30 and 5.
    """
    written = (topic or "").strip()
    if not written:
        return []
    terms = topic_terms(written)
    return _unique([written, " ".join(terms), " ".join(terms[:3]), " ".join(terms[:2])])[:MAX_QUERIES]


def _term_key(word: str) -> str:
    """One word's form for comparing: case folded, a plural's "s" gone, so
    "Plants" and "plant" are the same word. Long enough to leave "gas" and
    "news" alone, and "ss" stays ("loss")."""
    key = word.casefold()
    if len(key) > 4 and key.endswith("s") and not key.endswith("ss"):
        return key[:-1]
    return key


def term_keys(text: str) -> set[str]:
    """Every word of ``text``, ready to compare with ``topic_keys``."""
    return {_term_key(w) for w in _words(text)}


def topic_keys(topic: str) -> set[str]:
    """The topic's carrying words, ready to compare with ``term_keys``."""
    return {_term_key(t) for t in topic_terms(topic)}

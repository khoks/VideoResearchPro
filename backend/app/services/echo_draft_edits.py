"""What the user changed in a "speak as me" draft (S-3.4.2), as words.

The provenance guard reads this module: only the words the user TYPED are
their writing. A draft is the model's text, and the words of it the user kept
were still written by the model, so they never feed the user's voice; Echo
learning from them would be Echo learning from itself. What the user cut is
kept as evidence of what they would not say, but it is not their words
either, so it never becomes an example.

Typed words are not always the user's own either. A reply often repeats the
message it answers ("you say the tariff will bring every job back, but…"),
and those words are the sender's. S-3.4.1's verbatim guard applies here too:
any stretch of ``echo_agent.VERBATIM_WORDS`` words the user's version shares
with a third-party passage (the incoming message) is set aside as ``quoted``,
even when the user typed it, and never becomes their voice. The stretch is
found over the whole version, so a quote that runs across draft words the
user kept is caught as well.

Words are compared on a folded form (case and surrounding punctuation
ignored), so "pays." to "pays!" or a capital letter is not a change the user
wrote. Each run is sliced from the final text as the user typed it.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Iterable

_WORD = re.compile(r"\S+")
_EDGE = re.compile(r"^\W+|\W+$", re.UNICODE)


@dataclass(frozen=True)
class EditDiff:
    #: Runs the user typed (inserted, or replacing draft words), verbatim,
    #: minus anything quoted from a third party: what may teach their voice.
    written: list[str] = field(default_factory=list)
    #: Runs of the draft the user cut or replaced.
    removed: list[str] = field(default_factory=list)
    #: Typed runs that repeat a third-party passage (the incoming message).
    quoted: list[str] = field(default_factory=list)
    kept_words: int = 0

    @property
    def written_words(self) -> int:
        return sum(len(r.split()) for r in self.written)

    @property
    def removed_words(self) -> int:
        return sum(len(r.split()) for r in self.removed)

    @property
    def quoted_words(self) -> int:
        return sum(len(r.split()) for r in self.quoted)

    def summary(self) -> dict:
        return {"written_words": self.written_words, "removed_words": self.removed_words,
                "quoted_words": self.quoted_words, "kept_words": self.kept_words}


def _fold(word: str) -> str:
    core = _EDGE.sub("", word).casefold()
    return core or word.casefold()


def _spans(text: str) -> list[re.Match]:
    return list(_WORD.finditer(text or ""))


def _verbatim_words() -> int:
    from app.agents.echo_agent import VERBATIM_WORDS

    return VERBATIM_WORDS


def _quoted_mask(keys: list[str], passages: Iterable[str], n: int) -> list[bool]:
    """For each word of the version: is it inside an ``n``-word stretch the
    version shares with any passage?"""
    theirs: set[tuple[str, ...]] = set()
    for p in passages:
        k = [_fold(m.group()) for m in _spans(p)]
        theirs |= {tuple(k[i: i + n]) for i in range(len(k) - n + 1)}
    mask = [False] * len(keys)
    if not theirs:
        return mask
    for i in range(len(keys) - n + 1):
        if tuple(keys[i: i + n]) in theirs:
            for j in range(i, i + n):
                mask[j] = True
    return mask


def edit_diff(draft: str, final: str, *, third_party: Iterable[str] = (), n: int | None = None) -> EditDiff:
    a, b = _spans(draft), _spans(final)
    keys_b = [_fold(m.group()) for m in b]
    quoted_at = _quoted_mask(keys_b, [p for p in third_party if p], n or _verbatim_words())
    sm = difflib.SequenceMatcher(a=[_fold(m.group()) for m in a], b=keys_b, autojunk=False)
    written: list[str] = []
    removed: list[str] = []
    quoted: list[str] = []
    kept = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            kept += i2 - i1
            continue
        if tag in ("replace", "delete") and i2 > i1:
            removed.append(draft[a[i1].start(): a[i2 - 1].end()])
        if tag in ("replace", "insert"):
            j = j1
            while j < j2:
                k = j
                while k < j2 and quoted_at[k] == quoted_at[j]:
                    k += 1
                (quoted if quoted_at[j] else written).append(final[b[j].start(): b[k - 1].end()])
                j = k
    return EditDiff(written=written, removed=removed, quoted=quoted, kept_words=kept)


def strip_disclosure(final: str, disclosure: str | None) -> str:
    """The disclosure line is Echo's, not the user's: a final text pasted back
    with it attached is read without it."""
    text = (final or "").strip()
    d = (disclosure or "").strip()
    if d and text.endswith(d):
        text = text[: -len(d)].rstrip(" \t\r\n—–-")
    return text


def user_written_text(draft: str, final: str | None, *, min_words: int, third_party: Iterable[str] = ()) -> str:
    """The user's own words in an edited draft, one run per line, or "" when
    there are fewer than ``min_words`` of them (or no edit at all)."""
    if not final:
        return ""
    diff = edit_diff(draft, final, third_party=third_party)
    if diff.written_words < max(1, min_words):
        return ""
    return "\n".join(diff.written)

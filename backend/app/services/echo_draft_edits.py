"""What the user changed in a "speak as me" draft (S-3.4.2), as words.

The provenance guard reads this module: only the words the user TYPED are
their writing. A draft is the model's text, and the words of it the user kept
were still written by the model, so they never feed the user's voice; Echo
learning from them would be Echo learning from itself. What the user cut is
kept as evidence of what they would not say, but it is not their words
either, so it never becomes an example.

Words are compared on a folded form (case and surrounding punctuation
ignored), so "pays." to "pays!" or a capital letter is not a change the user
wrote. Each written run is sliced from the final text as the user typed it.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

_WORD = re.compile(r"\S+")
_EDGE = re.compile(r"^\W+|\W+$", re.UNICODE)


@dataclass(frozen=True)
class EditDiff:
    #: Runs the user typed (inserted, or replacing draft words), verbatim.
    written: list[str] = field(default_factory=list)
    #: Runs of the draft the user cut or replaced.
    removed: list[str] = field(default_factory=list)
    kept_words: int = 0

    @property
    def written_words(self) -> int:
        return sum(len(r.split()) for r in self.written)

    @property
    def removed_words(self) -> int:
        return sum(len(r.split()) for r in self.removed)

    def summary(self) -> dict:
        return {"written_words": self.written_words, "removed_words": self.removed_words, "kept_words": self.kept_words}


def _fold(word: str) -> str:
    core = _EDGE.sub("", word).casefold()
    return core or word.casefold()


def _spans(text: str) -> list[re.Match]:
    return list(_WORD.finditer(text or ""))


def edit_diff(draft: str, final: str) -> EditDiff:
    a, b = _spans(draft), _spans(final)
    sm = difflib.SequenceMatcher(a=[_fold(m.group()) for m in a], b=[_fold(m.group()) for m in b], autojunk=False)
    written: list[str] = []
    removed: list[str] = []
    kept = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            kept += i2 - i1
            continue
        if tag in ("replace", "insert") and j2 > j1:
            written.append(final[b[j1].start(): b[j2 - 1].end()])
        if tag in ("replace", "delete") and i2 > i1:
            removed.append(draft[a[i1].start(): a[i2 - 1].end()])
    return EditDiff(written=written, removed=removed, kept_words=kept)


def strip_disclosure(final: str, disclosure: str | None) -> str:
    """The disclosure line is Echo's, not the user's: a final text pasted back
    with it attached is read without it."""
    text = (final or "").strip()
    d = (disclosure or "").strip()
    if d and text.endswith(d):
        text = text[: -len(d)].rstrip(" \t\r\n—–-")
    return text


def user_written_text(draft: str, final: str | None, *, min_words: int) -> str:
    """The user's own words in an edited draft, one run per line, or "" when
    there are fewer than ``min_words`` of them (or no edit at all)."""
    if not final:
        return ""
    diff = edit_diff(draft, final)
    if diff.written_words < max(1, min_words):
        return ""
    return "\n".join(diff.written)

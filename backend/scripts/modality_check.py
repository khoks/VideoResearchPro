"""Deterministic check that a report's spoken and on-screen attributions match their evidence (S-1.18.7). Research tool, not wired into the pipeline: see D-075 for why.

R1 (D-067) merges frame descriptions into transcripts as ``[VISUAL @ mm:ss — …]``
spans. Prompt rules alone did not keep the two channels apart. Across three
measured runs (D-071, D-075), the composer first credited speakers with
screen-only details; once told not to, it began claiming the screen showed
things that were only spoken. The errors moved with the wording; they did not
go away.

This module checks the finished report against the evidence instead of asking
the model to behave. It is pure: callers pass the report HTML and, per video,
the timestamped speech and the timestamped visual descriptions. There are three
kinds of finding:

``screen_claim_without_span``
    A clause says something is on screen at a moment with no visual
    description nearby.
``speech_presented_as_screen``
    A clause says something is on screen and a description exists nearby, but
    the clause's specific details occur only in the speech around that moment.
``screen_detail_attributed_to_speaker``
    A sentence credits a speaker ("X says / lists / reports …") with specific
    details that occur only in a nearby visual description.

"Specific detail" means a token a reader could check: numbers (native digits
are normalised, so Bengali ০.১৩.২ matches 0.13.2), code-like identifiers,
quoted strings, and pairs of content words. Ordinary prose is ignored. The
check is script-aware: where the nearby speech is mostly non-Latin, only
numbers are compared, because a word or identifier spoken in Devanagari or
Bengali cannot be matched against an English sentence, and its apparent
absence proves nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


@dataclass
class Evidence:
    """Timestamped evidence for one video."""

    speech: list[tuple[float, str]] = field(default_factory=list)   # (start_seconds, text)
    visual: list[tuple[float, str]] = field(default_factory=list)   # (timestamp_seconds, description)

    def speech_text(self, lo: float, hi: float) -> str:
        return " ".join(t for s, t in self.speech if lo <= s <= hi)

    def visual_text(self, lo: float, hi: float) -> str:
        return " ".join(t for s, t in self.visual if lo <= s <= hi)

    def has_visual(self, lo: float, hi: float) -> bool:
        return any(lo <= s <= hi for s, _ in self.visual)


@dataclass
class Finding:
    kind: str
    sentence: str
    video_id: str
    seconds: float
    tokens: list[str]
    detail: str = ""


@dataclass
class Windows:
    """Seconds around a cited moment.

    ``explicit`` applies when the sentence names the time ("at 10:45").
    ``link_before``/``link_after`` apply when only a citation link gives it:
    links usually point at a chunk start, and the frame can sit later in that
    chunk. ``speech`` is deliberately wide, because a speaker may have said a
    detail a minute before the cited moment, and absence from speech is the
    claim under test.
    """

    explicit: float = 20.0
    link_before: float = 20.0
    link_after: float = 120.0
    speech: float = 90.0
    # How many screen-only details make a speaker-attributed sentence a finding.
    speaker_strong: int = 1
    speaker_weak: int = 1
    trailing_strong: int = 1
    trailing_weak: int = 2


# --------------------------------------------------------------------------
# Normalisation and tokens
# --------------------------------------------------------------------------

_NATIVE_DIGITS = str.maketrans(
    "০১২৩৪৫৬৭৮৯०१२३४५६७८९٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "0123456789" * 4,
)
_STOP = frozenset(
    """a an the and or of to in on at by for with from as is are was were be been being it its this that these those
    which who whom whose what when where how than then there here their they them he she his her we our you your
    i me my not no but if so such also only very more most less least can could would should may might will shall
    do does did done has have had into over under about after before between through during each every all any some
    one two three first second same other both either neither own just still even again further while because
    video videos tutorial speaker presenter instructor channel screen frame chart plot shows show shown says said
    notes explains states lists reports mentions example examples using uses used""".split()
)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)*(?![\w])")
_IDENT = re.compile(r"`([^`]{2,60})`|\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+|[a-z0-9]+_[a-z0-9_]+)\b")
_QUOTED = re.compile(r"[\"“]([^\"”]{3,80})[\"”]")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])")
_TRAILING_ATTRIBUTION = re.compile(r"[—–]\s*[^—–\n]{2,160}\(\s*\d{1,2}:\d{2}(?::\d{2})?\s*\)\s*\.?\s*$")
_TITLE_TAIL = re.compile(r"\s[—–]\s.*$")


def normalise(text: str) -> str:
    t = (text or "").translate(_NATIVE_DIGITS).lower()
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)      # 50,000 -> 50000
    t = t.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t)


def _strip_citation_text(sentence: str) -> str:
    """Remove timestamps and a trailing "— Title — Channel (mm:ss)" source tail.

    Both are citation apparatus, not claims: a timestamp is not a number the
    speaker said, and a video title's words are not details of the sentence.
    """
    t = sentence
    if _TRAILING_ATTRIBUTION.search(t):
        t = _TITLE_TAIL.sub("", t)
    return _TIME.sub(" ", t)


def specific_tokens(text: str) -> list[tuple[str, str]]:
    """Checkable details as (token, strength).

    strong: numbers of two or more digits, code-like identifiers, quoted strings.
    weak:   content-word pairs.
    """
    raw = _strip_citation_text(text)
    s = normalise(raw)
    tokens: list[tuple[str, str]] = []
    for m in _NUMBER.finditer(s):
        n = m.group(0)
        if len(n.replace(".", "")) >= 2:
            tokens.append((n, "strong"))
    for m in _IDENT.finditer(raw):
        tok = (m.group(1) or m.group(2) or "").strip().lower()
        if tok and not re.fullmatch(r"[\d.:,\s]+", tok):
            tokens.append((tok, "strong"))
    for m in _QUOTED.finditer(raw):
        q = normalise(m.group(1)).strip()
        if len(q) >= 3:
            tokens.append((q, "strong"))
    words = [w.lower() for w in _WORD.findall(raw)]
    for a, b in zip(words, words[1:]):
        if a not in _STOP and b not in _STOP and len(a) > 2 and len(b) > 2:
            tokens.append((f"{a} {b}", "weak"))
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for t, k in tokens:
        if t and t not in seen:
            seen.add(t)
            out.append((t, k))
    return out


def latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if c.isascii()) / len(letters)


def _words(haystack: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", haystack))


def _occurs(token: str, haystack: str) -> bool:
    if " " in token or not token[:1].isalnum():
        return token in haystack
    return re.search(rf"(?<![\w.]){re.escape(token)}(?![\w])", haystack) is not None


def present(token: str, haystack: str, words: set[str] | None = None) -> bool:
    """Is ``token`` evidenced in ``haystack`` (already normalised)?

    A word pair counts when both words occur. An identifier also counts when
    all its parts occur as words, because speech renders ``plt.plot`` as
    "plt dot plot".
    """
    words = words if words is not None else _words(haystack)
    if _occurs(token, haystack):
        return True
    if re.fullmatch(r"[a-z][a-z'-]+ [a-z][a-z'-]+", token):
        a, b = token.split(" ", 1)
        return a in words and b in words
    parts = [x for x in re.split(r"[._\s]+", token) if len(x) >= 2 and not x.isdigit()]
    return bool(parts) and all(x in words for x in parts)


# --------------------------------------------------------------------------
# Report parsing
# --------------------------------------------------------------------------

_LINK = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})(?:&(?:amp;)?|.*?[?&])t=(\d+)")
_MARK = re.compile(r"⟦([A-Za-z0-9_-]{11})\|(\d+)⟧")
_SPLIT = re.compile(r"(?<![\s(]\d\.)(?<![\s(]\d\d\.)(?<=[.!?])\s+(?=[A-Z0-9“\"(])")


class _ReportText(HTMLParser):
    """Report text with each citation link replaced by a marker ⟦video_id|seconds⟧."""

    _BLOCKS = ("p", "li", "h1", "h2", "h3", "h4", "tr", "br", "div", "section")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._link: tuple[str, int] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            m = _LINK.search(dict(attrs).get("href") or "")
            self._link = (m.group(1), int(m.group(2))) if m else None
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._link is not None:
            self.parts.append(f" ⟦{self._link[0]}|{self._link[1]}⟧ ")
            self._link = None
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def report_sentences(html: str) -> list[tuple[str, list[tuple[str, int]]]]:
    """(sentence text, [(video_id, seconds) cited in it]) for every sentence."""
    p = _ReportText()
    p.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(p.parts))
    out = []
    for block in text.split("\n"):
        for sent in _SPLIT.split(block.strip()):
            if not sent.strip():
                continue
            cites = [(m.group(1), int(m.group(2))) for m in _MARK.finditer(sent)]
            clean = re.sub(r"\s+", " ", _MARK.sub("", sent)).strip()
            if clean:
                out.append((clean, cites))
    return out


def _seconds(m: re.Match) -> float:
    a, b, c = m.group(1), m.group(2), m.group(3)
    return float(int(a) * 3600 + int(b) * 60 + int(c)) if c else float(int(a) * 60 + int(b))


# --------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------

_SCREEN = re.compile(
    r"\b(on[- ]screen|on the screen|visible|displayed|the video displays|screenshot|"
    r"the (?:frame|screen|slide)\b|frame (?:capture|description)s?)",
    re.I,
)
_ALSO_SEEN = re.compile(r"\balso (?:visible|shown|displayed)\b", re.I)
_SPEECH_VERB = re.compile(
    r"\b(says|said|notes|noted|explains|explained|states|stated|mentions|mentioned|lists|listed|reports|reported|"
    r"reiterates|adds|added|describes|described|tells|told|recommends|argues|claims|concedes|warns|points out|"
    r"announces|reads out|calls)\b",
    re.I,
)
_CLAUSE = re.compile(r"\s*(?:;|,(?=\s)|\swhile\s)\s*")


def _window(t: float, explicit: bool, w: Windows) -> tuple[float, float]:
    return (t - w.explicit, t + w.explicit) if explicit else (t - w.link_before, t + w.link_after)


def check_report(
    html: str,
    evidence: dict[str, Evidence],
    windows: Windows | None = None,
    aliases: dict[str, str] | None = None,
) -> list[Finding]:
    """Flag modality errors in a composed report; at most one finding per sentence.

    ``aliases`` maps lower-cased channel names and titles to video ids, so a
    sentence that names its video in prose ("the Data Analytics Lab tutorial,
    at 23:08 …") can still be checked when its citation link sits elsewhere.
    """
    w = windows or Windows()
    findings: list[Finding] = []
    alias_items = sorted((aliases or {}).items(), key=lambda kv: -len(kv[0]))
    for sentence, cites in report_sentences(html):
        cited = [(v, float(t)) for v, t in cites if v in evidence]
        if not cited and alias_items:
            low = sentence.lower()
            named = {vid for name, vid in alias_items if len(name) >= 6 and name in low and vid in evidence}
            if len(named) == 1:
                cited = [(next(iter(named)), 0.0)]
        if not cited:
            continue
        videos = {v for v, _ in cited}
        single = next(iter(videos)) if len(videos) == 1 else None
        screen_sentence = bool(_SCREEN.search(sentence))
        speaker_sentence = bool(_SPEECH_VERB.search(sentence))
        trailing = bool(_TRAILING_ATTRIBUTION.search(sentence))

        # Units to check: each clause that names its own time, else the whole sentence per citation.
        units: list[tuple[str, str, float, bool]] = []
        if single:
            body = _TITLE_TAIL.sub("", sentence) if trailing else sentence
            for clause in _CLAUSE.split(body):
                for m in _TIME.finditer(clause):
                    units.append((clause, single, _seconds(m), True))
        if not units:
            units = [(sentence, v, t, False) for v, t in cited if t > 0 or not cites]
        if not units:
            continue

        for clause, vid, t, explicit in units:
            ev = evidence[vid]
            lo, hi = _window(t, explicit, w)
            speech_raw = ev.speech_text(t - w.speech, t + w.speech + (0.0 if explicit else w.link_after))
            speech, visual = normalise(speech_raw), normalise(ev.visual_text(lo, hi))
            sw, vw = _words(speech), _words(visual)
            latin = latin_share(speech_raw) >= 0.5
            toks = [(k, s) for k, s in specific_tokens(clause) if latin or re.fullmatch(r"[\d.]+", k)]
            clause_screen = screen_sentence and (bool(_SCREEN.search(clause)) or explicit)

            if clause_screen:
                if not ev.has_visual(lo, hi):
                    findings.append(Finding("screen_claim_without_span", sentence, vid, t, [],
                                            f"no visual description within {lo:.0f}-{hi:.0f}s"))
                    break
                if _ALSO_SEEN.search(clause):
                    continue  # the screen confirming speech is the allowed form (S-1.18.6)
                in_span = [k for k, _ in toks if present(k, visual, vw)]
                spoken = [k for k, _ in toks if present(k, speech, sw) and not present(k, visual, vw)]
                if spoken and not in_span:
                    findings.append(Finding("speech_presented_as_screen", sentence, vid, t, spoken,
                                            "clause asserts the screen; its details occur only in nearby speech"))
                    break
            elif speaker_sentence or trailing:
                if not visual:
                    continue
                screen_only = [(k, s) for k, s in toks if present(k, visual, vw) and not present(k, speech, sw)]
                strong = [k for k, s in screen_only if s == "strong"]
                weak = [k for k, s in screen_only if s == "weak"]
                # A trailing "— Name (mm:ss)" is mostly source citation, so it can demand more evidence.
                if speaker_sentence:
                    hit = len(strong) >= w.speaker_strong or len(weak) >= w.speaker_weak
                else:
                    hit = len(strong) >= w.trailing_strong or len(weak) >= w.trailing_weak
                if hit:
                    findings.append(Finding("screen_detail_attributed_to_speaker", sentence, vid, t,
                                            strong + weak, "details occur only in a nearby visual description"))
                    break
    return findings

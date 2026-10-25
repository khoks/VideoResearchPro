"""Who said it, and what was only on screen — the deterministic attribution guard (S-1.18.9).

R1 merges frame descriptions into transcripts as ``[VISUAL @ mm:ss — ...]``
spans (D-067). Across eight blind-judged runs the residual defect kept one
shape: a sentence credited to a speaker ("X says / reads / lists ...", or a
clause ending "— Name (mm:ss)") carries a specific detail that exists only in
a span near the cited moment. Prompt rules moved the error rather than
removing it (D-075); map-stage said/shown labels (S-1.18.8) halved it. This
module removes it in code, at the two points where it enters:

- **Map items** (`label_items`). A detail of an item that appears in a span
  of the item's OWN source near its moment, and not in the speech around
  that moment, is screen-only. An item whose details are all screen-only
  becomes ``shown``; an item whose screen-only details fill clauses of their
  own is split into a ``shown`` item and the rest; otherwise the item lists
  them (``screen_only``) and compose names them in its tag. Run 8's weekday
  totals reached the composer tagged [SAID+SHOWN], and the tag note told it
  to credit the speaker.
- **The composed report** (`guard_report`). A detail that still sits in a
  part of a sentence credited to a speaker is marked in place, "(on screen
  at 18:24)", with the span's own timestamp. The opposite error — "also
  visible on screen", or "the video displays X", where no span of the cited
  source shows X and its speech says it — is corrected too. Every change is
  returned for the report's processing note.

**Near the moment, not anywhere.** Whether a detail is screen-only is
decided against the speech around the cited moment: in run 6 the presenter
said "light grid lines" at 9 minutes, and the sentence about 22:28 still took
"light grid" from the 22:33 frame. The stronger words "not spoken" need the
detail to be absent from the source's whole speech.

**Specific details** are what a reader can check and what the past errors
carried: numbers (native digits normalised), code identifiers, quoted
strings, visual descriptor pairs ("confidence band", "light grid") and runs
of three or more listed names (dataset names read off a screen). The guard
acts only on a detail it FINDS in a span, so what it writes ("on screen at
mm:ss") is true by construction; a detail found nowhere is left alone.

**What it never claims.** "Not spoken" is added only for a figure or a
multi-word quotation, only where the source's speech is in Latin script, and
only when the whole speech states it nowhere — reading "15 000", "fifteen
thousand" and "one two two" as numbers. Identifiers, pairs and names never
get it: captions write "carat" as "carrot". In Devanagari or Bengali speech
an absence proves nothing (S-1.18.7), so the mark says only where the detail
was shown. A rewrite never deletes a detail: substance moves, it is not lost.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field
from html import unescape
from typing import Iterable

from app.agents.prompts.shared import MODALITY_BOTH, MODALITY_SAID, MODALITY_SHOWN, MODALITY_UNKNOWN
from app.services import quote_fidelity
from app.services.visual_service import format_timestamp, strip_annotations

# --- normalisation ------------------------------------------------------------

_NATIVE_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯", "01234567890123456789")
_SPAN = re.compile(r"\[VISUAL @ (\d+(?::\d{2}){1,2}) [—–-] ([^\]]*)\]")
# A video timestamp; "10:00 a.m." is a time of day, not a moment in a video.
_STAMP = r"(?<![\d:])\d{1,2}(?::\d{2}){1,2}(?![\d:])(?!\s*(?:[ap]\.?m\b|[ap]\.m\.))"
INF = float("inf")


def _norm(text: str) -> str:
    """Lower-cased, NFKC, ASCII digits, straight quotes, no thousands separators."""
    t = unicodedata.normalize("NFKC", text or "").translate(_NATIVE_DIGITS).lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("−", "-")
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
    return re.sub(r"\s+", " ", t)


def _norm_speech(text: str) -> str:
    """`_norm` plus a caption habit: "15 000" is fifteen thousand."""
    return re.sub(r"\b(\d{1,3})((?: \d{3})+)\b", lambda m: m.group(1) + m.group(2).replace(" ", ""), _norm(text))


def _compact(text: str) -> str:
    """Letters and digits only, with spoken punctuation dropped ("plt dot plot")."""
    t = re.sub(r"\b(?:dot|underscore|bracket|brackets|parenthesis|parentheses|comma)\b", " ", _norm(text))
    return re.sub(r"[^a-z0-9]+", "", t)


def _seconds(stamp: str) -> float:
    total = 0
    for p in stamp.split(":"):
        total = total * 60 + int(p)
    return float(total)


def _latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if "LATIN" in unicodedata.name(c, "")) / len(letters)


def _overlaps(a: tuple[int, int], spans: Iterable[tuple[int, int]]) -> bool:
    return any(a[0] < e and s < a[1] for s, e in spans)


# --- numbers, in digits or in English words -----------------------------------

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_UNITS["oh"] = 0
_TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}


def _canonical_number(key: str) -> str:
    """One spelling per value: '17363.10' -> '17363.1', '08' -> '8'; versions kept."""
    if key.count(".") == 1:
        whole, frac = key.split(".")
        frac = frac.rstrip("0")
        whole = whole.lstrip("0") or "0"
        return f"{whole}.{frac}" if frac else whole
    if "." not in key:
        return key.lstrip("0") or "0"
    return key


def _spoken_numbers(speech: str) -> set[str]:
    """Every number a normalised speech states: digits, words ("fifteen thousand",
    "point nine two") and digit-by-digit readings ("one two two" for 122)."""
    found = {_canonical_number(m.group(0)) for m in re.finditer(r"\d+(?:\.\d+)*", speech)}
    words = re.findall(r"[a-z]+|\d+", speech)
    n = len(words)
    i = 0
    while i < n:
        # Digit by digit: "one two two" -> 122, "oh eight" -> 8.
        j = i
        while j < n and words[j] in _UNITS and _UNITS[words[j]] < 10:
            j += 1
        if j - i >= 2:
            found.add(_canonical_number("".join(str(_UNITS[w]) for w in words[i:j])))
        total, current, j, saw = 0, 0, i, False
        while j < n:
            w = words[j]
            if w in _UNITS:
                current += _UNITS[w]
            elif w in _TENS:
                current += _TENS[w]
            elif w.isdigit() and j + 1 < n and words[j + 1] in _SCALES:
                current += int(w)
            elif w in _SCALES and saw:
                if w == "hundred":
                    current = max(current, 1) * 100
                else:
                    total += max(current, 1) * _SCALES[w]
                    current = 0
            elif w == "and" and saw and j + 1 < n and (words[j + 1] in _UNITS or words[j + 1] in _TENS):
                pass
            else:
                break
            saw = True
            j += 1
        value = total + current
        if saw:
            found.add(str(value))
        if j < n and words[j] == "point":
            digits, k = [], j + 1
            while k < n and ((words[k] in _UNITS and _UNITS[words[k]] < 10) or words[k].isdigit()):
                digits.append(str(_UNITS[words[k]]) if words[k] in _UNITS else words[k])
                k += 1
            if digits:
                found.add(_canonical_number(f"{value if saw else 0}.{''.join(digits)}"))
                j = k
        i = max(j, i + 1)
    return found


# --- specific details ---------------------------------------------------------

@dataclass(frozen=True)
class Token:
    kind: str     # number | identifier | quoted | visual_pair | name
    text: str     # as written
    key: str      # normalised, for matching
    start: int
    end: int
    strong: bool


_NUMBER = re.compile(r"(?<![\w.,:/])[$₹€£]?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)+|\d+)%?(?![\w]|[.,:]\d)")
_IDENTIFIERS = [
    re.compile(r"`([^`\n]{1,60})`"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?:\(\))?"),
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b(?:\(\))?"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(\)"),
    re.compile(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b"),
    re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b"),
]
_QUOTED = [re.compile(r'"([^"\n]{3,100})"'), re.compile(r"“([^”\n]{3,100})”")]
_LONG_QUOTED = [re.compile(r'"[^"\n]{1,3000}"'), re.compile(r"“[^”\n]{1,3000}”")]
_ABBREVIATIONS = {"e.g", "i.e", "a.m", "p.m", "u.s", "u.k", "vs", "etc", "approx", "no", "fig", "dr", "mr", "ms"}
# Three or more single lower-case names in a comma list: "dowjones, fmri, iris and seaice".
_NAME_LIST = re.compile(r"\b[a-z][a-z0-9_]{2,}(?:,\s+(?:and\s+|or\s+)?[a-z][a-z0-9_]{2,}){2,}(?:,?\s+(?:and|or)\s+[a-z][a-z0-9_]{2,})?")

_COLOURS = set("red blue green purple orange pink yellow grey gray black white brown teal cyan magenta "
               "violet navy maroon golden gold silver beige turquoise".split())
_SHADES = set("light dark pale bright shaded translucent transparent dashed dotted".split())
_VISUAL_NOUNS = set("band grid gridlines shading background whiskers colorbar colourbar palette gradient "
                    "outline border hatching".split())
_STOP = set("a an the and or of to in on at by for with from as is are was were be it its this that "
            "these those which who not no but if so also only very more most less".split())


_CALL_ARGS = re.compile(r"(?<=[\w.])\((?:[^()]|\([^()]*\))*\)")
_ASSIGNMENT = re.compile(r"\b\w+=[^\s,;)]+")


def code_ranges(text: str) -> list[tuple[int, int]]:
    """Call arguments and keyword assignments: code, not prose figures ("add_subplot(121)", "dpi=300")."""
    return [m.span() for rx in (_CALL_ARGS, _ASSIGNMENT) for m in rx.finditer(text)]


def specific_tokens(text: str, masked: Iterable[tuple[int, int]] = ()) -> list[Token]:
    """The checkable details in ``text``, outside the ``masked`` ranges.

    Timestamps are never details (a link label is citation, not a claim), a
    single digit is too common to mean anything, and an identifier wins over
    the numbers and words inside it. Inside call arguments and assignments
    only identifiers count: the rest is code, not a claim.
    """
    taken: list[tuple[int, int]] = list(masked)
    taken.extend(m.span() for m in re.finditer(_STAMP, text))
    code = code_ranges(text)
    out: list[Token] = []

    def add(kind: str, raw: str, key: str, span: tuple[int, int], strong: bool) -> None:
        if not key or _overlaps(span, taken):
            return
        if kind != "identifier" and _overlaps(span, code):
            return
        taken.append(span)
        out.append(Token(kind, raw, key, span[0], span[1], strong))

    for rx in _QUOTED:
        for m in rx.finditer(text):
            inner = m.group(1).strip()
            key = re.sub(r"\s+", " ", re.sub(r"[^\w\s.]+", " ", _norm(inner))).strip()
            if len(key) >= 3:
                add("quoted", inner, key, m.span(), len(key.split()) >= 2 or len(key) >= 6)
    for rx in _IDENTIFIERS:
        for m in rx.finditer(text):
            raw = (m.group(1) if rx.pattern.startswith("`") else m.group(0)).strip()
            parts = [p for p in re.split(r"[._()\s]+", raw) if p]
            if (len(raw) < 2 or raw.lower().rstrip(".") in _ABBREVIATIONS or not any(len(p) >= 2 for p in parts)
                    or raw[0].isdigit()):
                continue
            add("identifier", raw, _norm(raw), m.span(), _structured(raw))
    for m in _NUMBER.finditer(text):
        figure = m.group(1)
        if len(re.sub(r"\D", "", figure)) < 2:
            continue
        strong = "." in figure or "," in figure or len(figure.split(".")[0]) >= 3
        add("number", m.group(0), _canonical_number(_norm(figure)), m.span(), strong)
    words = list(re.finditer(r"[A-Za-z][A-Za-z-]+", text))
    for a, b in zip(words, words[1:]):
        wa, wb = a.group(0).lower(), b.group(0).lower()
        if text[a.end():b.start()].strip() or wa in _STOP or wb in _STOP:
            continue
        if wa in _COLOURS or wa in _SHADES or wb in _VISUAL_NOUNS:
            add("visual_pair", f"{a.group(0)} {b.group(0)}", f"{wa} {wb}", (a.start(), b.end()), True)
    for m in _NAME_LIST.finditer(text):
        for w in re.finditer(r"[a-z][a-z0-9_]{2,}", m.group(0)):
            if w.group(0) not in ("and", "or"):
                add("name", w.group(0), w.group(0), (m.start() + w.start(), m.start() + w.end()), False)
    out.sort(key=lambda t: t.start)
    return out


def _structured(raw: str) -> bool:
    """An identifier specific enough to act on alone: dotted, snake_case, a call
    or CamelCase. A plain word in backticks ("`data`", a column name) is weak."""
    return len(_compact(raw)) >= 4 and bool(re.search(r"[._(]|[a-z][A-Z]", raw))


def verifiable(tok: Token) -> bool:
    """Kinds whose absence from Latin-script speech is trusted: figures and multi-word quotes."""
    return (tok.kind == "number" and tok.strong) or (tok.kind == "quoted" and len(tok.key.split()) >= 2)


def acts(found: list[Token]) -> bool:
    """Enough to act on: one strong detail, two weak ones, or three listed names."""
    if all(t.kind == "name" for t in found):
        return len(found) >= 3
    return any(t.strong for t in found) or len(found) >= 2


# --- evidence -----------------------------------------------------------------

@dataclass
class Span:
    seconds: float
    norm: str
    compact: str


@dataclass
class Speech:
    """Speech to search: normalised text, compact form, stated numbers, raw text."""
    raw: str
    norm: str
    compact: str
    numbers: set[str]
    _vt: quote_fidelity.VideoText | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def of(cls, raw: str) -> "Speech":
        norm = _norm_speech(raw)
        return cls(raw, norm, _compact(raw), _spoken_numbers(norm))

    def video_text(self) -> quote_fidelity.VideoText:
        with self._lock:
            if self._vt is None:
                self._vt = quote_fidelity.VideoText.from_raw("", self.raw)
            return self._vt


@dataclass(eq=False)
class Source:
    sid: str
    title: str
    channel: str
    video_id: str
    speech: Speech
    segments: list[tuple[float, float, str]]   # (start, end, speech text) per chunk, in order
    latin: bool
    spans: list[Span]
    _near: dict = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def label(self) -> str:
        return self.channel or self.title

    def near(self, lo: float, hi: float) -> Speech:
        """Speech of the chunks overlapping [lo, hi]."""
        if lo == -INF and hi == INF:
            return self.speech
        key = (lo, hi)
        with self._lock:
            if key not in self._near:
                texts = [t for a, b, t in self.segments if b >= lo and a <= hi]
                self._near[key] = Speech.of(quote_fidelity.merge_chunk_texts(texts))
            return self._near[key]

    def spoken_at(self, tok: Token) -> float | None:
        """Start of the first chunk whose speech states ``tok``."""
        for a, b, t in self.segments:
            if spoken(tok, Speech.of(t)):
                return a
        return None


def _url_key(value: object) -> str:
    return str(value or "").split("&t=")[0].split("?t=")[0].strip()


def _identity(meta: dict) -> str:
    return str(
        meta.get("document_id") or meta.get("video_id")
        or _url_key(meta.get("video_url") or meta.get("url") or meta.get("permalink"))
        or meta.get("video_title") or ""
    )


def _title_variants(title: str) -> set[str]:
    """A title and the shortened forms a composer cites it by."""
    out = {re.sub(r"\s+", " ", title).strip()}
    for sep in (" | ", ": ", " - ", " — ", " – "):
        for t in list(out):
            head = t.split(sep)[0].strip()
            if len(head) >= 12:
                out.add(head)
    return {t for t in out if t}


class Evidence:
    """Per-source speech and on-screen spans, built once from a report's chunks."""

    def __init__(self, sources: dict[str, Source], keys: dict[str, str], speaker_names: Iterable[str] = ()):
        self.sources = sources
        self.keys = keys
        self.has_visual = any(s.spans for s in sources.values())
        self.speaker_names = {n.strip() for n in speaker_names if n and len(n.strip()) >= 3}
        names: dict[str, set[str]] = {}
        for s in sources.values():
            variants = _title_variants(s.title) if s.title else set()
            if s.channel and len(s.channel) >= 4:
                variants.add(s.channel)
            for name in variants:
                names.setdefault(name.lower(), set()).add(s.sid)
        # Longest first, so a title wins over the channel name inside it.
        self.aliases = sorted(((n, frozenset(v)) for n, v in names.items()), key=lambda kv: -len(kv[0]))
        refs = [re.escape(n) for n, _ in self.aliases] + [re.escape(n.lower()) for n in self.speaker_names]
        refs.append(r"presenters?|instructors?|speakers?|hosts?|narrators?|tutors?|teachers?|lecturers?|"
                    r"creators?|authors?|youtubers?|he|she|they|his|her|their|video|tutorial|course|lecture|"
                    r"session|channel|walkthrough|source")
        self.speaker_ref = re.compile(r"\b(?:" + "|".join(refs) + r")\b", re.I)

    def resolve(self, *, video_id: str = "", url: str = "", title: str = "") -> Source | None:
        for key in (video_id, _url_key(url), f"title:{title}" if title else ""):
            sid = self.keys.get(key) if key else None
            if sid:
                return self.sources.get(sid)
        return None


def build_evidence(chunks: list[dict], speaker_names: Iterable[str] = ()) -> Evidence:
    """Speech (spans stripped, chunk overlap removed) and spans for every source in ``chunks``."""
    by_source: dict[str, list[tuple[float, int, float, str]]] = {}
    metas: dict[str, dict] = {}
    keys: dict[str, str] = {}
    for ch in chunks or []:
        meta = ch.get("metadata") or {}
        sid = _identity(meta)
        if not sid:
            continue
        start = float(meta.get("timestamp_start") or 0)
        end = float(meta.get("timestamp_end") or start)
        by_source.setdefault(sid, []).append((start, int(meta.get("chunk_index") or 0), end, ch.get("text") or ""))
        metas.setdefault(sid, meta)
        for key in (meta.get("video_id"), _url_key(meta.get("video_url")), _url_key(meta.get("url"))):
            if key:
                keys.setdefault(str(key), sid)
        if meta.get("video_title"):
            keys.setdefault(f"title:{meta['video_title']}", sid)
    sources: dict[str, Source] = {}
    for sid, parts in by_source.items():
        parts.sort(key=lambda p: (p[0], p[1]))
        spans: dict[tuple[float, str], Span] = {}
        segments: list[tuple[float, float, str]] = []
        for start, _, end, text in parts:
            for m in _SPAN.finditer(text):
                sec = _seconds(m.group(1))
                spans.setdefault((sec, m.group(2)), Span(sec, _norm(m.group(2)), _compact(m.group(2))))
            segments.append((start, end, strip_annotations(text)))
        speech_raw = quote_fidelity.merge_chunk_texts(t for _, _, t in segments)
        meta = metas[sid]
        sources[sid] = Source(
            sid=sid, title=str(meta.get("video_title") or ""), channel=str(meta.get("channel_name") or ""),
            video_id=str(meta.get("video_id") or ""), speech=Speech.of(speech_raw), segments=segments,
            latin=_latin_share(speech_raw) >= 0.6, spans=sorted(spans.values(), key=lambda s: s.seconds),
        )
    return Evidence(sources, keys, speaker_names)


# --- is a detail in a span, in speech? --------------------------------------------

def _occurs(key: str, haystack: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(key)}(?![\w]|\.\d)", haystack) is not None


def _pair_near(key: str, haystack: str, gap: int = 2) -> bool:
    a, b = key.split(" ", 1)
    return re.search(rf"\b{re.escape(a)}\b(?:\W+\w+){{0,{gap}}}?\W+{re.escape(b)}\b", haystack) is not None


def in_span(tok: Token, span: Span) -> bool:
    if tok.kind == "number":
        return any(_canonical_number(n) == tok.key for n in re.findall(r"\d+(?:\.\d+)*", span.norm))
    if tok.kind == "identifier":
        c = _compact(tok.text)
        return _occurs(tok.key, span.norm) or (len(c) >= 6 and c in span.compact)
    if tok.kind == "quoted":
        return tok.key in re.sub(r"[^\w\s.]+", " ", span.norm)
    if tok.kind == "name":
        # A listed name counts only as listed on screen: quoted or in code, as
        # sns.get_dataset_names() prints them — not a word in a description.
        return re.search(rf"[`'\"]{re.escape(tok.key)}[`'\"]", span.norm) is not None
    return _pair_near(tok.key, span.norm)


def spoken(tok: Token, speech: Speech) -> bool:
    """Whether ``speech`` states the detail."""
    if tok.kind == "number":
        if tok.key in speech.numbers:
            return True
        whole = tok.key.split(".")[0]
        # A rounded or truncated reading ("about 17,363") is the speaker's figure.
        return "." in tok.key and len(whole) >= 2 and whole in speech.numbers
    if tok.kind == "identifier":
        c = _compact(tok.text)
        if _occurs(tok.key, speech.norm) or (len(c) >= 6 and c in speech.compact):
            return True
        # "plt dot plot", "mat plot lib": every word of it was said.
        parts = [p for p in re.split(r"[^a-z]+", tok.key) if len(p) >= 3]
        return bool(parts) and all(_occurs(p, speech.norm) or (len(p) >= 6 and p in speech.compact) for p in parts)
    if tok.kind == "quoted":
        if tok.key in re.sub(r"[^\w\s.]+", " ", speech.norm):
            return True
        frags = quote_fidelity.fragments(tok.text)
        vt = speech.video_text()
        return bool(frags) and all(vt.coverage(f) >= quote_fidelity.NEAR for f in frags)
    if tok.kind == "name":
        return _occurs(tok.key, speech.norm) or tok.key.replace("_", "") in speech.compact
    return _pair_near(tok.key, speech.norm, gap=3)


@dataclass
class ScreenOnly:
    source: Source
    seconds: float
    verified: bool   # Latin speech, a trusted kind, and absent from the whole of it


# Speech counted as "around" a span window: the chunks a little before and after it.
NEAR_SPEECH_BEFORE = 60.0
NEAR_SPEECH_AFTER = 30.0


def screen_only(tok: Token, scope: list[tuple[Source, float, float]]) -> ScreenOnly | None:
    """The span that shows ``tok`` within ``scope``, when no speech around it states it.

    ``scope`` is (source, from, to) in seconds, the first entry the most
    likely one. None when the detail is in no span there (not screen
    content) or any scoped source says it around that window.
    """
    for src, lo, hi in scope:
        best: Span | None = None
        for span in src.spans:
            if lo <= span.seconds <= hi and in_span(tok, span):
                anchor = lo + CITE_BEFORE_SECONDS if lo != -INF else span.seconds
                if best is None or abs(span.seconds - anchor) < abs(best.seconds - anchor):
                    best = span
        if best is None:
            continue
        # Around THIS window for the source that shows it (a sentence citing
        # 7:22 and 22:28 means two moments); any scoped window for the others,
        # who may be the speaker the sentence credits.
        if spoken(tok, src.near(lo - NEAR_SPEECH_BEFORE, hi + NEAR_SPEECH_AFTER)) or any(
            spoken(tok, s.near(a - NEAR_SPEECH_BEFORE, b + NEAR_SPEECH_AFTER)) for s, a, b in scope if s is not src
        ):
            return None
        verified = (src.latin and verifiable(tok)
                    and not any(spoken(tok, s.speech) for s in {x for x, _, _ in scope}))
        return ScreenOnly(src, best.seconds, verified)
    return None


# --- map items ---------------------------------------------------------------------

_ITEM_KEYS = ("facts", "comments", "conclusions", "references", "speakers")
_RANGE = re.compile(r"(\d+(?::\d{2}){1,2})\s*[–—-]\s*(\d+(?::\d{2}){1,2})")
_ONE = re.compile(r"(\d+(?::\d{2}){1,2})")

# Window around an item's own moment in which a span counts as near it.
ITEM_BEFORE_SECONDS = 30.0
ITEM_AFTER_SECONDS = 60.0


def _item_window(item: dict) -> tuple[float, float] | None:
    disp = str(item.get("timestamp_display") or "")
    m = _RANGE.search(disp)
    if m:
        return _seconds(m.group(1)), _seconds(m.group(2))
    m = _ONE.search(disp)
    if m:
        return _seconds(m.group(1)), _seconds(m.group(1))
    try:
        ts = item.get("timestamp_seconds")
        if ts is not None and str(ts).strip() != "":
            return float(ts), float(ts)
    except (TypeError, ValueError):
        pass
    return None


def _item_clauses(text: str) -> list[tuple[int, int]]:
    """Where an item's content can be split: sentence ends and semicolons."""
    bounds, start = [], 0
    for m in re.finditer(r";\s+|(?<=[.!?])\s+(?=[A-Z0-9\"“])", text):
        bounds.append((start, m.start()))
        start = m.end()
    bounds.append((start, len(text)))
    return [(a, b) for a, b in bounds if text[a:b].strip()]


def label_items(summary: object, evidence: Evidence, counts: dict | None = None) -> None:
    """Fix each item's modality from its details, in place (after `report_agent._label_modality`).

    Items from a source with no span, and items already ``shown``, are left
    alone. For the rest, a detail found in a span of the item's own source
    near its moment and not in the speech around it is screen-only.

    - Every detail screen-only, all of them trusted (`verifiable`, Latin
      speech, absent from the whole speech), no ``original`` quote: the item
      becomes ``shown``.
    - Trusted screen-only details that fill clauses of their own: those
      clauses become a new ``shown`` item right after this one.
    - Otherwise the item carries ``screen_only`` (raised from ``said`` or
      ``unknown`` to ``both``) and compose names those details in its tag.

    The label before is kept in ``modality_before_guard``. Devanagari or
    Bengali speech is never relabelled — the map model read it, and an absence
    of digits there proves nothing — so its details are listed only.
    """
    if not isinstance(summary, dict) or not evidence.has_visual:
        return
    for key in _ITEM_KEYS:
        items = summary.get(key)
        if not isinstance(items, list):
            continue
        out: list = []
        for item in items:
            out.append(item)
            if not isinstance(item, dict) or item.get("modality") == MODALITY_SHOWN:
                continue
            src = evidence.resolve(url=str(item.get("video_url") or ""), title=str(item.get("video_title") or ""))
            if src is None or not src.spans:
                continue
            window = _item_window(item)
            lo, hi = (window[0] - ITEM_BEFORE_SECONDS, window[1] + ITEM_AFTER_SECONDS) if window else (-INF, INF)
            content = str(item.get("content") or "")
            tokens = specific_tokens(content, _alias_ranges(content, evidence))
            hits = {t: screen_only(t, [(src, lo, hi)]) for t in tokens}
            found = [t for t in tokens if hits[t]]
            if not found or not acts(found):
                continue
            others = [t for t in tokens if not hits[t]]
            trusted = all(hits[t].verified for t in found) and not item.get("original")
            before = item.get("modality") or MODALITY_UNKNOWN
            if trusted and not others:
                item["modality_before_guard"] = before
                item["modality"] = MODALITY_SHOWN
                _count(counts, "relabelled_shown")
                continue
            if trusted:
                shown_parts, kept_parts = [], []
                for a, b in _item_clauses(content):
                    inside = [t for t in tokens if a <= t.start < b]
                    (shown_parts if inside and all(hits[t] for t in inside) else kept_parts).append(
                        content[a:b].strip().rstrip(";"))
                if shown_parts and kept_parts:
                    item["content"] = "; ".join(kept_parts)
                    item["modality_before_guard"] = before
                    split = {k: v for k, v in item.items()
                             if k not in ("original", "quote_form", "speaker", "modality_before_guard")}
                    split.update(content="; ".join(shown_parts), modality=MODALITY_SHOWN, split_by_guard=True)
                    out.append(split)
                    _count(counts, "split")
                    continue
            item["screen_only"] = [t.text for t in found]
            if before in (MODALITY_SAID, MODALITY_UNKNOWN):
                item["modality_before_guard"] = before
                item["modality"] = MODALITY_BOTH
            _count(counts, "listed")
        summary[key] = out


def _count(counts: dict | None, key: str) -> None:
    if counts is not None:
        counts[key] = counts.get(key, 0) + 1


def _alias_ranges(text: str, evidence: Evidence) -> list[tuple[int, int]]:
    """Where source titles and channel names occur: names, not details."""
    low = text.lower()
    out: list[tuple[int, int]] = []
    for name, _ in evidence.aliases:
        start = 0
        while (i := low.find(name, start)) >= 0:
            if not _overlaps((i, i + len(name)), out):
                out.append((i, i + len(name)))
            start = i + len(name)
    return out


# --- the composed report ------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_BLOCK_TAG = re.compile(r"</?(?:p|li|ul|ol|h[1-6]|tr|td|th|table|thead|tbody|div|section|blockquote|br|hr)\b", re.I)
_CLOSING_INLINE = re.compile(r"</(?:code|strong|em|b|i|a|span|sup|sub|mark)>", re.I)
_HREF = re.compile(r'href="([^"]*)"', re.I)
_VID = re.compile(r"(?:[?&]v=|youtu\.be/)([\w-]{11})")
_T = re.compile(r"[?&]t=(\d+)")
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);")


@dataclass
class _Link:
    start: int
    end: int
    video_id: str
    seconds: float


class _Text:
    """The report's text with a map back to HTML offsets; block tags become newlines."""

    def __init__(self, html: str):
        self.html = html
        chars: list[str] = []
        pos: list[int] = []      # HTML offset where each text character starts
        ends: list[int] = []     # ... and where it ends (an entity is one character)
        self.links: list[_Link] = []
        self.code: list[tuple[int, int]] = []
        link_open: tuple[int, str] | None = None
        code_open: int | None = None

        def push(ch: str, start: int, end: int) -> None:
            chars.append(ch)
            pos.append(start)
            ends.append(end)

        def text_node(a: int, b: int) -> None:
            k = a
            for m in _ENTITY.finditer(html, a, b):
                for j in range(k, m.start()):
                    push(html[j], j, j + 1)
                push(unescape(m.group(0))[:1] or " ", m.start(), m.end())
                k = m.end()
            for j in range(k, b):
                push(html[j], j, j + 1)

        i = 0
        for m in _TAG.finditer(html):
            text_node(i, m.start())
            tag = m.group(0)
            low = tag.lower()
            if _BLOCK_TAG.match(low):
                push("\n", -1, -1)
            elif low.startswith("<a "):
                href = _HREF.search(tag)
                link_open = (len(chars), href.group(1) if href else "")
            elif low.startswith("</a"):
                if link_open is not None:
                    href = link_open[1].replace("&amp;", "&")
                    v, t = _VID.search(href), _T.search(href)
                    if v:
                        self.links.append(_Link(link_open[0], len(chars), v.group(1),
                                                float(t.group(1)) if t else -1.0))
                link_open = None
            elif low.startswith("<code"):
                code_open = len(chars)
            elif low.startswith("</code"):
                if code_open is not None:
                    self.code.append((code_open, len(chars)))
                code_open = None
            i = m.end()
        text_node(i, len(html))
        self.text = "".join(chars)
        self.pos = pos
        self.ends = ends

    def html_after(self, t_end: int) -> int | None:
        """HTML offset right after text offset ``t_end - 1``, past closing inline tags."""
        if t_end <= 0 or self.ends[t_end - 1] < 0:
            return None
        h = self.ends[t_end - 1]
        while (m := _CLOSING_INLINE.match(self.html, h)):
            h = m.end()
        return h

    def html_range(self, a: int, b: int) -> tuple[int, int] | None:
        """HTML range for text [a, b) when it lies inside one text node, else None."""
        if a >= b or self.pos[a] < 0 or self.ends[b - 1] < 0:
            return None
        ha, hb = self.pos[a], self.ends[b - 1]
        return (ha, hb) if "<" not in self.html[ha:hb] else None


_ABBREV_END = re.compile(r"\b(?:e\.g|i\.e|vs|approx|etc|a\.m|p\.m|no|fig|dr|mr|ms|st)\.$", re.I)


def _sentences(text: str, protected: list[tuple[int, int]] = ()) -> list[tuple[int, int]]:
    """Sentence ranges; never split inside a ``protected`` range (a title like "01. Seaborn in Python")."""
    out: list[tuple[int, int]] = []
    for block in re.finditer(r"[^\n]+", text):
        start = block.start()
        for m in re.finditer(r"[.!?][\"”’)]*\s+(?=[A-Z0-9\"“(])", block.group(0)):
            end = block.start() + m.start() + 1
            if _ABBREV_END.search(text[max(start, end - 8):end]) or _overlaps((end - 1, end), protected):
                continue
            out.append((start, end))
            start = block.start() + m.end()
        if block.end() > start:
            out.append((start, block.end()))
    return [(a, b) for a, b in out if text[a:b].strip()]


# Verbs that credit speech. Most are nouns too ("the notes", "a list"), so a
# match counts only with a speaker before it in its clause (see `_events`).
_SPEECH = re.compile(
    r"\b(?:says?|said|saying|notes|noted|noting|explains?|explained|explaining|states|stated|stating|"
    r"mentions?|mentioned|mentioning|lists|listed|listing|reports|reported|reporting|reads|read out|reading out|"
    r"recites?|recited|describes?|described|describing|calls|calling|names|naming|"
    r"recommends?|recommended|recommending|argues?|argued|arguing|claims|claimed|claiming|"
    r"concludes?|concluded|concluding|adds|added|tells?|told|telling|warns?|warned|insists?|insisted|"
    r"observes?|observed|remarks?|remarked|emphasi[sz]es|emphasi[sz]ed|stresses|stressed|suggests?|suggested|"
    r"advises?|advised|cites?|cited|quotes|quoted|points? out|pointed out|reiterates?|reiterated|"
    r"confirms?|confirmed|admits?|admitted|concedes?|conceded|enumerates?|enumerated|"
    r"summari[sz]es|summari[sz]ed|announces?|announced|puts it|walks? (?:\w+ )?through)\b",
    re.I,
)
_NOUN_TOO = {"names", "lists", "notes", "reports", "claims", "calls", "states", "quotes", "remarks", "cites",
             "adds", "reads", "says", "tells", "warns", "observes", "suggests", "advises", "confirms"}
_DETERMINER_BEFORE = re.compile(r"\b(?:the|a|an|its|his|her|their|these|those|such|our|your|my)\s+$", re.I)
# A participle credits only through its agent: "named by CodeWithMunnaX" (run 4),
# never "a DataFrame named titanic".
_PARTICIPLE_BY = re.compile(r"\b(?:named|called|listed|described|reported|mentioned|stated|read out)\s+by\s+", re.I)
_SCREEN = re.compile(
    r"\bon[- ]?screen\b|\b(?:visible|displayed|shown|pictured|rendered)\b|\b(?:displays?|displaying|shows|showing|showed)\b"
    r"|\bthe (?:demonstrated|resulting)\b|\b(?:frames?|screenshots?|slides?)\b"
    r"|\b(?:the|this|that|its)\s+(?:[\w-]+\s+){0,2}?(?:notebook|chart|plot|graph|figure|table|output|code|cell|"
    r"heat ?map|legend|axis|axes|title|terminal|console|traceback|dataframe|editor|screen)s?\s+"
    r"(?:reads|lists|contains|carries|includes|has|uses|labels|is titled|prints|gives|returns|warns|reports|names)\b",
    re.I,
)
_SCREEN_VERB = re.compile(r"displays?|displaying|shows|showing|showed", re.I)
# An explicit claim about what this video's screen showed — the only kind the
# speech-as-screen correction acts on. "displays a tick every four weeks" is
# what code does; "makes the grid visible" is not a claim about the frame.
_STRICT_SCREEN = re.compile(
    r"\bon[- ]?screen\b|\b(?:the|this) video (?:displays|shows|showed)\b|\bthe (?:displayed|demonstrated)\b"
    r"|\b(?:visible|displayed|shown)\s+(?:on|in)\s+(?:the\s+)?(?:screen|frame|notebook|video|slide)\b"
    r"|\bthe (?:screen|frame|slide) (?:shows|displays|reads|lists)\b",
    re.I,
)
# "A regression plot displays two variables": what such a plot does in general, not this video's screen.
_GENERIC_SUBJECT = re.compile(r"\b(?:an?|each|every|any)\s+(?:[\w-]+\s+){0,3}$", re.I)
_ALSO_BEFORE = re.compile(r"\b(?:also|and)\s+$", re.I)
_ALSO_CLAIM = re.compile(
    r"(?:\s*[,;]\s*|\s+[—–]\s+|\s*\(\s*|\s+)"
    r"(?P<phrase>(?:which (?:is|was) )?(?:also|and) (?:(?:clearly|plainly) )?(?:visible|shown|displayed)"
    r"(?: on[- ]?screen| in the (?:frame|notebook|video))?|also on[- ]?screen)"
    r"(?P<close>\s*\))?",
    re.I,
)
_PLAIN_STAMP = re.compile(r"(" + _STAMP + r")(?:\s*[–—-]\s*(" + _STAMP + r"))?")
_PRONOUN_LEAD = re.compile(r"^\W*(?:he|she|they|his|her|their|it|this|the (?:same )?(?:presenter|instructor|speaker|"
                           r"host|narrator|video|tutorial|source|channel|output))\b", re.I)

# Window around a cited moment. Links point at chunk starts and a chunk runs
# a minute or two, so the span can sit well after the link (R1 run 8: link at
# 17:19, span at 18:24).
CITE_BEFORE_SECONDS = 30.0
CITE_AFTER_SECONDS = 150.0


@dataclass
class Rewrite:
    kind: str           # screen_detail_marked | screen_claim_removed | speech_as_screen_marked
    sentence: str
    tokens: list[str]
    source: str
    seconds: float | None
    verified: bool = False

    def as_dict(self) -> dict:
        return {"kind": self.kind, "sentence": self.sentence[:400], "tokens": self.tokens,
                "source": self.source, "seconds": self.seconds, "verified": self.verified}


def _quoted_ranges(s: str) -> list[tuple[int, int]]:
    """Quotations: what a speaker said (or its translation), never markers."""
    out = [m.span() for rx in _QUOTED for m in rx.finditer(s)]
    out += [m.span() for m in re.finditer(r"[ऀ-৿][^()\n]*?[ऀ-৿।]", s)]
    return out


def _citation_ranges(s: str, evidence: Evidence) -> list[tuple[int, int]]:
    """Citation apparatus: "(mm:ss)", "(Title — Channel, mm:ss)", "— Title — Channel (".

    The words in a title are not details of the sentence citing it.
    """
    out: list[tuple[int, int]] = []

    def residue(text: str) -> int:
        t = text.lower()
        for name, _ in evidence.aliases:
            t = t.replace(name, " ")
        t = re.sub(_STAMP, " ", t)
        t = re.sub(r"\b(?:and|at|in|from|to|see|via|by|the|video|of|presented|by)\b", " ", t)
        return len(re.findall(r"[a-z0-9]+", t))

    for m in re.finditer(r"\([^()]*\)", s):
        inner = m.group(0)[1:-1]
        if re.search(_STAMP, inner) and residue(inner) <= 3:
            out.append(m.span())
    for m in re.finditer(r"\s[—–]\s", s):
        nxt = s.find("(", m.end())
        stop = min([p for p in (nxt, s.find(";", m.end())) if p >= 0] or [len(s)])
        seg = s[m.end():stop]
        if seg.strip() and any(n in seg.lower() for n, _ in evidence.aliases) and residue(seg) <= 3:
            out.append((m.start(), stop))
    return out


def _depths(s: str) -> list[int]:
    """Parenthesis depth at every offset."""
    out, d = [], 0
    for ch in s:
        if ch == ")":
            d = max(0, d - 1)
        out.append(d)
        if ch == "(":
            d += 1
    return out


def _boundaries(s: str) -> list[tuple[int, int]]:
    """Clause delimiters outside parentheses: dashes, and semicolons that do not
    just separate list items ("Monday 17,363.10; Tuesday 18,158.38" is one list)."""
    depth = _depths(s)
    out = [m.span() for m in re.finditer(r"\s[—–]\s", s) if depth[m.start()] == 0]
    semis = [m.span() for m in re.finditer(r";", s) if depth[m.start()] == 0]
    cuts = [0] + [b for _, b in semis] + [len(s)]
    for k, (a, b) in enumerate(semis):
        left, right = s[cuts[k]:a], s[b:semis[k + 1][0] if k + 1 < len(semis) else len(s)]
        if len(left.split()) <= 5 and len(right.split()) <= 5:
            continue
        out.append((a, b))
    return sorted(out)


def _clause_of(s: str, p: int) -> tuple[int, int, int, int]:
    """(inner_start, inner_end, host_start, host_end) of the clause holding offset ``p``.

    Inner is the innermost parenthetical around ``p`` if any, else its clause;
    host is the clause around the inner one.
    """
    open_at, depth = None, 0
    for i in range(p - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            if depth == 0:
                open_at = i
                break
            depth -= 1
    close_at = None
    if open_at is not None:
        depth = 0
        for i in range(p, len(s)):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                if depth == 0:
                    close_at = i
                    break
                depth -= 1
        if close_at is None:
            open_at = None
    lo_anchor = open_at if open_at is not None else p
    hi_anchor = close_at if close_at is not None else p
    hs, he = 0, len(s)
    for a, b in _boundaries(s):
        if open_at is not None and open_at < a < close_at:
            continue
        if b <= lo_anchor:
            hs = b
        elif a >= hi_anchor:
            he = a
            break
    if open_at is not None:
        return open_at + 1, close_at, hs, he
    return hs, he, hs, he


def _open_paren(s: str, p: int) -> int | None:
    """Offset of the innermost "(" still open at ``p``."""
    depth = 0
    for i in range(p - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            if depth == 0:
                return i
            depth -= 1
    return None


def _events(s: str, skip: list[tuple[int, int]], evidence: Evidence) -> list[tuple[int, str]]:
    """Speech credits and on-screen markers in a sentence, in order.

    ``skip`` holds quotations and citation apparatus. A speech verb credits
    only with a speaker before it in its clause (a channel, a title, a
    speaker's name, "the presenter", "he") and no on-screen subject in
    between — "the notebook on screen warns" is the screen talking — or as
    "named by / according to <speaker>".
    """
    screen = []
    for m in _SCREEN.finditer(s):
        if _overlaps(m.span(), skip):
            continue
        if _SCREEN_VERB.fullmatch(m.group(0)) and _GENERIC_SUBJECT.search(s[max(0, m.start() - 60):m.start()]):
            continue
        kind = "also" if _ALSO_BEFORE.search(s[max(0, m.start() - 6):m.start()]) else "screen"
        screen.append((m.start(), kind))
    refs = [m.span() for m in evidence.speaker_ref.finditer(s) if not _overlaps(m.span(), skip)]
    ev = list(screen)
    for m in _SPEECH.finditer(s):
        if _overlaps(m.span(), skip):
            continue
        if m.group(0).lower() in _NOUN_TOO and _DETERMINER_BEFORE.search(s[max(0, m.start() - 12):m.start()]):
            continue   # "the names include", "his notes"
        paren = _open_paren(s, m.start())
        hs = max([0] + [b for a, b in _boundaries(s) if b <= m.start()] + ([paren + 1] if paren is not None else []))
        before = [r for r in refs if hs <= r[0] and r[1] <= m.start()]
        if before and not any(before[-1][1] <= a < m.start() and k == "screen" for a, k in screen):
            ev.append((m.start(), "speech"))
    for m in list(_PARTICIPLE_BY.finditer(s)) + list(re.finditer(r"\baccording to\s+", s, re.I)):
        agent = re.sub(r"^(?:the|a)\s+", "", s[m.end():m.end() + 80], flags=re.I)
        if not _overlaps(m.span(), skip) and evidence.speaker_ref.match(agent):
            ev.append((m.start(), "speech"))
    ev.sort()
    return ev


def _trail_credited(s: str, evidence: Evidence) -> list[tuple[int, int]]:
    """Clauses ending "— Name (mm:ss)" or "(Title — Name, mm:ss)": credited to that speaker (S-1.18.6)."""
    out = []
    low = s.lower()
    names = [n for n, _ in evidence.aliases] + [n.lower() for n in evidence.speaker_names]
    for m in re.finditer(r"\(\s*(?:[^()]*?,\s*)?" + _STAMP, s):
        inside = low[m.start():m.end()]
        lead_start = max(0, m.start() - 220)
        lead = low[lead_start:m.start()]
        if "," in inside and any(n in inside for n in names):
            cut = m.start()
        else:
            dash = max(lead.rfind(" — "), lead.rfind(" – "))
            if dash < 0 or not any(n in lead[dash:] for n in names):
                continue
            cut = lead_start + dash
            prev = max(low.rfind(" — ", 0, cut), low.rfind(" – ", 0, cut))
            if prev >= 0 and any(n in low[prev:cut] for n in names):
                cut = prev
        start = max([0] + [b for a, b in _boundaries(s) if b <= cut])
        out.append((start, cut))
    return out


def _credited(tok: Token, s: str, events: list[tuple[int, str]], trails: list[tuple[int, int]]) -> bool | None:
    """Is the detail in a part of the sentence credited to a speaker?

    True = credited, False = attributed to the screen, None = neither. The
    nearest marker before it in its clause decides (on-screen marks the
    screen, a credited speech verb credits); then the parenthetical's host
    clause; then the first marker after it in its clause; then a clause
    ending "— Name (mm:ss)"; then the nearest marker earlier in the sentence.
    "Also visible on screen" decides nothing: it says the speaker said it too.
    """
    ins, ine, hs, he = _clause_of(s, tok.start)
    marks = [(p, k) for p, k in events if k != "also"]

    def last(lo: int, hi: int) -> str | None:
        found = [k for p, k in marks if lo <= p < hi]
        return found[-1] if found else None

    k = last(ins, tok.start)
    if k is None and (ins, ine) != (hs, he):
        k = last(hs, ins - 1)
    if k is None:
        # "17,363.10, the presenter says" — but not a verb three claims later.
        after = [(p, k2) for p, k2 in marks if tok.end <= p < min(ine, tok.end + 60)
                 and not re.search(_STAMP, s[tok.end:p])]
        k = after[0][1] if after else None
    if k is None and any(a <= tok.start < b for a, b in trails):
        return True
    if k is None:
        k = last(0, hs)
    if k is None:
        return None
    return k == "speech"


def _scope(s: str, s_start: int, s_end: int, doc: _Text, evidence: Evidence, at: int | None,
           fallback: list[tuple[Source, float, float]]) -> list[tuple[Source, float, float]]:
    """The sources and moments a detail at sentence offset ``at`` can come from, likeliest first.

    The citation right after the detail in the sentence (citations follow
    their claims), then the one before it, then the sentence's other links;
    without links, sources named in the sentence with their plain timestamps;
    then ``fallback``.
    """
    links = [ln for ln in doc.links if s_start <= ln.start < s_end]
    if links:
        if at is not None:
            after = [ln for ln in links if ln.start - s_start >= at]
            before = [ln for ln in links if ln.start - s_start < at]
            ordered = after[:1] + before[::-1][:1] + [ln for ln in links if ln not in after[:1] + before[::-1][:1]]
        else:
            ordered = links
        out = []
        for ln in ordered:
            src = evidence.resolve(video_id=ln.video_id)
            if src is None:
                continue
            out.append((src, -INF, INF) if ln.seconds < 0
                       else (src, ln.seconds - CITE_BEFORE_SECONDS, ln.seconds + CITE_AFTER_SECONDS))
        if out:
            return out
    low = s.lower()
    named: list[str] = []
    for name, sids in evidence.aliases:
        if name in low:
            named.extend(sids)
    named = list(dict.fromkeys(named))
    if named:
        stamps = sorted(_PLAIN_STAMP.finditer(s), key=lambda m: (at is not None and m.start() < at, m.start()))
        out = []
        for sid in named:
            src = evidence.sources[sid]
            if not stamps:
                out.append((src, -INF, INF))
            for m in stamps:
                a = _seconds(m.group(1))
                b = _seconds(m.group(2)) if m.group(2) else a
                out.append((src, a - CITE_BEFORE_SECONDS, b + CITE_AFTER_SECONDS))
        return out
    return fallback


def _same_group(s: str, last: Token, tok: Token, a: ScreenOnly, b: ScreenOnly) -> bool:
    """Details from one span region in one clause, a few words apart: one mark covers them."""
    if a.source.sid != b.source.sid or abs(a.seconds - b.seconds) > 90:
        return False
    gap = s[last.end:tok.start]
    if re.search(r"[()]|\s[—–]\s", gap) or any(last.end <= x < tok.start for x, _ in _boundaries(s)):
        return False
    return len(re.findall(r"[A-Za-z]+", gap)) <= 8


_PHRASE_STOP = re.compile(r"[,;:.()\"”]|\s[—–]\s|\s(?:and|or|with|to|that|which|while|whereas|but|because|as|in|on|at|for|from|by)\s")


def _insert_at(s: str, tok: Token) -> int:
    """Where a mark goes after ``tok``: past its word, past a call's arguments
    ("sns.lineplot(x=x, y=y)"), and for a descriptor pair past the rest of its
    noun phrase ("a red regression line"), before trailing punctuation."""
    p = tok.end
    while p < len(s) and not s[p].isspace() and s[p] not in ",;:)(—–\"”":
        p += 1
    if p < len(s) and s[p] == "(":
        m = _CALL_ARGS.match(s, p)
        if m:
            p = m.end()
    if tok.kind == "visual_pair":
        stop = _PHRASE_STOP.search(s, p)
        limit = stop.start() if stop else len(s)
        words = list(re.finditer(r"\S+", s[p:limit]))
        if 0 < len(words) <= 3:
            p += words[-1].end()
    while p > tok.end and s[p - 1] == ".":
        p -= 1
    return p


def guard_report(html: str, evidence: Evidence) -> tuple[str, list[Rewrite]]:
    """Mark screen-only details in speaker-credited sentences, and correct
    on-screen claims about details only the speech has.

    Returns the new HTML and one ``Rewrite`` per change. A no-op when the
    corpus has no span.
    """
    if not html or not evidence.has_visual:
        return html, []
    doc = _Text(html)
    text = doc.text
    inserts: list[tuple[int, str]] = []
    deletes: list[tuple[int, int]] = []
    rewrites: list[Rewrite] = []
    prev: tuple[list[tuple[Source, float, float]], list[Token]] = ([], [])
    prev_block = -1
    # Quotations can run over several sentences ("... sns.heatmap. ... So after
    # sns.pairplot we put in data."), so they are found per paragraph.
    all_quotes = [m.span() for rx in _LONG_QUOTED for m in rx.finditer(text)]

    for s_start, s_end in _sentences(text, _alias_ranges(text, evidence)):
        s = text[s_start:s_end]
        block = text.rfind("\n", 0, s_start)
        if block != prev_block:
            prev, prev_block = ([], []), block
        quoted = _quoted_ranges(s) + [(max(a, s_start) - s_start, min(b, s_end) - s_start)
                                      for a, b in all_quotes if a < s_end and s_start < b]
        citations = _citation_ranges(s, evidence)
        names = _alias_ranges(s, evidence)
        apparatus = citations + names
        tokens = specific_tokens(s, apparatus)
        # Text inside <code> is an identifier even as one word (weak: a column name is often said).
        for a, b in ((a - s_start, b - s_start) for a, b in doc.code if s_start <= a < s_end):
            callee = re.match(r"[\w.]+", s[a:b])
            if callee is None or any(t.start < b and a < t.end for t in tokens) or _overlaps((a, b), apparatus):
                continue
            raw = callee.group(0)
            if len(_compact(raw)) >= 3 and not raw[0].isdigit():
                tokens.append(Token("identifier", raw, _norm(raw), a, a + len(raw), _structured(raw)))
        tokens.sort(key=lambda t: t.start)
        fallback = prev[0] if _PRONOUN_LEAD.match(s) else []
        own_scope = _scope(s, s_start, s_end, doc, evidence, None, fallback)
        # A title can hold a verb ("How to Analyze Data"): no markers inside names,
        # but a channel name is still the speaker a verb after it credits.
        events = [(p, k) for p, k in _events(s, quoted + citations, evidence) if not any(a <= p < b for a, b in names)]
        trails = _trail_credited(s, evidence)
        cited = {src.sid for src, _, _ in own_scope}
        strict = [m.start() for m in _STRICT_SCREEN.finditer(s) if not _overlaps(m.span(), quoted + apparatus)]

        # 1. Screen-only details in parts credited to a speaker.
        groups: list[tuple[list[Token], ScreenOnly, list[ScreenOnly]]] = []
        screen_marked: list[Token] = []
        for tok in tokens:
            if tok.kind != "quoted" and _overlaps((tok.start, tok.end), quoted):
                continue
            credit = _credited(tok, s, events, trails)
            if credit is False and tok.kind in ("number", "identifier") and tok.strong:
                ins, _, hs, _ = _clause_of(s, tok.start)
                if any(min(ins, hs) <= p < tok.start for p in strict):
                    screen_marked.append(tok)
            if not credit:
                continue
            hit = screen_only(tok, _scope(s, s_start, s_end, doc, evidence, tok.start, fallback))
            if hit is None:
                continue
            if groups and _same_group(s, groups[-1][0][-1], tok, groups[-1][1], hit):
                groups[-1][0].append(tok)
                groups[-1][2].append(hit)
            else:
                groups.append(([tok], hit, [hit]))
        for toks, hit, hits in groups:
            if not acts(toks):
                continue
            times = [format_timestamp(t) for t in sorted({h.seconds for h in hits})]
            where = times[0] if len(times) == 1 else ", ".join(times[:-1]) + " and " + times[-1]
            named = "" if hit.source.sid in cited else f" in {hit.source.label()}'s video"
            verdict = (", not spoken" if all(h.verified for h in hits) and all(verifiable(t) for t in toks)
                       else "")
            ins, ine, _, _ = _clause_of(s, toks[0].start)
            # A prose parenthetical holding only these details: "(Monday 17,363.10; ...)".
            # Never a call's arguments.
            alone = (ins > 0 and s[ins - 1] == "(" and (ins < 2 or not (s[ins - 2].isalnum() or s[ins - 2] in "_."))
                     and ine < len(s) and s[ine] == ")"
                     and all(ins <= t.start < ine for t in toks)
                     and not [t for t in tokens if ins <= t.start < ine and t not in toks])
            if alone:
                h = doc.html_after(s_start + ins)            # just inside "("
                mark = f"on screen{named} at {where}{verdict}: "
            else:
                h = doc.html_after(s_start + _insert_at(s, toks[-1]))
                mark = f" (on screen{named} at {where}{verdict})"
            if h is None:
                continue
            inserts.append((h, mark))
            rewrites.append(Rewrite("screen_detail_marked", s.strip(), [t.text for t in toks],
                                    hit.source.label(), min(x.seconds for x in hits), bool(verdict)))

        # 2. Speech presented as screen: a figure or identifier the sentence
        # explicitly puts on screen ("on screen at 03:10", "the video displays")
        # that no span of the cited source shows anywhere, while its speech says it.
        whole_cited = [(src, -INF, INF) for src in dict.fromkeys(src for src, _, _ in own_scope)]
        for tok in screen_marked:
            if not whole_cited:
                continue
            if any(in_span(tok, sp) for src, _, _ in whole_cited for sp in src.spans):
                continue
            speaker = next((src for src, _, _ in whole_cited if spoken(tok, src.speech)), None)
            if speaker is None:
                continue
            at = speaker.spoken_at(tok)
            h = doc.html_after(s_start + _insert_at(s, tok))
            if h is None:
                continue
            when = f" at {format_timestamp(at)}" if at is not None else ""
            inserts.append((h, f" (said{when}; no captured frame shows it)"))
            rewrites.append(Rewrite("speech_as_screen_marked", s.strip(), [tok.text], speaker.label(), at))

        # 3. "Also visible on screen" where no span of the cited source shows the details.
        for m in _ALSO_CLAIM.finditer(s):
            if _overlaps(m.span("phrase"), quoted + apparatus):
                continue
            _, _, hs, he = _clause_of(s, m.start("phrase"))
            referents = [t for t in tokens if t.strong and hs <= t.start < he and not _overlaps((t.start, t.end), quoted)]
            scope = whole_cited
            if not referents and len(s.split()) <= 10 and prev[1]:
                # "The output was also visible on screen." points back at the sentence before.
                referents, scope = prev[1], [(src, -INF, INF) for src in dict.fromkeys(x for x, _, _ in prev[0])]
            if not referents or not scope:
                continue
            if any(in_span(t, sp) for t in referents for src, _, _ in scope for sp in src.spans):
                continue
            said = [t for t in referents if any(spoken(t, src.speech) for src, _, _ in scope)]
            if not said:
                continue
            rest = (s[:m.start()] + s[m.end():]).strip(" .")
            if len(rest.split()) <= 4 and not tokens:
                rng = doc.html_range(s_start, s_end)          # nothing left of the sentence
            else:
                a, b = m.start(), m.end()
                lead = s[a:m.start("phrase")]
                if "(" in lead and not m.group("close"):
                    continue
                if lead.strip() in ("—", "–") and s[b:].lstrip()[:1] in ("—", "–"):
                    b += len(s[b:]) - len(s[b:].lstrip()) + 1
                rng = doc.html_range(s_start + a, s_start + b)
            if rng is None:
                continue
            deletes.append(rng)
            rewrites.append(Rewrite("screen_claim_removed", s.strip(), [t.text for t in said[:4]],
                                    scope[0][0].label(), None))
        if own_scope:
            prev = (own_scope, [t for t in tokens if t.strong])

    if not inserts and not deletes:
        return html, rewrites
    edits = [(h, h, mark) for h, mark in inserts] + [(a, b, "") for a, b in deletes]
    out = html
    for a, b, rep in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        out = out[:a] + rep + out[b:]
    return re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", out), rewrites

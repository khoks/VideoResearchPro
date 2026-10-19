"""Check that every non-English quotation traces back to its speaker's words (T-1.18.8.4). Research tool.

N-002 / T-1.16.2.5 asks the map stage to copy a non-English speaker's wording
EXACTLY into an item's ``original`` field, and the composer quotes it in the
source's script. R1 run 5 showed what a prompt-only "copy exactly" produces
when one map batch mixes eight channels: a Hindi speaker quoted in Bengali,
strings that occur nowhere in the corpus, and a report that put them in his
mouth seven times. A careful human reader missed it the first time; this
check is the mechanical replacement.

Two levels, both pure:

``audit_items``
    Every map item carrying ``original``, checked against the SPEECH of its
    own video (visual spans excluded: an ``original`` is something said).
``audit_report``
    Every run of Devanagari or Bengali text in the composed report, checked
    against all speech in the corpus. This is the deliverable-level check: a
    pipeline that drops bad ``original``s before composing passes it even if
    the map stage still invents them.

Verdicts, fixed before run 6:

``verbatim``      every fragment occurs exactly (after normalisation)
``near``          at least ``NEAR`` of every fragment's characters align with
                  one stretch of the speech; caption spelling, not invention
``visual_only``   found only in the video's ``[VISUAL @]`` spans
``other_video``   found in another video's speech, not its own
``absent``        found nowhere

and two flags that fail a quote whatever its verdict: ``script_mismatch``
when the quote's script differs from the dominant non-Latin script of its
video's speech, and ``mixed_script`` when a single word mixes letters of two
non-Latin scripts (Bengali letters spliced into a Devanagari word), which no
speaker produces and no caption contains. Normalisation is NFKC,
lower-case, native digits to ASCII, nukta and zero-width marks dropped,
punctuation (including the danda) to spaces. An ellipsis splits a quote into
fragments that are checked separately, because elision is legitimate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

NEAR = 0.8
MIN_FRAGMENT_CHARS = 6
MIN_REPORT_RUN_TOKENS = 3

_NATIVE_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯", "01234567890123456789")
_DROP = {"़", "়", "‌", "‍", "﻿"}   # nukta (Deva, Beng), ZWNJ, ZWJ, BOM
_ELLIPSIS = re.compile(r"\.{3,}|…")
_HEADER = re.compile(r"^=== (.*) \((https?://\S+?)\) ===$")
_VIDEO_ID = re.compile(r"(?:[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})")
_NATIVE_CHAR = re.compile(r"[ऀ-ॿঀ-৿]")


# --------------------------------------------------------------------------
# Normalisation and scripts
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_NATIVE_DIGITS).lower()
    out = []
    for ch in t:
        if ch in _DROP:
            continue
        cat = unicodedata.category(ch)
        out.append(" " if cat[0] in "PSZC" else ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _script(ch: str) -> str | None:
    if not ch.isalpha() and unicodedata.category(ch) not in ("Mn", "Mc"):
        return None
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return None


def dominant_native_script(text: str) -> str | None:
    """Most frequent non-Latin script among letters, or None for Latin-only text."""
    counts = Counter(s for s in map(_script, text or "") if s and s != "LATIN")
    return counts.most_common(1)[0][0] if counts else None


def mixed_script_words(text: str) -> list[str]:
    """Words whose letters come from two or more non-Latin scripts."""
    out = []
    for word in (text or "").split():
        scripts = {s for s in map(_script, word) if s and s != "LATIN"}
        if len(scripts) > 1:
            out.append(word)
    return out


def video_id(url: str | None) -> str:
    m = _VIDEO_ID.search(url or "")
    return m.group(1) if m else (url or "").split("&t=")[0].strip()


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


@dataclass
class VideoText:
    title: str
    speech: str          # normalised, captions joined
    visual: str          # normalised
    script: str | None   # dominant non-Latin script of the raw speech
    _matcher: SequenceMatcher | None = field(default=None, repr=False)

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
        Alignment tolerates the spelling the model regularises (a caption's
        "ম্যাটপ্লোটলিব এ" quoted as "ম্যাটপ্লটলিবে") without accepting a
        sentence the speaker never said.
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


def parse_transcript(text: str) -> dict[str, VideoText]:
    """Split a replay's ``transcript_annotated.txt`` into per-video speech and visual text."""
    videos: dict[str, tuple[str, list[str], list[str]]] = {}
    current: str | None = None
    for line in (text or "").splitlines():
        h = _HEADER.match(line.strip())
        if h:
            current = video_id(h.group(2))
            videos.setdefault(current, (h.group(1), [], []))
            continue
        if current is None or not line.strip():
            continue
        bucket = videos[current][2] if line.lstrip().startswith("[VISUAL @") else videos[current][1]
        bucket.append(line.strip())
    out = {}
    for vid, (title, speech, visual) in videos.items():
        raw = " ".join(speech)
        out[vid] = VideoText(title, normalise(raw), normalise(" ".join(visual)), dominant_native_script(raw))
    return out


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def fragments(quote: str) -> list[str]:
    parts = [normalise(p) for p in _ELLIPSIS.split(quote or "")]
    kept = [p for p in parts if len(p) >= MIN_FRAGMENT_CHARS]
    return kept or ([normalise(quote)] if normalise(quote) else [])


def _level(frags: list[str], haystack: str, video: VideoText | None = None) -> str | None:
    if not frags or not haystack:
        return None
    if all(f in haystack for f in frags):
        return "verbatim"
    if video is not None and all(video.coverage(f) >= NEAR for f in frags):
        return "near"
    return None


def classify(quote: str, own: str, corpus: dict[str, VideoText]) -> tuple[str, str | None]:
    """Verdict for one quote attributed to video ``own``, and the video it matched."""
    frags = fragments(quote)
    mine = corpus.get(own)
    if mine is not None:
        lvl = _level(frags, mine.speech, mine)
        if lvl:
            return lvl, own
    for vid, v in corpus.items():
        if vid != own and _level(frags, v.speech, v):
            return "other_video", vid
    if mine is not None and _level(frags, mine.visual):
        return "visual_only", own
    return "absent", None


@dataclass
class QuoteFinding:
    verdict: str
    quote: str
    video_id: str
    matched_video: str | None
    script: str | None
    video_script: str | None
    script_mismatch: bool
    mixed_script: bool = False
    channel: str = ""
    timestamp: str = ""
    category: str = ""


def _finding(quote: str, own: str, corpus: dict[str, VideoText], **extra) -> QuoteFinding:
    verdict, matched = classify(quote, own, corpus)
    q_script = dominant_native_script(quote)
    v_script = corpus[own].script if own in corpus else None
    mismatch = bool(q_script and v_script and q_script != v_script)
    return QuoteFinding(verdict, quote, own, matched, q_script, v_script, mismatch,
                        bool(mixed_script_words(quote)), **extra)


def iter_original_items(intermediates: dict):
    """Yield (category, item) for every map item that carries ``original``."""
    for batch in intermediates.get("map") or []:
        try:
            payload = json.loads(batch.get("payload_json") or "{}")
        except json.JSONDecodeError:
            continue
        for cat, items in payload.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("original"):
                    yield cat, item


def audit_items(intermediates: dict, corpus: dict[str, VideoText]) -> list[QuoteFinding]:
    return [
        _finding(
            str(item["original"]), video_id(item.get("video_url")), corpus,
            channel=str(item.get("channel_name") or ""),
            timestamp=str(item.get("timestamp_display") or ""),
            category=cat,
        )
        for cat, item in iter_original_items(intermediates)
    ]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "li", "br", "div", "h1", "h2", "h3", "h4", "td", "tr", "blockquote"):
            self.parts.append("\n")


def report_native_runs(html: str, min_tokens: int = MIN_REPORT_RUN_TOKENS) -> list[str]:
    """Maximal runs of Devanagari/Bengali words in the report text.

    A run may bridge up to two Latin tokens (code-mixed speech such as
    "plt ডট টাইটেল") but starts and ends on a native token. Runs shorter than
    ``min_tokens`` native words are single borrowed terms, not quotations.
    """
    parser = _Text()
    parser.feed(html or "")
    runs: list[str] = []
    for line in "".join(parser.parts).splitlines():
        tokens = line.split()
        i = 0
        while i < len(tokens):
            if not _NATIVE_CHAR.search(tokens[i]):
                i += 1
                continue
            j, last_native, gap = i, i, 0
            while j + 1 < len(tokens) and gap <= 2:
                j += 1
                if _NATIVE_CHAR.search(tokens[j]):
                    last_native, gap = j, 0
                else:
                    gap += 1
            span = tokens[i:last_native + 1]
            if sum(1 for t in span if _NATIVE_CHAR.search(t)) >= min_tokens:
                runs.append(" ".join(span))
            i = last_native + 1
    return runs


def audit_report(html: str, corpus: dict[str, VideoText]) -> list[QuoteFinding]:
    """Each native-script run in the report, located anywhere in the corpus speech."""
    out = []
    for run in report_native_runs(html):
        frags = fragments(run)
        verdict, matched = "absent", None
        for vid, v in corpus.items():
            lvl = _level(frags, v.speech, v)
            if lvl and (verdict == "absent" or lvl == "verbatim"):
                verdict, matched = lvl, vid
                if lvl == "verbatim":
                    break
        q_script = dominant_native_script(run)
        v_script = corpus[matched].script if matched else None
        out.append(QuoteFinding(verdict, run, matched or "", matched, q_script, v_script,
                                bool(q_script and v_script and q_script != v_script),
                                bool(mixed_script_words(run))))
    return out


FAILING = ("absent", "other_video", "visual_only")


def fails(f: QuoteFinding | dict) -> bool:
    g = f if isinstance(f, dict) else asdict(f)
    return g["verdict"] in FAILING or g["script_mismatch"] or g["mixed_script"]


def summarise(findings: list[QuoteFinding]) -> dict:
    return {
        "total": len(findings),
        "by_verdict": dict(Counter(f.verdict for f in findings)),
        "script_mismatch": sum(f.script_mismatch for f in findings),
        "mixed_script": sum(f.mixed_script for f in findings),
        "failing": sum(1 for f in findings if fails(f)),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_dir", type=Path, help="replay_visual_ab output directory")
    p.add_argument("--arms", nargs="+", default=["on", "off"])
    p.add_argument("--transcript", type=Path, default=None,
                   help="defaults to <run_dir>/transcript_annotated.txt")
    p.add_argument("--out", type=Path, default=None, help="write the full findings as JSON")
    p.add_argument("--check", action="store_true", help="exit 1 when any report-level quote fails")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    transcript = args.transcript or args.run_dir / "transcript_annotated.txt"
    corpus = parse_transcript(transcript.read_text(encoding="utf-8"))
    result: dict = {}
    report_failures = 0
    for arm in args.arms:
        arm_out: dict = {}
        inter = args.run_dir / f"{arm}.intermediates.json"
        if inter.exists():
            items = audit_items(json.loads(inter.read_text(encoding="utf-8")), corpus)
            arm_out["items"] = {"summary": summarise(items), "findings": [asdict(f) for f in items]}
        html_path = args.run_dir / f"{arm}.html"
        if html_path.exists():
            runs = audit_report(html_path.read_text(encoding="utf-8"), corpus)
            s = summarise(runs)
            report_failures += s["failing"]
            arm_out["report"] = {"summary": s, "findings": [asdict(f) for f in runs]}
        result[arm] = arm_out
        line = [f"[{arm}]"]
        for level in ("items", "report"):
            if level in arm_out:
                s = arm_out[level]["summary"]
                line.append(f"{level}: {s['total']} quotes, {s['failing']} failing {s['by_verdict']}"
                            f" script_mismatch={s['script_mismatch']} mixed_script={s['mixed_script']}")
        print("  ".join(line))
        for level in ("items", "report"):
            for f in (arm_out.get(level) or {}).get("findings", []):
                if fails(f):
                    where = f"{f['channel']} {f['timestamp']}".strip() or f["video_id"]
                    flags = (" +script" if f["script_mismatch"] else "") + (" +mixed" if f["mixed_script"] else "")
                    print(f"    {level[:-1]:6} {f['verdict']}{flags}"
                          f" [{f['script']} vs {f['video_script']}] {where}: {f['quote'][:70]}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if args.check and report_failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

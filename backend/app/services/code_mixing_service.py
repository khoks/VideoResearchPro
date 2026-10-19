"""Romanised code-mixing detection — S-1.16.2 / invention N-002.

`language_service` answers "which SCRIPTS are in this text?" exactly, and is
deliberately blind to Hindi written in Latin letters: "taaki baadme koi kasar
na reh jaye" is 100% Latin, so it reads as English. This module answers the
question that profile cannot: "which LANGUAGE is each word in?", for Latin
and Devanagari text alike.

Two detectors, measured against the same hand-labelled set
(`tests/fixtures/code_mixing/`, method in `docs/notes/`):

- `tag_tokens` — a lexicon + character n-gram tagger with a two-state Viterbi
  pass. Deterministic, free, ~0.1 ms per segment, so it can run on every chunk
  of every transcript.
- `llm_detect` — one `code_mixing_detect` call per batch of snippets (volume
  tier, reasoning off). Returns the Hindi spans verbatim; `spans_to_tags`
  maps them back onto the same tokens so both detectors are scored on one
  token sequence.

Token languages are "en", "hi" and "ne" (neutral: numbers, fillers, bare
punctuation). Hindi and Urdu are one class here: spoken Hindustani is the
same language whichever script the transcriber chose, and the pipeline's
decision — translate it, and how to quote it — does not differ between them.
"""
from __future__ import annotations

import json
import logging
import math
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.services import language_service

logger = logging.getLogger(__name__)

_LEXICON_DIR = Path(__file__).parent / "lexicons"

# Fillers and backchannels carry no language. Counting "um" as English would
# make every hesitant Hindi speaker look partly English.
_NEUTRAL_WORDS = frozenset({
    "um", "umm", "uh", "uhh", "hmm", "hm", "mm", "mmm", "ah", "aah", "oh", "ooh",
    "huh", "haha", "hahaha", "ha", "eh", "er", "erm", "ok", "okay", "yeah", "yep",
    "crore", "crores", "lakh", "lakhs", "rs", "inr",
})

# Tagger parameters. Chosen on the DEV split of the labelled set only; the
# values and the grid they were picked from are recorded in
# docs/notes/2026-10-19-code-mixing-detection.md.
HINDI_ONLY_WEIGHT = 3.0      # word in the Hindi lexicon, not in the English vocab
ENGLISH_ONLY_WEIGHT = 3.0    # word in the English vocab, not in the Hindi lexicon
AMBIGUOUS_PIVOT_ZIPF = 5.0   # ambiguous word: more frequent than this in English leans English
AMBIGUOUS_SLOPE = 1.0
AMBIGUOUS_CLIP = 1.0         # ...but never so strongly that context cannot overrule it
NGRAM_SCALE = 1.5            # out-of-vocabulary word: char n-gram log-odds per n-gram, scaled
NGRAM_CLIP = 2.5
SWITCH_PENALTY = 1.25        # cost of changing language between adjacent words
ENGLISH_START_BIAS = 0.25    # all-ambiguous text defaults to English


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    script: str          # "Latin", "Devanagari", ... or "Number"

    @property
    def norm(self) -> str:
        return self.text.lower().replace("’", "'")


def _is_word_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M")


def tokenize(text: str) -> list[Token]:
    """Words in any script, plus digit runs.

    `\\w` cannot be used: Python's regex treats Devanagari vowel signs
    (category Mc/Mn) as non-word characters and splits "कांसेप्ट" into four
    pieces. An apostrophe between letters stays inside the word ("don't").
    """
    tokens: list[Token] = []
    i, n = 0, len(text or "")
    while i < n:
        ch = text[i]
        if _is_word_char(ch):
            j = i + 1
            while j < n and (
                _is_word_char(text[j])
                or (text[j] in "'’" and j + 1 < n and _is_word_char(text[j + 1]))
            ):
                j += 1
            word = text[i:j]
            script = language_service.dominant_script(word) or "Other"
            tokens.append(Token(word, i, j, script))
            i = j
        elif ch.isdigit():
            j = i + 1
            while j < n and text[j].isdigit():
                j += 1
            tokens.append(Token(text[i:j], i, j, "Number"))
            i = j
        else:
            i += 1
    return tokens


# --- lexicons ----------------------------------------------------------------

@dataclass(frozen=True)
class _Lexicons:
    hindi: frozenset[str]
    english_zipf: dict[str, float]
    ngram_hi: dict[str, float]
    ngram_en: dict[str, float]
    ngram_hi_unseen: float
    ngram_en_unseen: float


def _read_words(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.split("\t")[0].lower())
    return out


def _char_ngrams(word: str, n_min: int = 2, n_max: int = 4) -> list[str]:
    padded = f"^{word}$"
    return [
        padded[i:i + n]
        for n in range(n_min, n_max + 1)
        for i in range(len(padded) - n + 1)
    ]


def _ngram_model(words: Iterable[tuple[str, float]]) -> tuple[dict[str, float], float]:
    """Laplace-smoothed log-probabilities of char n-grams, weighted by word."""
    counts: Counter[str] = Counter()
    for w, weight in words:
        for g in _char_ngrams(w):
            counts[g] += weight
    total = sum(counts.values())
    vocab = len(counts) + 1
    return (
        {g: math.log((c + 1) / (total + vocab)) for g, c in counts.items()},
        math.log(1 / (total + vocab)),
    )


@lru_cache(maxsize=1)
def lexicons() -> _Lexicons:
    hindi = frozenset(_read_words(_LEXICON_DIR / "hindi_romanised.txt"))
    total = 1.0
    counts: dict[str, int] = {}
    for line in (_LEXICON_DIR / "english_vocab.tsv").read_text(encoding="utf-8").splitlines():
        if line.startswith("# total_tokens"):
            total = float(line.split("\t")[1])
            continue
        if not line or line.startswith("#"):
            continue
        word, count = line.split("\t")
        counts[word] = int(count)
    # Conversational and texting English a tech-talk corpus underrepresents
    # ("sir", "plz", "bro"), counted as mid-frequency words.
    for word in _read_words(_LEXICON_DIR / "english_supplement.txt"):
        counts.setdefault(word, max(1, int(total * 1e-5)))
    # Zipf scale: log10 of frequency per billion words. "the" ~7.6, a word
    # seen twice in a million ~3.3.
    english_zipf = {w: math.log10(c / total * 1e9) for w, c in counts.items()}
    # The n-gram model sees each English type once per order of magnitude of
    # its frequency, so "the" does not drown out the orthography of rarer
    # words, and each Hindi type with the weight of a mid-frequency word.
    ngram_en, en_unseen = _ngram_model(
        (w, 1.0 + math.log10(c)) for w, c in counts.items() if w not in hindi
    )
    ngram_hi, hi_unseen = _ngram_model((w, 2.0) for w in hindi)
    return _Lexicons(hindi, english_zipf, ngram_hi, ngram_en, hi_unseen, en_unseen)


def _ngram_log_odds(word: str, lex: _Lexicons) -> float:
    """Mean per-n-gram log-odds of Hindi over English for an unseen word."""
    grams = _char_ngrams(word)
    if not grams:
        return 0.0
    s = sum(
        lex.ngram_hi.get(g, lex.ngram_hi_unseen) - lex.ngram_en.get(g, lex.ngram_en_unseen)
        for g in grams
    )
    return s / len(grams)


def emission(word: str, lex: _Lexicons | None = None) -> float:
    """Evidence for Hindi over English for one lower-cased Latin word.

    Positive favours Hindi. Four cases: Hindi-only, English-only, ambiguous
    (in both lists — "to", "main", "par", "hi"), and unseen. An ambiguous
    word's lean comes from how common it is in English: "the" is so frequent
    in English that only strong context makes it the Hindi "the" (were),
    while "se" is rare enough in English that it leans Hindi.
    """
    lex = lex or lexicons()
    in_hi = word in lex.hindi
    zipf = lex.english_zipf.get(word)
    if in_hi and zipf is None:
        return HINDI_ONLY_WEIGHT
    if zipf is not None and not in_hi:
        return -ENGLISH_ONLY_WEIGHT
    if in_hi and zipf is not None:
        return max(-AMBIGUOUS_CLIP, min(AMBIGUOUS_CLIP,
                   (AMBIGUOUS_PIVOT_ZIPF - zipf) * AMBIGUOUS_SLOPE))
    lo = _ngram_log_odds(word, lex) * NGRAM_SCALE
    return max(-NGRAM_CLIP, min(NGRAM_CLIP, lo))


def _viterbi(scores: list[float]) -> list[str]:
    """Two-state best path: per-word evidence vs a cost for every switch.

    Code-switching happens at phrase boundaries, not between every word; the
    switch penalty is what lets an ambiguous "to" inside a Hindi clause read
    as Hindi and the same "to" inside an English clause read as English.
    """
    if not scores:
        return []
    states = ("en", "hi")
    # score of being in state s: +e/2 for hi, -e/2 for en
    prev = {"en": -scores[0] / 2 + ENGLISH_START_BIAS, "hi": scores[0] / 2}
    back: list[dict[str, str]] = []
    for e in scores[1:]:
        cur, ptr = {}, {}
        for s in states:
            gain = e / 2 if s == "hi" else -e / 2
            stay = prev[s]
            switch = prev["hi" if s == "en" else "en"] - SWITCH_PENALTY
            if stay >= switch:
                cur[s], ptr[s] = stay + gain, s
            else:
                cur[s], ptr[s] = switch + gain, ("hi" if s == "en" else "en")
        back.append(ptr)
        prev = cur
    last = max(states, key=lambda s: prev[s])
    path = [last]
    for ptr in reversed(back):
        path.append(ptr[path[-1]])
    return list(reversed(path))


def tag_tokens(text: str) -> list[tuple[Token, str]]:
    """Language per token: the lexicon detector.

    Latin words go through the lexicon + n-gram + Viterbi pass. Words in a
    non-Latin script are tagged from the script (Devanagari and Arabic-script
    words are Hindi/Urdu), except the closed class of English function words
    as Hindi ASR spells them (`ENGLISH_IN_DEVANAGARI`: इज, टू, द, एंड...).
    That leaves one known blind spot, measured on the labelled set rather
    than assumed away: English CONTENT words transcribed in Devanagari
    ("मशीन लर्निंग"), which YouTube's Hindi auto-captions produce constantly.
    """
    lex = lexicons()
    tokens = tokenize(text)
    tags: list[str] = ["ne"] * len(tokens)
    # Viterbi runs over each maximal run of Latin words. Neutral tokens are
    # skipped without breaking a run; a native-script word breaks it.
    runs: list[list[int]] = [[]]
    for i, tok in enumerate(tokens):
        if tok.script == "Number" or tok.norm in _NEUTRAL_WORDS:
            continue
        if tok.script == "Latin":
            runs[-1].append(i)
            continue
        if tok.script in ("Devanagari", "Arabic", "Gurmukhi"):
            tags[i] = "en" if tok.norm in ENGLISH_IN_DEVANAGARI else "hi"
        runs.append([])
    for run in runs:
        path = _viterbi([emission(tokens[i].norm, lex) for i in run])
        for i, lang in zip(run, path):
            tags[i] = lang
    return list(zip(tokens, tags))


def shares(tags: Iterable[str]) -> dict[str, Any]:
    """Token counts and the Hindi share among language-bearing tokens."""
    c = Counter(tags)
    en, hi = c.get("en", 0), c.get("hi", 0)
    lang = en + hi
    return {
        "en_tokens": en,
        "hi_tokens": hi,
        "hi_share": round(hi / lang, 4) if lang else 0.0,
    }


def profile_text(text: str) -> dict[str, Any]:
    """Lexicon-detector profile of one span: token counts and Hindi share."""
    return shares(tag for _, tag in tag_tokens(text))


# --- matrix vs embedded language (T-1.16.2.2) ----------------------------------
#
# Proportion says how many words each language contributes; it cannot say
# which language the sentence is IN. "so model ko train karna padta hai with
# the data" is 64% English words in Hindi grammar. Myers-Scotton's Matrix
# Language Frame model gives the test: the matrix language supplies the
# SYSTEM morphemes — auxiliaries, inflected light verbs, postpositions, case
# forms, negation, conjunctions — while the embedded language supplies content
# words. So the matrix is decided by a vote of closed-class words, and content
# words do not vote at all.
#
# Verbal morphemes (auxiliaries, inflected light verbs) carry the clause's
# tense and agreement and count double. On the DEV split the weight made no
# difference between 1 and 3; 2 follows the theory.
#
# The lists are closed classes, so they live here rather than in a lexicon
# file. Devanagari entries matter twice over: Hindi function words written in
# Devanagari vote Hindi, and English function words written in Devanagari
# ("इट इज नॉट", "टू द") vote English even though the tagger calls every
# Devanagari word Hindi — the one place the lexicon detector can see English
# in Devanagari, and the place it matters most, because an English-matrix
# sentence must not be quoted as Hindi.

HINDI_VERBAL_MORPHEMES = frozenset({
    "hai", "hain", "hei", "he", "h", "hoon", "hun", "hu", "ho", "tha", "thi", "the", "thee",
    "raha", "rahi", "rahe", "rha", "rhi", "rhe", "hota", "hoti", "hote", "hoga", "hogi", "honge",
    "hua", "hui", "hue", "gaya", "gayi", "gaye", "gya", "gyi", "sakta", "sakti", "sakte", "skta",
    "sake", "chuka", "chuki", "chuke", "jaata", "jata", "jaati", "jati", "jaate", "jate", "jaye",
    "jaaye", "jayega", "jaega", "paata", "paate", "padta", "padti", "padte", "padega",
    "kar", "karna", "karne", "karni", "karta", "karti", "karte", "kare", "karo", "karu", "karun",
    "karenge", "karega", "karegi", "kiya", "kiye", "kia", "krna", "krte", "krta", "kro", "kr",
    "kra", "karke", "diya", "diye", "dena", "dete", "deta", "lena", "liya", "lete", "leta",
    "kariye", "kijiye", "dijiye", "dijye",
    "है", "हैं", "हूं", "हूँ", "हो", "था", "थी", "थे", "रहा", "रही", "रहे", "होता", "होती", "होते",
    "होगा", "होगी", "होंगे", "हुआ", "हुई", "हुए", "गया", "गई", "गए", "सकता", "सकती", "सकते",
    "जाता", "जाती", "जाते", "कर", "करना", "करने", "करता", "करती", "करते", "करें", "करो", "किया",
    "किए", "दिया", "दिए", "लिया", "लेते", "देते", "पड़ता", "चाहिए",
})
HINDI_FUNCTION_MORPHEMES = frozenset({
    "ka", "ki", "ke", "ko", "se", "mein", "me", "mai", "par", "pe", "tak", "ne", "liye", "wala",
    "wali", "wale", "waala", "waale", "nahi", "nahin", "nai", "nhi", "na", "mat", "bhi", "toh",
    "to", "hi", "aur", "ya", "lekin", "magar", "jo", "agar", "taaki", "kyunki", "kyuki", "isliye",
    "mujhe", "humein", "hume", "tumhe", "usko", "isko", "unko", "inko", "aapko", "apko", "mera",
    "meri", "mere", "hamara", "tumhara", "aapka", "aapki", "aapke", "apka", "apki", "apke", "uska",
    "uski", "uske", "iska", "iski", "iske", "unka", "unki", "unke", "main", "hum", "tum", "aap",
    "wo", "woh", "vo", "ye", "yeh", "kya", "kaise", "kaun", "kon", "koi", "kuch", "k", "m",
    "का", "की", "के", "को", "से", "में", "पर", "पे", "तक", "ने", "लिए", "वाला", "वाली", "वाले",
    "नहीं", "ना", "न", "भी", "तो", "ही", "और", "या", "लेकिन", "जो", "अगर", "ताकि", "क्योंकि", "कि",
    "मुझे", "हमें", "तुम्हें", "उसको", "इसको", "उनको", "आपको", "मेरा", "मेरी", "मेरे", "आपका", "आपकी",
    "आपके", "उसका", "उसकी", "उसके", "इसका", "इसकी", "इसके", "मैं", "हम", "तुम", "आप", "वो", "वह",
    "ये", "यह", "क्या", "कैसे", "कौन", "कोई", "कुछ",
})
ENGLISH_VERBAL_MORPHEMES = frozenset({
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "have", "has",
    "had", "will", "would", "can", "could", "should", "shall", "may", "might", "must", "don't",
    "doesn't", "didn't", "isn't", "aren't", "wasn't", "won't", "can't", "i'm", "it's", "that's",
    "you're", "we're", "they're", "i've", "i'll", "let's", "r",
    "इज", "आर", "वाज", "बी", "शुड", "विल", "कैन", "डू", "डोंट", "हैव",
})
ENGLISH_FUNCTION_MORPHEMES = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "of", "to", "in", "on", "at", "for",
    "with", "by", "from", "about", "into", "i", "you", "he", "she", "it", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "its", "our", "their", "who", "which",
    "what", "and", "but", "or", "so", "because", "if", "when", "than", "not", "no", "there",
    "u", "ur", "n", "nd",
    # Not इन (in), आई (I) or दे (they): each is also a common Hindi word
    # ("these", "came", "give").
    "द", "दि", "ऑफ", "टू", "ऑन", "फॉर", "विद", "एंड", "बट", "ऑर", "दैट", "दिस", "इट", "यू",
    "वी", "माय", "योर", "नॉट", "इफ",
})
VERBAL_MORPHEME_WEIGHT = 2.0

# English function words as YouTube's Hindi ASR spells them. Tagged English
# by `tag_tokens` — a closed class, so this is exact where it applies, and it
# is what lets an English-matrix sentence written in Devanagari ("इट इज नॉट
# बीइंग एक्सप्लीसिटली प्रोग्राम") be recognised as English at all. English
# CONTENT words in Devanagari (मशीन, लर्निंग) remain the measured blind spot.
ENGLISH_IN_DEVANAGARI = frozenset(
    w for w in ENGLISH_VERBAL_MORPHEMES | ENGLISH_FUNCTION_MORPHEMES
    if language_service.dominant_script(w) == "Devanagari"
)


def morpheme_votes(tagged: list[tuple[Token, str]]) -> dict[str, float]:
    """System-morpheme vote per language over already-tagged tokens.

    A word votes only for the language the tagger gave it, so an ambiguous
    "to" or "the" votes Hindi inside a Hindi clause and English inside an
    English one.
    """
    votes = {"en": 0.0, "hi": 0.0}
    for tok, tag in tagged:
        w = tok.norm
        if tag == "hi":
            if w in HINDI_VERBAL_MORPHEMES:
                votes["hi"] += VERBAL_MORPHEME_WEIGHT
            elif w in HINDI_FUNCTION_MORPHEMES:
                votes["hi"] += 1
        elif tag == "en":
            if w in ENGLISH_VERBAL_MORPHEMES:
                votes["en"] += VERBAL_MORPHEME_WEIGHT
            elif w in ENGLISH_FUNCTION_MORPHEMES:
                votes["en"] += 1
    return votes


def matrix_language(tagged: list[tuple[Token, str]]) -> str:
    """"en", "hi", or "none" when the span has no language-bearing word.

    A tied vote (including no system morphemes at all, as in a bare noun
    phrase) falls back to the majority of words.
    """
    votes = morpheme_votes(tagged)
    if votes["en"] != votes["hi"]:
        return "hi" if votes["hi"] > votes["en"] else "en"
    s = shares(tag for _, tag in tagged)
    if not (s["en_tokens"] or s["hi_tokens"]):
        return "none"
    return "hi" if s["hi_tokens"] > s["en_tokens"] else "en"


def analyse_span(text: str) -> dict[str, Any]:
    """Proportion AND structure of one span — the measurement N-002 renders from.

    ``{en_tokens, hi_tokens, hi_share, matrix, embedded}``: ``matrix`` is the
    language supplying the grammar, ``embedded`` the other language when it
    contributes any words (None for a monolingual span).
    """
    tagged = tag_tokens(text)
    out = shares(tag for _, tag in tagged)
    m = matrix_language(tagged)
    other = {"en": "hi", "hi": "en"}.get(m)
    present = other and out[f"{other}_tokens"] > 0
    out["matrix"] = m
    out["embedded"] = other if present else None
    return out


# --- LLM detector -------------------------------------------------------------

LLM_BATCH_SIZE = 25
LLM_MAX_COMPLETION_TOKENS = 4000


def parse_llm_payload(raw: str, n_snippets: int) -> list[dict] | None:
    """Validate `code_mixing_detect` JSON into one entry per snippet.

    Tolerates code fences and prose around the object. A snippet the model
    skipped comes back as `None` so the caller can tell "no Hindi" from
    "not answered".
    """
    content = (raw or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        end = -1 if lines and lines[-1].startswith("```") else len(lines)
        content = "\n".join(lines[1:end]).strip()
    if not content.startswith("{"):
        a, b = content.find("{"), content.rfind("}")
        if a < 0 or b < a:
            return None
        content = content[a:b + 1]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    items = data.get("snippets") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    out: list[dict | None] = [None] * n_snippets
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if not 0 <= i < n_snippets:
            continue
        spans = item.get("hi") or []
        if not isinstance(spans, list):
            spans = []
        matrix = str(item.get("matrix") or "none").lower()
        if matrix not in ("en", "hi", "none"):
            matrix = "none"
        out[i] = {"hi": [str(s) for s in spans if str(s).strip()], "matrix": matrix}
    return out


# How many unmatched tokens may sit between two consecutive words of a span.
# The model is asked for contiguous runs, but on Devanagari text it sometimes
# returns all the Hindi words of a snippet as ONE span with the English words
# dropped ("खोलेंगे तो वहां भी आपको उसी से जुड़े" for "... उसी प्रोडक्ट से
# जुड़े ..."). The words are still the right words, in order; only the
# contiguity is wrong. 8 covers the longest English run seen inside Hindi in
# the labelled set (7 words).
SPAN_MAX_GAP = 8


def _match_span(norms: list[str], span: list[str], start: int, max_gap: int) -> list[int] | None:
    """Positions of `span` in `norms` as an in-order subsequence from `start`,
    with at most `max_gap` skipped tokens between consecutive words."""
    for i in range(start, len(norms)):
        if norms[i] != span[0]:
            continue
        pos, j = [i], i
        for word in span[1:]:
            k = j + 1
            while k < len(norms) and k - j - 1 <= max_gap and norms[k] != word:
                k += 1
            if k >= len(norms) or norms[k] != word or k - j - 1 > max_gap:
                break
            pos.append(k)
            j = k
        else:
            return pos
    return None


def spans_to_tags(
    text: str, spans: list[str], max_gap: int = SPAN_MAX_GAP
) -> tuple[list[tuple[Token, str]], int]:
    """Map the model's Hindi spans back onto `tokenize(text)`.

    Each span is matched left to right as an in-order token subsequence, so a
    repeated word is only marked where the model put it, and only the span's
    own words are marked — skipped words stay English. `max_gap=0` is the
    strict contiguous match. Returns the tags and the number of spans that
    could not be located (the model paraphrased or re-spelt them) — a
    reliability figure the evaluation reports.
    """
    tokens = tokenize(text)
    tags = [
        "ne" if (t.script == "Number" or t.norm in _NEUTRAL_WORDS) else "en"
        for t in tokens
    ]
    norms = [t.norm for t in tokens]
    cursor, missed = 0, 0
    for span in spans:
        span_norms = [t.norm for t in tokenize(span)]
        if not span_norms:
            continue
        pos = _match_span(norms, span_norms, cursor, max_gap)
        if pos is None:
            pos = _match_span(norms, span_norms, 0, max_gap)
        if pos is None:
            missed += 1
            continue
        for k in pos:
            if tags[k] != "ne":
                tags[k] = "hi"
        cursor = pos[-1] + 1
    return list(zip(tokens, tags)), missed


def llm_detect(texts: list[str], llm: Any | None = None) -> list[dict | None]:
    """Run `code_mixing_detect` over snippets in batches.

    Returns one `{"hi": [...spans], "matrix": ...}` per snippet, or None
    where a batch failed or the model skipped the snippet. Never raises:
    a detection failure must not fail an ingest.
    """
    from langchain_core.messages import HumanMessage

    from app.agents.prompts.code_mixing_prompts import CODE_MIXING_DETECT_PROMPT
    from app.services.llm_service import get_llm_for, response_text

    results: list[dict | None] = [None] * len(texts)
    client = llm
    for b in range(0, len(texts), LLM_BATCH_SIZE):
        batch = texts[b:b + LLM_BATCH_SIZE]
        numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(batch))
        prompt = CODE_MIXING_DETECT_PROMPT.format(snippets=numbered)
        try:
            client = client or get_llm_for(
                "code_mixing_detect", temperature=0.0,
                max_tokens=LLM_MAX_COMPLETION_TOKENS,
            )
            response = client.invoke([HumanMessage(content=prompt)])
            parsed = parse_llm_payload(response_text(response), len(batch))
        except Exception:
            logger.exception("code_mixing_detect failed for batch at %d", b)
            continue
        if parsed is None:
            logger.warning("code_mixing_detect returned unparseable JSON at %d", b)
            continue
        results[b:b + len(batch)] = parsed
    return results

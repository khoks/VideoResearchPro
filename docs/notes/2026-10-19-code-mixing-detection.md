---
status: measurement note
captured: 2026-10-19
relates_to: S-1.16.2 (E-1.16, R5), invention N-002, D-066, D-080
---

# Code-mixing detection: method and results (S-1.16.2)

This note records how the romanised code-mixing detector was chosen
(T-1.16.2.1): what was measured, on what data, and the numbers. Later tasks
of the story append their own sections below.

## 1. What the pipeline actually receives

The brief assumed Hinglish videos would arrive as romanised text ("taaki
baadme koi kasar..."). Three topic jobs on the dev backend, built to find
Hinglish speech, showed otherwise:

| Job | Topic | Videos approved | What came back |
|---|---|---|---|
| `fed18081` | machine learning explained in Hinglish | 5 | 3 Devanagari (`hi` auto-captions), 1 **Bengali** (`bn`), 1 unavailable |
| `84a13d8d` | Indian startup founder podcast, Hinglish | 4 | 3 English (`en` auto-captions), 1 Devanagari |
| `f3532fa1` | personal finance and career advice, Hinglish | 5 | held back, unread, for the end-to-end evaluation (T-1.16.2.6) |

- **YouTube captions Hindi speech in Devanagari, English words included.**
  "इट इज नॉट बीइंग एक्सप्लीसिटली प्रोग्राम" is the speaker saying "it is not
  being explicitly program(med)". Script profiling sees 100% Devanagari, so
  the English inside it is invisible — the mirror image of the romanised gap.
- **English auto-captions of Indian podcasts are English-dominant.** The
  lexicon tagger found a Hindi share of 0.0–0.3% across six of them. YouTube
  picks the caption language from the audio, so a Hindi-heavy episode gets a
  `hi` track, not a romanised `en` one.
- **A Bengali auto-dub track was ingested for a Hindi video.** `1v3_AQ26jZ0`
  lists `bn(auto)`, `en-US(auto)` and `hi(auto)`; `_fetch_transcript_once`
  prefers `en`/`en-auto` (no match for `en-US`) and then takes the first
  listed track. The library now holds a machine-dubbed Bengali transcript of
  a Hindi lecture. Filed as a follow-up; not fixed here.
- **Whisper could not run**: yt-dlp is bot-walled (HTTP 403 on all three
  player clients) and no cookie source is configured.

Real romanised Hinglish does exist next to these videos: in their **comments**,
which are overwhelmingly typed Hinglish ("Sir ye aapne bhut ache se samjhaya
h mene ek our example bhi socha h..."). That is the text people write in
Reddit threads, tweets, chats and the personal-brain sources of
[L3](../personal-brain.md), so the labelled set uses comments for the
romanised part and the jobs' captions for the rest.

## 2. The labelled set

`backend/tests/fixtures/code_mixing/labelled_units.json`, 300 units.

| Source | Units | What it tests |
|---|---|---|
| `comment` — top-level YouTube comments on 11 of the jobs' Hinglish videos (Data API v3, relevance order) | 180 | romanised Hindi as people type it, and Indian English |
| `caption_latin_indian` — 3 founder podcasts' `en` captions | 50 | false positives on Indian English speech (names, crores, "yaar") |
| `caption_devanagari` — 4 Hindi-ASR transcripts | 50 | English written in Devanagari |
| `caption_english` — 20 random English library transcripts | 20 | false positives on the library's dominant content |

Captions were cut into windows of 12–30 words at segment boundaries; comments
under 5 words were dropped and longer ones cut at 40 words. **Sampling never
consulted a detector** — selecting units that "look mixed" would drop exactly
the cases a detector misses and inflate its recall. Seeded (`20261019`);
split a third DEV / two thirds TEST, stratified by source.

**Labels are per token.** Each unit carries an annotation: `{...}` Hindi/Urdu,
`|...|` English (inside Devanagari units), `<...>` neither; unmarked words take
the unit's base language. `code_mixing_eval.gold_tags` turns it into one tag
per token and refuses any annotation that does not strip back to the exact
source text. Conventions:

- English words inside Hindi grammar are English ("video", "train", मशीन).
  Morphologically Hindi-inflected English stems are English too (मशीनों).
- Names of people, places, companies, products and languages are neither,
  and are not scored. So are numbers, fillers (um, ok) and crore/lakh, which
  are standard Indian English.
- Texting forms take the language they abbreviate: `h` = hai, `m` = main,
  `n` = and, `u` = you.
- Hindi and Urdu are one class (spoken Hindustani).
- **Matrix** is the language supplying most of the unit's grammatical frame
  — function words, auxiliaries, postpositions, verb inflections (the system
  morphemes of Myers-Scotton's Matrix Language Frame). The user's example is
  `en`; "model ko train karna padta hai" is `hi`.

Totals: 4,803 tokens — 3,625 English, 945 Hindi, 233 neutral. 42 Latin units
contain Hindi (41 mixed, 1 all-Hindi); 207 are all English; all 50 Devanagari
units mix in English words.

**Who labelled it.** Claude (Opus 5.5), reading every unit, not a native
speaker. The detector being evaluated is a different and much smaller model,
but the labels still carry one model's judgement, and the hardest calls
(garbled ASR such as "kaishking", whether a lone "sir" belongs to the Hindi
clause) are judgement. A native-speaker spot check of the 42 Hindi-bearing
Latin units and 10 Devanagari units would cost about half an hour and is the
first thing to do if these numbers are ever load-bearing. Recorded as an open
question in [D-080](../decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19).

## 3. The two detectors

**Lexicon tagger** (`code_mixing_service.tag_tokens`). Each Latin word gets a
score for Hindi over English:

- in the Hindi lexicon only (`lexicons/hindi_romanised.txt`, ~1,300 forms
  with spelling variants, written from general knowledge before the labelled
  set was read): +3;
- in the English vocabulary only (`english_vocab.tsv`: 8,776 words seen in at
  least two of the library's 208 English transcripts, plus a 230-word
  conversational supplement): −3;
- in both ("to", "main", "me", "par", "the"): a lean from the word's English
  frequency, clipped at ±1 so that context decides;
- in neither: a character 2–4-gram log-odds model trained on the two lists,
  clipped at ±2.5.

A two-state Viterbi pass then charges 1.25 for every language switch, which
is what makes "to" Hindi in "mujhe to pata hi nahi" and English in "I want to
go". Devanagari and Arabic-script words are Hindi by script. Cost: about 1 ms
per unit, no network.

**LLM detector** (`code_mixing_service.llm_detect`, use case
`code_mixing_detect`, `gpt-5.6-luna`, reasoning off). 25 numbered snippets
per call; the model returns each snippet's Hindi runs verbatim plus the
matrix language, and `spans_to_tags` maps the runs back onto the same tokens.
The prompt was written before any result was seen and was not changed.

**Tuning used DEV only.** A grid over the switch penalty, ambiguity clip,
n-gram scale and lexicon weights (90 settings) had a plateau at DEV token F1
0.971; the default is the plateau's centre, not its edge. Thirteen texting
forms (`he`, `h`, `k`, `m`, `konse`...) and two English misspellings were
added after reading DEV errors, in marked sections of the lexicon files. TEST
was not read until both detectors were frozen.

## 4. Results (TEST, held out: 168 Latin units, 34 Devanagari)

Token-level scores are for the Hindi class over gold-English and gold-Hindi
tokens; brackets are Wilson 95% intervals.

| | Latin token P | Latin token R | Latin F1 | Latin units with Hindi caught | English units flagged | Devanagari token P | Devanagari token R | Devanagari F1 |
|---|---|---|---|---|---|---|---|---|
| Lexicon | **0.929** [0.88, 0.96] | 0.890 [0.84, 0.93] | **0.909** | 28 / 30 | 4 / 138 | 0.767 [0.73, 0.80] | 1.000 | 0.868 |
| LLM | 0.803 [0.74, 0.85] | 0.895 [0.84, 0.93] | 0.847 | 29 / 30 | 0 / 138 | **0.964** [0.94, 0.98] | 0.966 [0.94, 0.98] | **0.965** |
| LLM, spans taken literally | 0.803 | 0.895 | 0.847 | 29 / 30 | 0 / 138 | 0.951 | 0.483 | 0.640 |

Mean absolute error of the per-unit Hindi share: lexicon 0.014 Latin / 0.236
Devanagari; LLM 0.019 / 0.052. Matrix language (LLM only so far): 60 of 62
mixed TEST units right (0.968); both misses were English-matrix units read
as Hindi. DEV, for reference: lexicon Latin F1 0.971, LLM 0.920.

The last row matters. On some Devanagari batches the model listed all of a
snippet's Hindi words as one span with the English words dropped, against the
instruction to return contiguous runs. Taken literally, those spans match
nothing and the detector "finds" no Hindi in 19 of 34 units. The mapper now
matches spans as in-order subsequences with at most 8 skipped words between
them, which keeps the skipped words English. That repairs the output format
and does not use the labels.

**Cost.** The LLM pass used 2.6 input and 1.3 output tokens per word: about
24K in and 12K out for an hour of speech, or 2.5M in and 1.3M out for the
947K-word reference corpus, at ~4.6 s per 25-snippet call. The lexicon
tagger costs nothing.

## 5. What the errors look like

- **Lexicon, Latin.** Missed Hindi is mostly ambiguous function words in
  short Hindi stretches ("me", "main", "is", "per") and words not in the list
  ("gol gol gol", "bi", "iss"). False Hindi is mostly acronyms inside Hindi
  clauses (BCA, MBA, DSA, FMCG, which the switch penalty absorbs) and
  elongated spellings ("Yeaah", "Tadaaaa") that the n-gram model reads as
  Hindi. The four flagged English units each have exactly one false word.
- **Lexicon, Devanagari.** By construction every Devanagari word is Hindi, so
  मशीन लर्निंग counts as Hindi. Recall is perfect and precision pays for it.
- **LLM, Latin.** The model ignores "an English word ends the Hindi run" and
  returns whole clauses ("...hall leke unko fitness class start Karu but
  actually problem yeh hai ki..."), so English insertions count as Hindi. It
  also leaves out address terms such as "bhai" and "bhaiya", probably
  reading them as names.

## 6. Decision

The lexicon tagger is the production detector for romanised text: it is more
precise at the same recall, with intervals that do not overlap on precision,
and it is free and deterministic enough to run on every chunk. The LLM
detector stays registered as `code_mixing_detect`. It is the reference the
evaluation harness compares against and the better instrument for English
written in Devanagari, but it is not on the ingest path. Full reasoning and
alternatives:
[D-080](../decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19).

**Known limits, measured rather than assumed away:**

- English in Devanagari is invisible to the lexicon tagger (precision 0.767
  on those units). Where it matters for N-002 is an English-matrix sentence
  written in Devanagari, which should render as plain English. None of the 50
  labelled Devanagari units had an English matrix, so the error changes the
  Hindi share but not the rendering decision on this data.
- 30 Hindi-bearing Latin TEST units give wide unit-level intervals (lexicon
  0.79–0.98, LLM 0.83–0.99). The token-level results are the firmer ones.
- Single labeller, not a native speaker (section 2).

## Reproduce

```bash
cd backend
./venv/Scripts/python scripts/eval_code_mixing.py --split test
./venv/Scripts/python scripts/eval_code_mixing.py --llm --split all   # live; rewrites the cache
./venv/Scripts/python -m pytest tests/test_services/test_code_mixing_service.py -q
```

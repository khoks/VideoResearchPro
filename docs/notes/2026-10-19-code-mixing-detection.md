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

## 7. Matrix and embedded language (T-1.16.2.2)

N-002's distinguishing claim is that proportion is not enough: the language
supplying the GRAMMAR (matrix) must be told apart from the one supplying
VOCABULARY (embedded). The labelled set tests that claim directly. Among the
90 mixed units, **10 (11%) have mostly English words in Hindi grammar**
("Logistics and shipping me bnao bhai kisi channel ne nhi kra", "एडिशन और
उसको हमने इनपुट दिया टू द मशीन"). A rule that reads the language off the
word count calls every one of them English. No unit went the other way.

**Method.** The Matrix Language Frame model says the matrix language supplies
the system morphemes: auxiliaries, inflected light verbs, postpositions,
case-marked pronouns, negation and conjunctions. `matrix_language` therefore
takes a vote of closed-class words only, each counted for the language the
tagger gave it, so an ambiguous "to" votes Hindi inside a Hindi clause.
Verbal morphemes count double, because they carry tense and agreement. A tie,
or a bare noun phrase with no system morphemes, falls back to word majority.
Content words never vote.

The closed lists include English function words as Hindi ASR spells them
(इज, टू, द, एंड, दैट: 29 forms), and the tagger now tags those as English.
This is the one place the lexicon detector can see English inside
Devanagari, and it matters most where it works: "इट इज नॉट बीइंग एक्सप्लीसिटली
प्रोग्राम" now reads as English-matrix. Three candidates were left out
because each is also a common Hindi word: इन ("these"), आई ("came"), दे
("give").

**Results (mixed units only; 28 DEV, 62 TEST).**

| | DEV | TEST |
|---|---|---|
| Word majority (proportion only) | 0.929 | 0.855 |
| System-morpheme vote | 0.964 | **0.952** |
| LLM (`code_mixing_detect`, reference) | 1.000 | 0.968 |

On TEST every baseline miss (9 of 9) is a Hindi-grammar sentence with mostly
English words, read as English. The vote recovers 7 of them. It gets three
units wrong. "Product ka quality ho jhaant bhar... Noise is worse than Boat"
is two clauses with opposite frames. "Great job hitesh! ... Accha music add
kiya btw" has its English frame in verbless fragments, so it has no English
system morphemes. "Logistics and shipping me bnao..." is a tie broken by
word count. The verbal weight made no difference between 1 and 3 on DEV.

**Side effect on detection.** Tagging the Devanagari function words as English
raises Devanagari token precision from 0.767 to 0.792 on TEST, with recall
still 1.000. The Latin scores do not change. English content words written in
Devanagari remain the measured blind spot.

**What "per span" means here.** `analyse_span(text)` returns `{en_tokens,
hi_tokens, hi_share, matrix, embedded}` for whatever span it is given: a
caption window, a comment, a sentence or a chunk. A span that switches frame
mid-way, as the user's example does around its embedded Hindi clauses, gets
the frame that dominates its system morphemes (`en` for the user's example).
Finer clause-level frames would need a clause segmenter, which the
unpunctuated ASR text does not support well. That is left open.

## 8. Proportion thresholds as a rendering policy (T-1.16.2.3)

N-002 treats the measured proportion as a decision about **how to quote a
span**, not as a label. D-066 still decides WHETHER a span is quoted at all:
ordinary speech is translated plainly, and wording that matters is kept. The
policy decides which script kept wording is shown in.

`code_mixing_service.rendering_mode(analysis)`:

| Mode | When | Quote form |
|---|---|---|
| `native_script` | Hindi grammar and Hindi share ≥ `CODE_MIX_DOMINANT_SHARE` (0.6) | Devanagari throughout, then transliteration, then translation: D-066's full three-part form |
| `plain_english` | English grammar and Hindi share ≤ `CODE_MIX_BORROWING_MAX_SHARE` (0.2), or no Hindi | English, with borrowed words glossed inline |
| `roman` | everything between | Roman script throughout, then translation. The Roman original is its own transliteration, so it is not repeated |

The matrix language gates both ends. A Hindi-grammar sentence is never
"light borrowing", however many English nouns it carries, and an
English-grammar sentence is never shown in Devanagari.

**How the defaults were chosen.** A threshold is only as good as the decisions
it produces on DETECTOR output. A threshold placed where detector bias
pushes spans across it flips decisions on noise alone. So for each pair of
thresholds, the mode computed from the detector's analysis was compared with
the mode computed from the labels (`code_mixing_eval.policy_agreement`).

- **Dominant.** DEV agreement plateaus between 0.50 and 0.60, then falls:
  Devanagari agreement is 0.875 at 0.70 and 0.562 at 0.80. The cause is the
  tagger's blind spot: English nouns written in Devanagari read as Hindi, so
  Devanagari Hinglish (gold Hindi share 0.4–0.95) reads as ~1.0. The user's
  60% sits on the plateau and is the default.
- **Borrowing.** DEV agreement is flat from 0.10 to 0.25 and lower at 0.30;
  0.20 is the plateau's centre. The labelled set shows why the region is
  flat. English-grammar spans up to 0.25 Hindi are single-word borrowings
  (bhai, yaar, beta, "gyan pelu"), and from 0.29 up they carry a whole Hindi
  clause ("ek hi dil hai kitni baar jitoge").

**Held-out (TEST) at the defaults:** detector and gold decisions agree on
0.946 of units, 0.970 of Latin units, **0.823 of mixed units** and 0.824 of
Devanagari units. Gold modes: 145 plain English, 15 Roman, 42 native script.
The 11 flips are 6 Roman→native (Devanagari bias), 4 native→Roman and 1
plain→Roman. Unseen names add to the error: they look Hindi to the n-gram
model ("harry bhai you are the best" reads as one-third Hindi). The labels do
not score names, so the token scores do not show this, but the policy does.

**Does the matrix gate change decisions?** At these defaults, rarely: it
changes 0 of 90 gold decisions and 1 of 57 detector decisions, compared with
the user's pure-percentage rule. It starts to matter at a looser borrowing
threshold. At 0.35 it keeps two Hindi-grammar sentences with a third Hindi
words ("sir please, All programming language ke liye video banaye") from
being flattened into plain English. The matrix earns its keep mostly
elsewhere: it tells the analysis path which grammar a sentence is in
(T-1.16.2.5), and 11% of mixed spans are Hindi grammar with mostly English
words.

**Open question for the user** (recorded in D-080). What should the dominant
threshold rest on? There are two pulls. Reader preference: how much Hindi
should a sentence carry before a reader would rather see Devanagari? That is
a taste question this data cannot settle. Robustness: on TEST, Devanagari
decisions agree with gold 0.912 of the time at 0.50, 0.824 at 0.60 and 0.647
at 0.80, so a lower threshold hides more of the detector's bias. The default
stays at the user's 60%. The measurement says 50% would be more robust until
English nouns in Devanagari become visible to the tagger.

## 9. Transcript-level primary language (T-1.16.2.4)

Deciding the script quote by quote makes a report flicker. One quote from a
speaker comes out in Devanagari, and the next in Roman because its window
carried more English nouns. `profile_transcript(segments)` instead resolves
the transcript's **primary language of communication** once, and that fixes
the script for every quote from the source.

- **Windows.** Consecutive caption segments are merged into windows of 12–40
  words, about a sentence. A 2–5 second caption cuts clauses in half, which
  is useless for a grammar vote.
- **Primary language.** This is the language whose grammar frames at least
  half the speech, weighted by words: `matrix_hi_share` ≥ 0.5 means a
  non-English primary. A Hindi lecture dense with English terms is
  therefore Hindi, which a word count would get wrong.
- **One decision per source.** `quote_mode` is the policy applied to the
  transcript as a whole. `resolve_quote_mode(span_mode, profile)` lets a
  span decide only whether it is English. If it keeps its wording, the
  transcript chooses the script. A Hindi clause inside an English-primary
  source stays in the Roman script it was written or spoken in.
- **Script.** `native_script` records which script the non-English words are
  in ("Devanagari", "Bengali"; "Latin" when romanised), so a native-script
  quote from a Bengali source is shown in Bengali.

**A silent failure found while measuring.** The tagger counted only
Devanagari, Arabic and Gurmukhi words as non-English, and every other script
fell to "neutral". The library holds two Bengali transcripts (one of them the
auto-dubbed Hindi lecture from section 1) and two Kannada ones. All four
measured 0% non-English and would have been quoted as plain English, which
is exactly the failure this story exists to prevent, in a script nobody was
watching. Any non-Latin script is now non-English. The labelled-set scores
do not change, apart from one kaomoji now counting as non-English.

**Measured on the library** (every transcript with any non-English word,
except the five held back for T-1.16.2.6):

| Source | Transcripts | Primary | Quote mode | Script changes, quote by quote | After resolution |
|---|---|---|---|---|---|
| Devanagari Hinglish (Hindi ASR) | 7 | hi | native script | 25 | 0 |
| Bengali (incl. 1 auto-dub) | 2 | other | native script (Bengali) | 2 | 0 |
| Kannada | 2 | other | native script (Kannada) | 0 | 0 |
| Indian English podcasts, English talks | 18 | en | plain English | 0 | 0 |
| **YouTube comment threads (romanised)** | 11 | en (all) | plain English ×9, Roman ×2 | **128** | 0 |

The comment threads show the problem plainly. One commenter writes a
Hindi-dominant line (native script by the span policy) and the next mixes
heavily (Roman), so a quote-by-quote report would switch scripts 128 times
across 11 threads. Resolved, every quoted Hindi line from those threads stays
in Roman. None of the 40 sources is a borderline case today. The closest are
the two comment threads with a third of their words in Hindi (`matrix_hi`
0.35 and 0.45), which resolve to English-primary with Roman quotes.

## Reproduce

```bash
cd backend
./venv/Scripts/python scripts/eval_code_mixing.py --split test
./venv/Scripts/python scripts/eval_code_mixing.py --llm --split all   # live; rewrites the cache
./venv/Scripts/python -m pytest tests/test_services/test_code_mixing_service.py -q
```

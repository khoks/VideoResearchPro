"""Prompt fragments shared across every agent — R3 / R5 / D-066.

These exist as one definition rather than nine copies because the audit that
motivated them found the opposite situation: **no** prompt in the report or
knowledge families instructed English output, so a Hindi corpus produced a
Devanagari report end to end. Nine hand-maintained copies of a rule drift; one
definition injected into nine prompts does not.

Each fragment is a plain string. Call sites concatenate it into their own
prompt so the surrounding instructions still read as one coherent brief.
"""

# --- R5: language ----------------------------------------------------------

ENGLISH_OUTPUT_CONTRACT = """LANGUAGE OF OUTPUT — NON-NEGOTIABLE:
- Write EVERYTHING you produce in English, whatever language the source is in.
  This holds at every stage: an item emitted in the source script here
  propagates untouched into the final deliverable, so the translation happens
  HERE, not later.
- Translate faithfully. Do not summarise away nuance to avoid translating, and
  do not silently drop material you find harder to render in English — a
  dropped point is worse than an imperfect translation.
- Preserve technical terms, product names and proper nouns rather than
  translating them literally into something unrecognisable."""

QUOTE_RENDERING_RULES = """QUOTING NON-ENGLISH SOURCES:
- Proper nouns (people, places, organisations, works) keep their ORIGINAL
  script followed by a romanised form: महाभारत (Mahābhārata). Add a short gloss
  where the name carries meaning the reader needs.
- Direct quotes, verses, and historically or culturally significant speech keep
  ALL THREE — original script, transliteration, then English translation:
  अहिंसा परमो धर्मः (ahiṃsā paramo dharmaḥ) — "non-violence is the highest virtue"
  The original carries authenticity and impact, the transliteration makes it
  pronounceable, the translation makes it usable. Do not drop any of the three
  for a quote that matters.
- Ordinary conversational speech does NOT need this treatment — translate it
  plainly. Reserve the three-part form for material whose exact wording is part
  of its value."""

CODE_MIXING_NOTE = """CODE-MIXED SPEECH:
- Speakers frequently mix languages inside a single sentence — English nouns in
  Hindi grammar, or Arabic/Persian/Urdu vocabulary in Hindi syntax. This is
  normal speech, not transcription error. Read the sentence as a whole and
  render its MEANING in English rather than translating word by word.
- Romanised non-English text (Hindi written in Latin letters, e.g. "mujhe ye
  samajh nahi aaya") is still non-English. Translate it; do not pass it through
  as if it were English.
- A source header may carry `speech: ...`, MEASURED from that source's words
  and grammar: which language it is spoken in, and — when it says "this
  passage in Hindi grammar" — that a passage full of English words is
  nonetheless a Hindi sentence ("model ko train karna padta hai": Hindi with
  English nouns). Read such a passage in the language of its grammar, then
  translate its meaning. A source marked as Hindi is Hindi even where it is
  written in Latin letters."""

# N-002 / S-1.16.2: which script kept wording is shown in. QUOTE_RENDERING_RULES
# decides WHETHER wording is kept; this decides HOW, per source, from the
# measured language mix (code_mixing_service.quote_form). One form per source,
# so a report never switches script for the same speaker.
CODE_MIXED_QUOTE_FORMS = """QUOTE FORM PER SOURCE (code-mixed speech):
- A source or item may name its quote form, measured from that source's
  language mix. When you keep a speaker's wording, use exactly that form:
  - "quote in <script> + transliteration + English translation": the wording
    in that script, then a romanisation, then the translation —
    अहिंसा परमो धर्मः (ahiṃsā paramo dharmaḥ) — "non-violence is the highest
    virtue".
  - "quote in Roman script + English translation": the wording in Latin
    letters as spoken — English words in English spelling, Hindi words
    romanised — then the translation: taaki baadme koi kasar na reh jaye —
    "so that nothing is left wanting later". The Roman original is its own
    transliteration; do not write it twice.
- Use ONE form for every quote from the same source, even where a single
  sentence leans the other way.
- Non-English wording in the report comes ONLY from an item's `original`,
  copied EXACTLY — its spelling, its caption errors, its script. Never
  translate an item's English `content` back into the source's language or
  script, and never re-script an `original`. If an item has no `original`,
  write its point in English. Any non-English text that is not some
  source's own words is removed from the report.
- A source with no quote form is English: gloss any borrowed word inline
  ("bhai (brother)") instead of quoting it."""


# --- R3: time --------------------------------------------------------------

TEMPORAL_AWARENESS = """TIME AND RELEVANCE:
- Each source carries a publication date and, where known, the period it
  DISCUSSES (a 2026 video about a 2019 paper is a 2026 source about a 2019
  event). Treat both as load-bearing: a claim about "the latest model" or
  "current best practice" is a claim about the world AT THE PUBLICATION DATE,
  not now.
- Distinguish "true AS OF <date>" from "true now". Write time-sensitive claims
  with their date so the reader can judge currency: "as of <date>, X was ...".
- When sources disagree and the disagreement tracks their dates, say so
  explicitly, name the dates, and state the trajectory: "as of March 2025
  the sources describe X; by January 2026 Y had replaced it". An older source
  may have been correct then and superseded since. Do not silently prefer
  either the newer or the older one.
- Point out SUPERSESSION: when a later source updates, contradicts or
  withdraws an earlier claim, say which claim is superseded and by which
  source, rather than presenting both as live.
- Weight recency where the question is time-sensitive (what is current,
  latest, best today); weight the discussed era where the question is about
  a period.
- Do NOT infer a date you were not given, and do not describe the corpus's
  overall vintage beyond the verified figures supplied to you."""

TEMPORAL_EXTRACTION_NOTE = """TIME:
- Each chunk header carries `published <date>` for its source and, where the
  library knows it, `discusses <era>` — the period the source is ABOUT. Where
  a claim is time-sensitive (a "new" release, a "current" state of the art, a
  prediction), keep the publication date with the claim so later stages can
  reason about currency.
- Anchor RELATIVE time to the publication date: "last year" in a source
  published 2025-03 means 2024; "the new model" means new AS OF that date.
  Emit absolute dates where you can derive them this way; where you cannot,
  keep the relative phrase and add "(as of <publication date>)".
- Distinguish WHEN A CLAIM WAS MADE from WHEN THE EVENT IT DESCRIBES HAPPENED.
  A 2026 video discussing a 2019 paper is a 2026 source about a 2019 event."""


# --- R1: visual annotations ------------------------------------------------

# The marker every visual annotation is wrapped in. Defined here, next to the
# instruction that teaches models to read it, so the two can never drift apart.
# `visual_service` imports these rather than re-spelling the literals.
VISUAL_MARKER_OPEN = "[VISUAL"
VISUAL_MARKER_CLOSE = "]"

VISUAL_ANNOTATION_CONTRACT = """ON-SCREEN VISUAL ANNOTATIONS — READ CAREFULLY:
- Some transcripts contain spans of the form
  `[VISUAL @ mm:ss — <description of what is on screen>]`.
- These are NOT spoken words. Nobody said them. They are machine-generated
  descriptions of what was VISIBLE on screen at that timestamp, inserted
  because the speaker was showing something the words alone do not carry.
- Use them as evidence about what the source showed. Never quote them as
  speech, never attribute them to the speaker, and never write "the speaker
  said" about their contents.
- ATTRIBUTION BOUNDARY: a sentence credited to a speaker — "X says / notes /
  explains ...", quoted speech, or a clause ending in "— Name (mm:ss)" — may
  contain ONLY what that speaker said. A detail that exists only in an
  annotation never goes inside such a sentence, not even bundled with things
  the speaker did say. Put it in a separate clause marked as shown on screen:
  "the speaker describes a regression plot with a fitted line (10:21); the
  chart on screen also shows a confidence band." Noting that a spoken figure
  is "also visible on screen" stays correct — that is the screen confirming
  speech, not speech invented from the screen.
- When you cite one, say what it is: "on screen at mm:ss, <...>" or "the
  video displays <...> at mm:ss". A reader must be able to tell a claim
  grounded in the audio from one grounded in the picture.
- They are descriptions produced by a model looking at one still frame, so
  they are less reliable than the transcript itself. Where an annotation and
  the spoken words conflict, prefer the words and note the discrepancy rather
  than silently picking one.
- If a passage has no annotations, that means no frames were captured there —
  it does not mean nothing was shown. Never infer absence of visuals from
  absence of annotations.
- CONVERSE: describe something as shown, displayed or visible on screen ONLY
  when an annotation actually shows it (or its item is tagged [SHOWN] or
  [SAID+SHOWN]). A detail the speaker only said is never "on screen", however
  much it reads like screen text — a version number, a file name, an error
  message, code read aloud. This holds in every language: a figure spoken in
  Hindi or Bengali, native digits included (০.১৩.২), is speech."""


# T-1.18.1.13: the Q&A refine step rewrites raw chunks into extracts before
# the answer prompt sees them. A span paraphrased into prose at that step
# reaches the answer model as speech, and the answer-stage contract can no
# longer apply. Both refine prompts carry the contract plus this rule.
VISUAL_SPAN_EXTRACT_RULE = """VISUAL SPANS IN EXTRACTS: when an extract draws on a `[VISUAL @ mm:ss — ...]`
span, copy the span whole, marker and timestamp included, as its own extract.
Never fold an annotation's content into an extract of speech, and never
restate it as plain prose: the answer step tells what was shown from what was
said only by the marker."""


# --- M5 / S-8.5.2: the user's own notes in retrieved context ----------------

# How a note is marked in raw context, defined next to the instruction that
# teaches models to read it (the D-067 pattern). The agent builds the header
# from this prefix; the contract below quotes it.
NOTE_MARKER_PREFIX = "[NOTE by you"

NOTE_ANNOTATION_CONTRACT = """THE ASKER'S OWN NOTES — READ CAREFULLY:
- The context may end with a block of the asker's own notes, each headed
  `[NOTE by you, YYYY-MM-DD | ...]`. Each is on the Allowed sources list as a
  source whose title starts "Your note of" and whose author is "you".
- These are notes the person asking this question wrote themselves: their own
  opinions, observations, reminders and corrections. They are NOT transcript
  text, nobody in any video or source said them, and they are not evidence of
  what a source claims.
- Never attribute a note's content to a speaker, channel, author or source,
  and never let a note stand in as proof that a source said something.
- When a note bears on the question, say so in the second person with its
  date ("you noted on 2026-03-15 that ...") and cite it like any other
  allowed source, copying its title exactly as listed:
  [Source: "<the note's exact title>" by you].
- A note can disagree with the sources. Report both and say which is which;
  do not silently side with either."""


# --- R1 / S-1.18.8: modality provenance -------------------------------------
#
# D-075: prompt rules alone moved attribution errors from one direction to
# the other instead of removing them, and four of the five confirmed errors
# sat in the one Bengali video, where the composer cannot read the speech.
# So whether a fact was SAID or SHOWN is decided at the map stage — where the
# model reads one chunk of native-language speech at a time — carried through
# the lossless reduce, and rendered to the composer as a tag it attributes
# from. These are the four values the pipeline uses.
MODALITY_SAID = "said"
MODALITY_SHOWN = "shown"
MODALITY_BOTH = "both"
MODALITY_UNKNOWN = "unknown"

MODALITY_FIELD_RULE = """EVIDENCE MODALITY — one field on EVERY item:
- `modality` says where the item's evidence sits in the segment it came from:
  "said"  — only in the spoken transcript;
  "shown" — only inside a `[VISUAL @ mm:ss — ...]` span (nobody said it);
  "both"  — the speaker says it AND a span shows it.
- Decide from the segment itself, reading the speech in its own language. A
  version number, name, figure or error message the speaker pronounces — in
  Hindi, Bengali or any other language, native digits included — is "said",
  even when its English rendering looks like on-screen text.
- A segment with no `[VISUAL @` span yields only "said" items."""

MODALITY_TAGS_NOTE = """EVIDENCE TAGS — WHERE EACH ITEM CAME FROM:
- Each item's content begins with a tag fixed when the transcript was read,
  by a model reading the original speech in whatever language it was spoken:
    [SAID]        the speaker said it. Credit it to the speaker.
    [SHOWN]       it appeared only on screen; nobody said it. Write it as
                  shown ("on screen at mm:ss, ..."), never inside a sentence
                  credited to a speaker.
    [SAID+SHOWN]  the speaker said it and the screen showed it. Credit the
                  speaker; you may add that it was also on screen.
    [SAID+SHOWN; shown on screen: X | Y]
                  the speaker said the item, but the details X and Y were
                  found only on screen near that moment, not in the speech.
                  Credit the speaker without them, and give X and Y in a
                  separate clause marked as shown ("on screen at mm:ss, ...").
    [UNLABELLED]  provenance unknown; apply the on-screen annotation rules.
- Attribute from the tag, not from how the content reads: a [SAID] item that
  sounds like screen text was spoken; a [SHOWN] item that sounds like speech
  was not said.
- The tags are for you. Never print them in the report."""


def compose_block(*fragments: str) -> str:
    """Join fragments with blank lines, skipping empties.

    Call sites pass only the fragments relevant to their stage — a JSON
    extraction step does not need quote-rendering rules, and adding them would
    be tokens spent on an instruction the stage cannot act on.
    """
    return "\n\n".join(f.strip() for f in fragments if f and f.strip())

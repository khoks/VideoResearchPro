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
  as if it were English."""


# --- R3: time --------------------------------------------------------------

TEMPORAL_AWARENESS = """TIME AND RELEVANCE:
- Each source carries a publication date. Treat it as load-bearing: a claim
  about "the latest model" or "current best practice" is a claim about the
  world AT THAT DATE, not now.
- When sources disagree and the disagreement tracks their dates, say so — an
  older source may have been correct then and superseded since. Do not silently
  prefer either the newer or the older one; state the trajectory.
- Attribute time-sensitive claims with their date so the reader can judge
  currency: "as of <date>, X was ...".
- Do NOT infer a date you were not given, and do not describe the corpus's
  overall vintage beyond the verified figures supplied to you."""

TEMPORAL_EXTRACTION_NOTE = """TIME:
- Each chunk header carries `published <date>` for its source. Where a claim is
  time-sensitive (a "new" release, a "current" state of the art, a prediction),
  keep that date with the claim so later stages can reason about currency.
- Distinguish WHEN A CLAIM WAS MADE from WHEN THE EVENT IT DESCRIBES HAPPENED.
  A 2026 video discussing a 2019 paper is a 2026 source about a 2019 event."""


def compose_block(*fragments: str) -> str:
    """Join fragments with blank lines, skipping empties.

    Call sites pass only the fragments relevant to their stage — a JSON
    extraction step does not need quote-rendering rules, and adding them would
    be tokens spent on an instruction the stage cannot act on.
    """
    return "\n\n".join(f.strip() for f in fragments if f and f.strip())

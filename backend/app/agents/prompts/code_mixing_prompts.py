"""Prompt for the `code_mixing_detect` use case — S-1.16.2 / N-002.

Word-level language labelling of transcript snippets from speakers who mix
Hindi/Urdu and English. The model returns the Hindi runs VERBATIM rather than
a tag per word: copying spans is cheaper in output tokens than one label per
token, and `code_mixing_service.spans_to_tags` maps them back onto the same
tokenisation the lexicon detector uses, so both are scored on one sequence.

Strict JSON, reasoning OFF at the call site — `max_completion_tokens`
includes reasoning tokens on OpenAI models.
"""

CODE_MIXING_DETECT_PROMPT = """You label the LANGUAGE of each word in short transcript snippets from Indian speakers, who often mix Hindi/Urdu and English inside one sentence.

Things to know:
- Hindi/Urdu is often written in LATIN letters ("romanised"): "mujhe nahi pata", "taaki baadme koi kasar na reh jaye". That is Hindi, not English, even though it uses English letters.
- Hindi may also be written in Devanagari, and English words are then often written in Devanagari too: in "मशीन लर्निंग का कांसेप्ट" the words मशीन, लर्निंग and कांसेप्ट are ENGLISH words (machine, learning, concept) in Devanagari letters; का is Hindi.
- Snippets come from automatic captions, so some words are mis-recognised. Label what the speaker evidently said.

For each numbered snippet:
- "hi": every maximal run of consecutive Hindi/Urdu words, copied EXACTLY as written — same spelling, same script, same order as in the snippet. Do not translate, correct or re-spell. Return [] if the snippet has no Hindi.
  - An English word inside a Hindi sentence ("mujhe ye CONCEPT samajh nahi aaya", "data ko analyse karna") is English: it ends the Hindi run.
  - Names of people, places, companies and products are neither language: leave them out of the runs.
  - Fillers (um, uh, ok) are neither language.
- "matrix": the language whose GRAMMAR frames the snippet — whose auxiliaries, postpositions, verb endings and word order it follows. "so model ko train karna padta hai" is "hi" (Hindi grammar, English nouns); "and this is how we were preparing taaki baadme koi kasar na reh jaye" is "en" (an English sentence with a Hindi clause inside it). Use "none" only when the snippet contains no clause at all.

Snippets:
{snippets}

Return ONLY a JSON object, no markdown, no commentary:
{{"snippets": [{{"i": 0, "hi": ["<exact Hindi run>", "..."], "matrix": "en"}}, ...]}}
Include every snippet number exactly once.
"""


# T-1.16.2.5 part B: the English rendering that a non-English chunk is
# EMBEDDED as. The chunk's stored text stays the original (that is what gets
# quoted); this rendering is only what similarity search compares an English
# question against. Measured: English questions find Hindi chunks at MRR 0.565
# in Devanagari, 0.402 romanised, 0.805 as an English rendering.
CODE_MIXING_RENDER_PROMPT = """Translate each numbered transcript chunk into English, for a search index. The speakers mix Hindi/Urdu and English, in Devanagari or in Latin letters ("romanised": "mujhe nahi pata" is Hindi); some chunks are in another Indian language.

Rules:
- Translate the WHOLE chunk faithfully, in the order it is spoken. Do not summarise, shorten, or skip anything you find hard to translate.
- English words already in the chunk stay as they are. English words written in Devanagari ("मशीन लर्निंग") are written back in English ("machine learning").
- Keep names, product names and technical terms recognisable.
- Keep any span of the form [VISUAL @ mm:ss — ...] exactly as it is.
- Output English only.

Chunks:
{chunks}

Return ONLY a JSON object, no markdown, no commentary:
{{"chunks": [{{"i": 0, "english": "..."}}, ...]}}
Include every chunk number exactly once.
"""

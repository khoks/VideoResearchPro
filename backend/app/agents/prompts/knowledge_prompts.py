"""Prompts for the per-video knowledge extraction agent (Unit 4).

Two prompts:
- EXTRACT_BATCH_PROMPT: map pass — ask the LLM to pull structured knowledge
  (topics/concepts/events/facts) from one transcript batch and return strict JSON.
- SYNTHESIZE_REPORT_PROMPT: reduce pass — ask the LLM to write a Wikipedia-style
  report-voice Markdown document from the merged extraction + full transcript.
"""

EXTRACT_BATCH_PROMPT = """You are extracting structured knowledge from one batch of a YouTube video transcript.

Video: "{video_title}"
Channel: {channel_name}

Transcript batch:
{batch_text}

Extract all substantive knowledge present in this batch into FOUR lists:
1. topics — broad subjects the speaker discusses (short noun phrases)
2. concepts — named ideas, theories, frameworks, definitions, or technical terms
3. events — specific things that happened (dated when possible; real-world, product, or historical)
4. facts — concrete factual claims (measurable, verifiable, or attributable statements)

Rules:
- OUTPUT LANGUAGE IS ENGLISH. Whatever the transcript's language, every item
  you emit is written in English. This is an extraction step feeding an
  English report — a Devanagari or Arabic-script item here propagates all the
  way to the final output.
- Proper nouns (people, places, organizations, product names) keep their
  ORIGINAL script, followed by a romanised form and, where the name carries
  meaning the reader needs, a gloss:
  ``महाभारत (Mahābhārata)`` — or ``महाभारत (Mahābhārata, "great epic of the
  Bharatas")`` when the meaning matters.
- Direct quotes, verses and formal speech keep all three: the original script,
  a romanised transliteration, then an English translation —
  ``अहिंसा परमो धर्मः (ahiṃsā paramo dharmaḥ) — "non-violence is the highest
  virtue"``. Authenticity and accessibility both matter here; do not collapse
  to one form.
- Keep each item concise but self-contained (one clause or short sentence).
- Do not invent information. Every item must be grounded in this batch.
- If the speaker clearly speculates or hedges ("I think", "probably"), prefix
  the item with "Speculation: ".
- Skip filler, greetings, call-to-action phrases, and sponsor reads.

OUTPUT FORMAT (STRICT):
- Respond with a SINGLE JSON object and NOTHING else.
- No markdown code fences, no prose, no commentary.
- Keys: topics, concepts, events, facts. Each value is an array of strings.
- If a category has no items for this batch, return an empty array.

Example shape:
{{"topics": ["..."], "concepts": ["..."], "events": ["..."], "facts": ["..."]}}
"""


SYNTHESIZE_REPORT_PROMPT = """You are writing a Wikipedia-style knowledge report for a single YouTube video.

Video: "{video_title}"
Channel: {channel_name}

Merged structured extraction (deduplicated union across transcript batches):
{merged_extraction_json}

Transcript excerpt (opening portion only — use it to anchor voice and
terminology; full coverage comes from the merged extraction above; do not
quote at length):
{full_transcript_text}

Write a Markdown knowledge document ABOUT THE CONTENT of this video. The
document is a reference artifact, not a video summary or recap.

STYLE REQUIREMENTS (non-negotiable):
- Report voice, not conversational. Write like a Wikipedia article or an
  encyclopedia entry. Third person. No "In this video...", no "the creator
  says...", no direct address to the reader.
- Objective and neutral. Attribute claims to the video as a source only when
  necessary (e.g. "According to the video, ...").
- Mark speculation EXPLICITLY. If a claim is speculative, hedged, or
  forward-looking, prefix the sentence with "Speculation: " or wrap the
  speculative portion in a sentence clearly labeled as such.
- THE REPORT IS WRITTEN IN ENGLISH, whatever the source language.
- Proper nouns keep their ORIGINAL script followed by a romanised form:
  ``महाभारत (Mahābhārata)``. Where the name carries meaning the reader needs,
  add a short gloss.
- Direct quotes, verses, and historically significant speech keep all three —
  original script, transliteration, then English translation:
  ``अहिंसा परमो धर्मः (ahiṃsā paramo dharmaḥ) — "non-violence is the highest
  virtue"``. The original preserves authenticity and impact; the
  transliteration makes it pronounceable; the translation makes it usable.
  Do not drop any of the three for a quote that matters.
- Prefer well-formed paragraphs over bullet lists for prose sections. Bullet
  lists are fine for enumerations (events, key concepts).

STRUCTURE:
Use Markdown headings. Suggested sections (include only those that apply):
1. `# <Short topic-style title>` — one line, topic-based (not the video title).
2. `## Overview` — 1-3 paragraph report-voice summary of the subject matter.
3. `## Key Concepts` — each concept as a bold term followed by a short definition.
4. `## Topics Covered` — brief paragraphs or a bulleted list of topics.
5. `## Events` — chronological bulleted list when dates or sequence exist.
6. `## Facts and Claims` — bulleted list; mark speculation explicitly.
7. `## References` — optional; list named sources the video cites.

Return ONLY the Markdown document body. No code fences, no preamble, no
closing remarks.
"""

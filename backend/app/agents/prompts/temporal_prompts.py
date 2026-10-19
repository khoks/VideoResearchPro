"""Prompt for the `temporal_scope_extract` use case — R3 / S-1.17.2.

One call per document, on its first ingest. It dates the SUBJECT MATTER of
a source, which is a different question from when the source was published:
a 2026 video about a 2019 paper is a 2026 source about a 2019 event. The
pipeline already knows the first date (`documents.published_at`); this is
the second.

Strict JSON, reasoning OFF at the call site — `max_completion_tokens`
includes reasoning tokens on OpenAI models, and this output is ~80 tokens.
"""

TEMPORAL_SCOPE_PROMPT = """You are dating the SUBJECT MATTER of one source — the period its claims, events and subjects belong to. This is NOT the same as when the source was published.

Source title: "{title}"
Published: {published_at}
Description: {description}

Transcript samples (opening, middle and closing windows; "[...]" marks a gap):
{samples}

Decide which period the source is ABOUT.

Return ONLY a JSON object with exactly these keys:
{{"era_start": <integer year or null>, "era_end": <integer year or null>, "era_confidence": <number 0.0-1.0>, "is_retrospective": <true or false>, "era_label": "<short phrase, at most 8 words>"}}

Rules:
- Years are integers. Use negative integers for BCE (500 BCE is -500).
- era_start <= era_end. A source about a single year has era_start == era_end.
- A source discussing the present as of its publication (current tools, current events, "the latest" anything): era_start and era_end are the publication year, or the year of the developments it reacts to if the samples make that explicit. is_retrospective is false.
- is_retrospective is true when the source mainly looks BACK at a period that ended well before it was published — history, retrospectives, explainers of older events, re-examinations of past work.
- A source spanning many periods (a history from 1900 to the present) gets the full span with lower confidence.
- Timeless or undatable material (a how-to with no dated referents, fiction, philosophy, pure mathematics): era_start and era_end are null, era_confidence is 0.0, is_retrospective is false.
- Do NOT derive the era from the publication date alone. If the samples contain no dated referents, return nulls rather than echoing the publication year.
- era_label names the period in words ("mid-2020s LLM tooling", "Mughal period", "2008 financial crisis"). Keep it short.
- No markdown, no code fences, no commentary. The JSON object only.
"""

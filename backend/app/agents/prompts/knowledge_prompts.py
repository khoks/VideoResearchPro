"""Prompts for the per-document knowledge extraction agent (Unit 4).

Two prompts:
- EXTRACT_BATCH_PROMPT: map pass — ask the LLM to pull structured knowledge
  (topics/concepts/events/facts) from one batch of a source's text and return
  strict JSON.
- SYNTHESIZE_REPORT_PROMPT: reduce pass — ask the LLM to write a Wikipedia-style
  report-voice Markdown document from the merged extraction + a text excerpt.

Both serve every source type. The words that name the source ("a YouTube
video transcript", "Channel:", "the speaker") come from ``SOURCE_PROFILES``
and ``source_header``; for a YouTube video they are exactly the
wording these prompts carried before non-video documents were supported, so
the video prompts did not change. The English-output, quoting, time and
language rules are the same for every source.
"""
from dataclasses import dataclass

from app.agents.prompts.shared import VISUAL_ANNOTATION_CONTRACT


@dataclass(frozen=True)
class SourceProfile:
    """How the knowledge prompts name one source type."""

    subject: str  # what a batch is cut from: "a YouTube video transcript"
    noun: str  # "YouTube video"
    short: str  # "video" — "this video", "According to the video"
    title_label: str  # the header line for the title: 'Video: "..."'
    creator_label: str  # the header line for the creator: "Channel: ..."
    text_label: str  # "Transcript" batch / excerpt
    voice: str  # who speculates or discusses: "the speaker"


_VIDEO = SourceProfile(
    subject="a YouTube video transcript",
    noun="YouTube video",
    short="video",
    title_label="Video",
    creator_label="Channel",
    text_label="Transcript",
    voice="the speaker",
)

_THREAD_VOICE = "the author or a commenter"

SOURCE_PROFILES: dict[str, SourceProfile] = {
    "video": _VIDEO,
    "podcast_episode": SourceProfile(
        "a podcast episode transcript", "podcast episode", "episode",
        "Episode", "Show", "Transcript", "the speaker",
    ),
    "pdf": SourceProfile(
        "the text of a PDF document", "PDF document", "document",
        "Document", "Author", "Text", "the author",
    ),
    "article": SourceProfile(
        "the text of a web article", "web article", "article",
        "Article", "Author", "Text", "the author",
    ),
    "tweet": SourceProfile(
        "an X / Twitter post", "X / Twitter post", "post",
        "Post", "Author", "Text", "the author",
    ),
    "fb_post": SourceProfile(
        "a Facebook post", "Facebook post", "post",
        "Post", "Author", "Text", "the author",
    ),
    "ig_post": SourceProfile(
        "an Instagram post", "Instagram post", "post",
        "Post", "Author", "Text", "the author",
    ),
    "li_post": SourceProfile(
        "a LinkedIn post", "LinkedIn post", "post",
        "Post", "Author", "Text", "the author",
    ),
    "reddit_post": SourceProfile(
        "a Reddit thread (the post and its comments)", "Reddit thread", "thread",
        "Thread", "Posted by", "Thread text", _THREAD_VOICE,
    ),
    "hn_story": SourceProfile(
        "a Hacker News thread (the story and its comments)", "Hacker News thread", "thread",
        "Thread", "Posted by", "Thread text", _THREAD_VOICE,
    ),
    "mastodon_post": SourceProfile(
        "a Mastodon thread (the post and its replies)", "Mastodon thread", "thread",
        "Thread", "Posted by", "Thread text", _THREAD_VOICE,
    ),
    "bluesky_post": SourceProfile(
        "a Bluesky thread (the post and its replies)", "Bluesky thread", "thread",
        "Thread", "Posted by", "Thread text", _THREAD_VOICE,
    ),
}

# A source type registered after this table was written still gets a prompt
# that reads correctly, just a less specific one.
_GENERIC = SourceProfile(
    "the text of a document", "document", "document",
    "Document", "Author", "Text", "the author",
)


def source_profile(source_type: str | None) -> SourceProfile:
    """The profile for ``source_type``; a missing type is a YouTube video
    (the column's default), an unknown one a generic document."""
    if not source_type:
        return _VIDEO
    return SOURCE_PROFILES.get(source_type, _GENERIC)


def source_header(profile: SourceProfile, title: str, creator: str) -> str:
    """The title and creator lines at the top of both prompts.

    A video keeps its old two lines, ``Channel: Unknown`` included. Other
    sources drop the creator line when the creator is not known: a PDF has no
    channel, and "Author: Unknown" tells the model nothing.
    """
    lines = [f'{profile.title_label}: "{title or "Unknown"}"']
    if profile is _VIDEO:
        lines.append(f"{profile.creator_label}: {creator or 'Unknown'}")
    elif creator:
        lines.append(f"{profile.creator_label}: {creator}")
    return "\n".join(lines)


EXTRACT_BATCH_PROMPT = """You are extracting structured knowledge from one batch of {source_subject}.

{source_header}
{temporal_note}
{language_note}

{text_label} batch:
{batch_text}

Extract all substantive knowledge present in this batch into FOUR lists:
1. topics — broad subjects {source_voice} discusses (short noun phrases)
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
- If {source_voice} clearly speculates or hedges ("I think", "probably"), prefix
  the item with "Speculation: ".
- TIME: anchor relative time expressions ("last year", "recently", "the new
  model", "next quarter") to the publication date given above and emit
  ABSOLUTE dates wherever you can derive them ("in 2024", "the model released
  in March 2025"). Where you cannot, keep the relative phrase and append
  "(as of <publication date>)". An event is dated by when it HAPPENED, a claim
  by when it was MADE — keep the two apart.
- Skip filler, greetings, call-to-action phrases, and sponsor reads.

{visual_annotations}
- An item grounded in an annotation rather than in speech must say so:
  "On screen at 4:12: revenue rises from $2.1M to $5.8M across the year."

OUTPUT FORMAT (STRICT):
- Respond with a SINGLE JSON object and NOTHING else.
- No markdown code fences, no prose, no commentary.
- Keys: topics, concepts, events, facts. Each value is an array of strings.
- If a category has no items for this batch, return an empty array.

Example shape:
{{"topics": ["..."], "concepts": ["..."], "events": ["..."], "facts": ["..."]}}
"""


SYNTHESIZE_REPORT_PROMPT = """You are writing a Wikipedia-style knowledge report for a single {source_noun}.

{source_header}
{temporal_note}
{language_note}

Merged structured extraction (deduplicated union across transcript batches):
{merged_extraction_json}

{text_label} excerpt (opening portion only — use it to anchor voice and
terminology; full coverage comes from the merged extraction above; do not
quote at length):
{full_transcript_text}

Write a Markdown knowledge document ABOUT THE CONTENT of this {source_short}. The
document is a reference artifact, not a {source_short} summary or recap.

STYLE REQUIREMENTS (non-negotiable):
- Report voice, not conversational. Write like a Wikipedia article or an
  encyclopedia entry. Third person. No "In this {source_short}...", no "the creator
  says...", no direct address to the reader.
- Objective and neutral. Attribute claims to the {source_short} as a source only when
  necessary (e.g. "According to the {source_short}, ...").
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
- DATE YOUR CLAIMS. Time-sensitive statements ("the current leader", "the
  latest release", prices, versions, records) are written as true AS OF the
  publication date — "as of <date>, ..." — never as timeless fact. Where the
  {source_short} is retrospective, say which period it concerns, and keep the period
  an event belongs to distinct from the date the {source_short} was made.

STRUCTURE:
Use Markdown headings. Suggested sections (include only those that apply):
1. `# <Short topic-style title>` — one line, topic-based (not the {source_short} title).
2. `## Overview` — 1-3 paragraph report-voice summary of the subject matter.
3. `## Key Concepts` — each concept as a bold term followed by a short definition.
4. `## Topics Covered` — brief paragraphs or a bulleted list of topics.
5. `## Events` — chronological bulleted list when dates or sequence exist.
6. `## Facts and Claims` — bulleted list; mark speculation explicitly.
7. `## References` — optional; list named sources the {source_short} cites.

Return ONLY the Markdown document body. No code fences, no preamble, no
closing remarks.
"""

"""Prompts used by the Search Agent.

Design philosophy for topic-job search planning:

* The user gives us a research ``topic`` plus optional free-text
  ``search_instructions`` and an optional list of ``preferred_channels``.
* The ``search_instructions`` field is *semantic guidance* about what the
  user cares about (tone, perspective, recency, style). It is NOT raw text
  to paste into a YouTube search query. Earlier prompt versions sometimes
  concatenated channel names or long instruction strings directly into the
  query text, producing 10-word phrases that YouTube matched against
  nothing.
* Preferred channels are resolved to channel IDs out-of-band and ingested
  via the uploads-playlist walker — never via query text. The LLM is told
  explicitly not to mention them.
* The goal of the broad query set is **maximum blast radius** on the
  topic: diverse angles, perspectives, and vocabularies so that we cover
  as much of YouTube as possible without over-narrowing any single query.
"""

PLAN_SEARCHES_PROMPT = """You are a YouTube research planner. You produce a JSON \
search plan for a research topic. Another system will execute the plan against \
the YouTube API — your job is only to plan.

Research topic: {topic}

User's semantic guidance (tone, angle, perspective preferences — NOT search \
text): {search_instructions}

Channel type preferences (semantic, NOT a YouTube filter): {channel_type_filters}

{preferred_channels_section}

Return a JSON object with exactly these three keys:

{{
  "broad_queries": [ "query 1", "query 2", ... ],
  "channel_keywords": [ "keyword 1", "keyword 2", ... ],
  "temporal_profile": {{
    "recency_weight": "dominant" | "secondary" | "minimal",
    "target_era": "<period the topic is about, e.g. '2024-2026' or 'Mughal period', or null>",
    "rationale": "<one sentence>"
  }}
}}

Rules for "broad_queries" (exactly 4-6 items):
- Each query is a short (2-6 word) YouTube search phrase targeting a DIFFERENT \
angle of the topic. Examples of angles: technical deep-dive, explainer / \
beginner intro, recent news, criticism or risks, case studies or demos, \
expert interviews.
- Queries should achieve MAXIMUM BLAST RADIUS — i.e. together they should \
cover the topic broadly, using varied vocabulary, not the same phrase \
rewritten. Think about synonyms, adjacent concepts, and common framings.
- **Absolutely DO NOT** include any channel names, creator names, handle-like \
tokens, URLs, or ``@``-mentions in the queries. Those are a separate \
mechanism handled elsewhere.
- Do not include the user's verbatim ``search_instructions`` text. Use the \
instructions only to shape which angles you pick.
- Prefer natural-language phrases actual viewers would type; avoid boolean \
operators, quotes, or site-specific syntax.

Rules for "channel_keywords" (3-8 short keywords or phrases):
- These will be used to filter the most recent uploads from the user's \
preferred channels down to the topic-relevant ones. So include the most \
central keywords of the topic (and common synonyms) that are likely to \
appear in video titles or descriptions.
- Short: one or two words per entry. Lowercase. No punctuation.
- Include keywords in whichever language(s) the topic is typically discussed \
in (English by default, but if the topic is clearly non-English, include \
terms in that language too).

Rules for "temporal_profile" — decide DELIBERATELY how time should weigh \
in ranking for THIS topic (it is a ranking preference downstream, never a \
filter):
- "dominant": the topic moves fast (tooling, models, prices, current events, \
anything where last year's answer is wrong this year). Newer material should \
strongly outrank older among on-topic candidates.
- "secondary": relevance and substance lead; publish date breaks ties and \
keeps the corpus from being all one vintage. The default when unsure.
- "minimal": the topic is evergreen or historical; foundational and \
authoritative treatments beat recent ones regardless of age.
- "target_era": the period the topic is ABOUT when that is specific (a \
historical period, a named year or range, "the 2008 crisis"); null when the \
topic is about the present or has no era.
- If the user's guidance mentions recency, currency, "latest", "history", a \
period or a year, let it decide.

Return ONLY the JSON object, no commentary.
"""

PREFERRED_CHANNELS_BLOCK = """Preferred channels the user already named: {channels}.
These will be ingested directly via their uploads playlists — do NOT mention \
their names in the broad_queries. Use channel_keywords to match which of their \
recent uploads are actually about the topic.
"""


RANK_AND_CURATE_PROMPT = """You are a YouTube research assistant. Given a list \
of discovered videos for a research topic, rank them by relevance and select \
the top {num_videos} most relevant ones.

Topic: {topic}
Additional instructions: {search_instructions}

Each video below is shown with metadata:
- Title and channel
- Duration
- Views (view count on the video)
- Likes (like count on the video)
- Published (ISO 8601 publish date — when the video was POSTED)
- Era (only when the library has already dated this video's CONTENT: the \
period it discusses, e.g. "discusses 2019–2021 (retrospective)". Absent for \
videos the library has not seen; infer the discussed era from the title and \
description for those)
- Script (only when the title is not in Latin script — a language hint)
- Subscribers (approximate subscriber count of the channel — a proxy for channel authority)
- Source (how the video was discovered: "search" = broad topic search, "preferred_channel" = from a channel the user specifically wanted)

Videos found:
{video_list}

{temporal_guidance}

{language_guidance}

Consider:
- Relevance to the specific topic
- Prefer videos sourced from "preferred_channel" when they are on-topic — \
the user explicitly wants those creators represented — but do not include \
off-topic preferred-channel videos just because the source is preferred.
- Engagement signals (views, likes) relative to channel size — a mid-size \
channel with strong engagement is often a better signal than a huge channel \
with a tangential video
- Channel authority via subscriber count, but weight relevance higher than raw popularity
- Video duration — prefer substantive content over shallow clickbait
- Time, as the TEMPORAL PROFILE above directs: publish date says when a video \
was made, the era says what period it is about, and a fast-moving topic \
weights the first while a historical topic weights the second. Either way \
this is a preference among on-topic candidates — never exclude a video for \
its date alone
- Diversity of perspectives across different channels

Return a JSON array of video IDs for the top {num_videos} most relevant videos, ordered by relevance.
Example: ["video_id_1", "video_id_2"]
"""

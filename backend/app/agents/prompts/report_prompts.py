MAP_CHUNK_PROMPT = """You are analyzing YouTube video transcripts for a research report on: {topic}

Extract ALL of the following from these transcript segments:
1. **Facts**: Specific factual claims made
2. **Comments/Opinions**: Commentary and opinions expressed
3. **Conclusions**: Conclusions drawn by speakers
4. **References**: Historical events, studies, other sources mentioned
5. **Speakers**: Identify speakers when possible (by name or role)

For each item, include:
- The content/claim
- The video title and channel
- The approximate timestamp
- The speaker (if identifiable)

Transcript segments:
{chunks}

OUTPUT FORMAT (STRICT):
- Respond with a SINGLE JSON object and NOTHING else.
- Do NOT wrap the output in markdown code fences (no ```json, no ```).
- Do NOT include any prose, comments, or explanation before or after the JSON.
- The JSON must be parseable by a standard JSON parser (double-quoted keys/strings, no trailing commas).

The JSON object must have keys: facts, comments, conclusions, references, speakers.
Each value is an array of objects with fields: content, video_title, channel_name, timestamp_display, timestamp_seconds, video_url, speaker.
"""

REDUCE_PROMPT = """You are consolidating extracted information from multiple batches of YouTube transcripts
for a research report on: {topic}

Merge and deduplicate the following extracted data, keeping all unique information:

{batch_summaries}

Return a single consolidated JSON object with keys: facts, comments, conclusions, references, speakers.
Merge duplicates, keep the most detailed version of each item.
"""

COMPOSE_REPORT_PROMPT = """You are writing a comprehensive research report based on YouTube video analysis.

Topic: {topic}
Statistics: {statistics}

Consolidated research data:
{consolidated_data}

Write a well-structured HTML report with the following sections:
1. **Executive Summary** - Brief overview of findings
2. **Key Facts** - All factual claims with sources and timestamps
3. **Analysis & Commentary** - Comments and opinions from various sources
4. **Conclusions** - Conclusions drawn across videos
5. **Historical & External References** - References to other sources, studies, events
6. **Speaker Contributions** - Notable speakers and their key contributions
7. **Statistics** - Video count, transcript count, total words, total minutes, per-channel breakdown

For each fact, comment, conclusion, and reference, include clickable YouTube timestamp links.
Format timestamps as links: <a href="VIDEO_URL&t=SECONDS" target="_blank">TIMESTAMP_DISPLAY</a>

Return ONLY the HTML content for the report body (no <html>, <head>, <body> tags - just the content).
Use semantic HTML (h2, h3, p, ul, li, table, etc.) with CSS classes for styling.
"""

CHANNEL_MAP_PROMPT = """You are summarizing YouTube videos collected from a single channel.

Channel: {channel_name}
Video count in this batch: {video_count}

Transcript excerpts for this channel:
{chunks}

Identify the dominant themes, recurring topics, and notable points covered in this channel's content.
Keep the summary concise (4-8 bullet points) and grounded in the transcript excerpts.

OUTPUT FORMAT (STRICT):
- Respond with a SINGLE JSON object and NOTHING else.
- Do NOT wrap the output in markdown code fences.
- Do NOT include any prose before or after the JSON.
- The JSON object must have keys: channel_name (string), themes (array of strings), highlights (array of strings).
"""

CHANNEL_COMPOSE_PROMPT = """You are composing a concise HTML narrative summarizing a collection of YouTube
channels whose videos have been gathered for reference.

Statistics: {statistics}

Per-channel theme summaries:
{channel_summaries}

Write an HTML report body with these sections:
1. **Overview** - a brief paragraph describing the collection as a whole.
2. **Channel Summaries** - one subsection per channel (h3 with the channel name) listing its dominant
   themes and any notable highlights as a bullet list.
3. **Cross-Channel Observations** - short paragraph calling out themes shared across channels (omit if none).

Return ONLY the HTML content for the report body (no <html>, <head>, <body> tags - just the content).
Use semantic HTML (h2, h3, p, ul, li) with CSS classes consistent with a research report.
"""


# --- S-1.14.8: sectioned composition ---------------------------------------
#
# COMPOSE_REPORT_PROMPT above asks one call to write all seven sections from
# the entire corpus. D-055 measured what that produces on a 200-video job: a
# 3,848-word report citing 2 channels, with zero quantitative claims, because
# a single completion cannot carry a large corpus no matter how good the
# model. Composition is now per-section, so report depth scales with how much
# material the corpus actually yielded.

COMPOSE_SECTION_PROMPT = """You are writing ONE section of a research report on: {topic}

SECTION: {section_title}
{section_guidance}

Source material for this section ({item_count} items{part_note}):
{material}

Requirements:
- Write ONLY this section's HTML. Start with <h2>{section_title}</h2>{heading_note}
- Cover the material comprehensively. Every distinct item above deserves to be
  represented — group related items under <h3> sub-headings where that aids the
  reader, but do NOT collapse many specific claims into one vague sentence.
- Preserve specificity: named models, tools, versions, organizations, numbers,
  percentages and dates are the value of this report. Never round away a figure
  or replace a named entity with a generic noun.
- Attribute every claim. Include a clickable timestamp link wherever the item
  supplies one: <a href="VIDEO_URL&t=SECONDS" target="_blank">TIMESTAMP_DISPLAY</a>
  Omit the link only when the item has no video_url.
- Where sources disagree, present the disagreement and cite both sides rather
  than flattening it.
- No <html>, <head>, <body>, <style> or <script> tags. Semantic HTML only
  (h2, h3, p, ul, li, table) with CSS classes.
- Output the HTML only — no preamble, no commentary about your process.
"""

COMPOSE_SUMMARY_PROMPT = """You are writing the Executive Summary for a research report on: {topic}

Corpus statistics:
{statistics}

The report's body sections (already written) cover:
{section_digest}

Write the Executive Summary:
- Start with <h2>Executive Summary</h2>
- State what the corpus actually contains and the most important findings across
  it — the through-lines, the tensions between sources, and what a reader should
  take away. Lead with substance, not throat-clearing.
- Be concrete: name the models, tools, organizations and figures that matter.
- Do NOT claim breadth the body does not support. If the body draws on a subset
  of the corpus, describe what IS covered rather than asserting totals.
- 4-8 paragraphs. No <html>/<head>/<body> tags. Semantic HTML only.
- Output the HTML only.
"""

# Per-section guidance + which consolidated key feeds each. Order here is the
# order sections appear in the report body.
REPORT_SECTIONS = (
    {
        "key": "facts",
        "title": "Key Facts",
        "guidance": (
            "Every factual claim made across the corpus, with its source and timestamp. "
            "This is the report's substance — organise it into thematic sub-sections "
            "(<h3>) so a reader can navigate, and keep the specific numbers, model "
            "names, versions and measurements intact."
        ),
    },
    {
        "key": "comments",
        "title": "Analysis & Commentary",
        "guidance": (
            "Opinions, arguments and interpretations from the speakers. Organise by "
            "the debate or theme at issue, give each position its strongest cited "
            "voice, and make disagreements explicit rather than averaging them away."
        ),
    },
    {
        "key": "conclusions",
        "title": "Conclusions",
        "guidance": (
            "Conclusions the sources themselves reach, plus the cross-cutting "
            "conclusions the corpus supports as a whole. Distinguish the two."
        ),
    },
    {
        "key": "references",
        "title": "Historical & External References",
        "guidance": (
            "References to papers, studies, products, events and prior work mentioned "
            "across the corpus, with who cited them and where."
        ),
    },
    {
        "key": "speakers",
        "title": "Speaker Contributions",
        "guidance": (
            "Notable speakers and what each contributed. Group by speaker, note their "
            "affiliation or channel, and summarise their distinctive positions."
        ),
    },
)

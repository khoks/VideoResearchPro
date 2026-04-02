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

Return a JSON object with keys: facts, comments, conclusions, references, speakers.
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

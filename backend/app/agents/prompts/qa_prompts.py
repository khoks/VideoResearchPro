REFINE_CONTEXT_PROMPT = """You are a context extraction assistant. Your job is to read raw context from video transcripts and a research report, then extract ONLY the passages that are relevant to the user's question.

Question: {question}

Raw context (transcript chunks + research report):
{raw_context}

INSTRUCTIONS:
1. Read ALL the raw context carefully — both transcript chunks and the research report section.
2. Extract every sentence, fact, quote, or passage that is even partially relevant to the question.
3. Preserve the source attribution (video title, channel, timestamp) for each extracted passage.
4. Include information that is indirectly relevant (e.g., background context, related events, contrasting perspectives).
5. Format your output as a clean, organized set of relevant extracts with their sources.
6. If the research report contains relevant findings, key facts, or analysis — include those prominently.
7. Aim for 2000-4000 characters of focused, relevant context.

IMPORTANT: Be inclusive, not exclusive. If in doubt about whether something is relevant, include it. The next step will use your extracts to answer the question — missing information is worse than including slightly tangential info.

Extracted relevant context:"""

QA_SYSTEM_PROMPT = """You are a research assistant that answers questions based on YouTube video transcript data.

You have access to curated, relevant extracts from a knowledge base built from YouTube video transcripts and a research report. When answering:
1. Use the provided context to give a thorough, well-structured answer.
2. Cite specific video sources with timestamps so users can verify in the original videos.
3. Mention the speaker's name when known.
4. Synthesize information across multiple sources for a comprehensive answer.
5. Only say information is unavailable if the provided context truly contains nothing related.

For each piece of information you cite, include a reference in this format:
[Source: "VIDEO_TITLE" by CHANNEL_NAME at TIMESTAMP]

At the end of your answer, provide a structured references section."""

QA_ANSWER_PROMPT = """Answer the following question using the curated context extracts below. These extracts were specifically selected as relevant to the question from video transcripts and a research report.

Question: {question}

Relevant context:
{refined_context}

Provide a thorough, well-structured answer with citations. For each key claim, reference the source video, channel, and timestamp.
"""

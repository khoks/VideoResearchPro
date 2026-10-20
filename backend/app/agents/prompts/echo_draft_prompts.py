"""Prompts for "speak as me" (S-3.4.1, ``app/agents/echo_agent.py``). Share OCR keeps its own
module, ``echo_prompts.py``.

The draft prompt starts from the ``VOICE`` prompt S-3.3.4's harness ran
(``scripts/voice_match_harness.py``), the version whose pre-registered gate
passed (D-100): a trait card of the user's signals plus five of their own
texts chosen for style diversity, not topic. To it this adds what a real
reply needs: the knowledge it may draw on, cited with markers; the facts
about the user; and the rules that keep it honest.

Drafts are written in the language of the reply (the user's), not English:
D-066's English contract governs reports and answers, which are about the
sources; a draft is the user speaking.
"""

CLASSIFY_PROMPT = """Someone received this message and wants to reply to it.

Message:
{message}

Reply with JSON only:
{{"intent": "question" | "opinion" | "recommendation" | "request" | "social" | "other",
  "topic": "what the reply must address, in at most 15 words",
  "language": "en" | "hi-Deva" | "hi-Latn" | "mixed",
  "people": [{{"name": "a person named in the message", "public": true | false}}]}}

"language" is the message's: en (English), hi-Deva (Hindi in Devanagari), hi-Latn (Hindi in Roman letters), mixed.
List every person the message names. "public" is true only for a public figure (a politician, a famous author, a company's CEO in the news); a friend, colleague or relative is false."""


DRAFT_PROMPT = """You are drafting a reply AS a specific person, in their voice. The person will read your draft, edit it and decide whether to send it. You never send anything.

How they write and think:
{trait_card}

Things they actually wrote (match their style; do not copy their sentences):
{exemplars}

What they know about themselves:
{facts}

What their library and notes say about this topic. Use it for substance. Put a marker such as [S2] right after every claim it supports. Never copy its wording: say it the way this person would. A claim no item below supports must not be made; say less instead.
{knowledge}

The message they are replying to:
{message}

Write the reply in {language_name}, register {register}, for {audience}. Match their style: word choice, sentence length, punctuation, register, and the way they frame a point. Do not mention that you are drafting, the samples, or these instructions. Do not state facts about any private person named in the message beyond what the message itself says. Reply with the draft only."""


CRITIQUE_PROMPT = """Here is how a person writes and thinks:
{trait_card}

Things they actually wrote:
{exemplars}

The knowledge a draft in their name was allowed to use:
{knowledge}

A draft reply in their name:
{draft}

Score the draft from 1 (poor) to 5 (indistinguishable from them) on tone, vocabulary, sentence structure and topicality (does it address the message the way they would). Score "grounded" from 1 to 5: is every factual claim supported by the knowledge, with its marker? List each way the draft deviates from them or claims more than the knowledge supports, as short plain sentences.

Reply with JSON only:
{{"tone": 1, "vocabulary": 1, "structure": 1, "topicality": 1, "grounded": 1, "notes": ["..."]}}"""


REVISE_PROMPT = """{draft_prompt}

A first draft:
{draft}

A careful reader who knows this person found:
{notes}

Write the reply again, fixing those points. Keep every marker on a claim the knowledge supports; drop any claim it does not. Reply with the draft only."""


PARAPHRASE_PROMPT = """{draft_prompt}

This draft repeats a source word for word, which a reply in the person's own voice must never do:
{draft}

The repeated words:
{spans}

Write the reply again with those passages said in the person's own words. Keep the markers. Reply with the draft only."""

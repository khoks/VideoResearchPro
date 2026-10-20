"""Author Studio prompts (I-6): the newsletter's featured deep-dive (S-6.4.1).

Everything else in an issue is listed deterministically from the database.
One ``author_newsletter_compose`` call writes the featured section from ONE
source the user already has (a report, or a knowledge report), whose
citations reach the model as markers (``[S3]``). The renderer turns markers
back into links and drops any it did not hand out; a section citing nothing
is replaced by the source's own summary, so the email never carries an
unsourced claim.
"""
from __future__ import annotations

from app.agents.prompts.shared import (
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    compose_block,
)

FEATURED_SYSTEM = compose_block(
    """You write the featured deep-dive of a personal research digest: one
piece of the reader's own library, brought back so they remember what it
said. The reader asked for this research; write for them, not for a general
audience.

Write 150 to 250 words of plain prose in two or three short paragraphs:
- open with the single most useful finding, stated concretely;
- then what supports it and where the sources disagree or leave it open;
- end with one thing worth revisiting or checking now.

SOURCES — NON-NEGOTIABLE:
- The source text below is your ONLY source of facts. Never add a fact,
  figure, name or date it does not contain.
- Markers look like [S12]. They follow the cited points in the source text.
  Timestamps such as 1:15 are not markers.
- After every sentence that states something from the source, copy the
  marker of the point it comes from, exactly as written, e.g. "... sixty
  percent [S4]." Use only markers that appear in the source text; never make
  one up. A sentence you cannot mark does not belong in the section, and a
  section without markers is discarded.
- No headings, lists, links, HTML or footnotes; the digest renders the
  sources itself.""",
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    """OUTPUT: the section only. First line: a headline of at most 10 words.
Then a blank line, then the paragraphs.""",
)


def featured_user_prompt(kind: str, title: str, text: str) -> str:
    return f'FEATURED {kind.upper()}: "{title}"\n\n===== SOURCE TEXT =====\n{text.strip()}'

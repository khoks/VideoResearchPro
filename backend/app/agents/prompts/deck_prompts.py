"""Author Studio prompts (I-6): the slide deck outline (S-6.3.1).

One ``author_deck_outline`` call turns one or more research reports, or
knowledge reports about single documents (S-6.3.2), into a deck plan. The
reports reach the model with every citation replaced by a source marker
(``[S12]``), and the model cites slides by those numbers only;
the renderer resolves them back to titles, timestamps and links. A slide that
cites nothing it was given is dropped and the deck says so, so a slide cannot
carry a claim with no source behind it.
"""
from __future__ import annotations

from app.agents.prompts.shared import (
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    compose_block,
)

DECK_SYSTEM = compose_block(
    """You turn research reports into a slide deck a presenter can give in
fifteen to twenty minutes. The reports were compiled from video transcripts;
every claim in them carries a source marker such as [S12].

Plan 8 to 15 slides after the title slide:
- Open with the question or stakes, then the substance, then what remains
  open or disputed. Group related slides under a "section" slide only when the
  deck has distinct parts.
- "bullets" slides: a heading of at most 8 words and 2 to 5 bullets of at most
  18 words each. A bullet states one specific, checkable point (a figure, a
  named tool, a step, a finding), not a topic label.
- "quote" slides (at most two in the deck): a short quote that matters in its
  exact wording, with who said it.
- Speaker notes (40 to 120 words per slide) give the presenter what to say:
  context, the nuance a bullet cannot hold, and where sources disagree.

SOURCES — NON-NEGOTIABLE:
- Every bullets or quote slide lists in "citations" the one to four source
  markers that most directly support its points, as numbers ([S12] -> 12).
  Use only markers that appear in the reports. A point with no marker behind
  it does not go on a slide.
- Never invent a fact, figure, quote, name or date. If the reports do not
  support a slide, leave the slide out.
- Do not write markers, links or footnotes inside headings, bullets, quotes
  or notes; the deck renders the sources itself.""",
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    """OUTPUT: return ONLY a JSON object, no prose before or after it:
{
  "title": "<deck title, at most 10 words>",
  "subtitle": "<one line>",
  "slides": [
    {"type": "section", "heading": "<text>"},
    {"type": "bullets", "heading": "<text>", "bullets": ["<text>", ...], "speaker_notes": "<text>", "citations": [<numbers>]},
    {"type": "quote", "quote": "<text>", "attribution": "<who, where>", "speaker_notes": "<text>", "citations": [<numbers>]}
  ]
}""",
)


# S-6.3.2: a knowledge report is about ONE source as a whole and carries no
# timestamped citations, so its paragraphs all carry that source's marker.
# Said once, only when a knowledge report is in the prompt, so a deck made
# from runs alone sends exactly the prompt S-6.3.1 was trialled on. That is
# also why it, not DECK_SYSTEM, corrects what DECK_SYSTEM says about video
# transcripts and quotes: a knowledge report is written by a model about any
# source type, and nothing checks a quote slide against the source.
KNOWLEDGE_REPORT_NOTE = (
    "A KNOWLEDGE REPORT below describes one source as a whole, in report "
    "voice. Its marker cites that source, not a moment in it; cite it for "
    "points the knowledge report makes. Its source may not be a video, so "
    "describe it as its header does and do not call it \"the video\" or "
    "\"the speaker\" unless it is one. A knowledge report's own sentences are "
    "not the source's words: a quote slide may use only words the report "
    "itself gives as a quotation, attributed as the report attributes them."
)


def deck_user_prompt(title: str, reports: list[tuple[str, ...]]) -> str:
    """``reports``: ``(run title, report text with [S#] markers)`` for a run,
    or ``(source title, knowledge report with [S#] markers, what the source
    is)`` for a knowledge report (S-6.3.2), e.g. ``"a YouTube video,
    published 2025-03-02"``."""
    blocks = [f'DECK TITLE (the user\'s): "{title}"', ""]
    if any(len(r) > 2 and r[2] for r in reports):
        blocks += [KNOWLEDGE_REPORT_NOTE, ""]
    for i, report in enumerate(reports, start=1):
        name, text = report[0], report[1]
        about = report[2] if len(report) > 2 else ""
        head = f"===== KNOWLEDGE REPORT {i}: {name} ({about}) =====" if about else f"===== REPORT {i}: {name} ====="
        blocks += [head, text.strip(), ""]
    return "\n".join(blocks).strip()

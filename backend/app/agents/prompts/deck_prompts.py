"""Author Studio prompts (I-6): the slide deck outline (S-6.3.1).

One ``author_deck_outline`` call turns one or more research reports into a
deck plan. The reports reach the model with every citation replaced by a
source marker (``[S12]``), and the model cites slides by those numbers only;
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


def deck_user_prompt(title: str, reports: list[tuple[str, str]]) -> str:
    """``reports``: ``(run title, report text with [S#] markers)``."""
    blocks = [f'DECK TITLE (the user\'s): "{title}"', ""]
    for i, (run_title, text) in enumerate(reports, start=1):
        blocks += [f"===== REPORT {i}: {run_title} =====", text.strip(), ""]
    return "\n".join(blocks).strip()

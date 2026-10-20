"""Author Studio prompts (I-6): the book cohesion pass (S-6.1.3).

Two calls frame a book without touching its chapters:

- ``author_book_outline`` reads a digest of each chapter and returns, as
  JSON, a reading order, an optional grouping into parts, a one-paragraph
  bridge into each chapter after the first, and briefs for the introduction
  and conclusion.
- ``author_book_prose`` (cohesion ``full`` only) writes the introduction,
  the bridges, the conclusion and a glossary from that outline plus longer
  excerpts of every chapter.

**Chapter bodies are never sent back through a model.** They stay the
reports' own Markdown with their citations, so the added prose cites nothing
and is told it may only frame what the chapters say. The reports can carry
`[VISUAL @ mm:ss — ...]` spans and non-English quotes, so both prompts carry
the shared visual, language and time contracts (D-066, D-067, D-072).
"""
from __future__ import annotations

from app.agents.prompts.shared import (
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    compose_block,
)

GROUNDING_RULES = """WHAT YOU MAY WRITE — READ CAREFULLY:
- The chapters are research reports compiled from video transcripts. Their
  text below is your ONLY source of facts. Every statement you write must be
  supported by it.
- Never add a fact, figure, name, date, product, study or claim that is not
  in the chapter material, even one you are confident is true. Your job is to
  frame and connect, not to inform.
- A connection you draw between chapters is the editor's reading, not a
  finding: phrase it as such ("read together, these chapters suggest ...").
- Where chapters disagree or cover different periods, say so plainly rather
  than reconciling them.
- Say nothing about the world outside the chapters: not how a subject is
  "often" presented, what people "usually" believe, or how it is "sold".
- Write about the subject, never about the making of this book: do not
  describe how it was assembled, edited, ordered or numbered, or that it has
  an introduction, bridges or a glossary.
- Refer to a chapter by its title or its subject ("the visualisation
  chapter"), never by a number: the printed book numbers its chapters in its
  own reading order, which is not the numbering in this input.
- Write no links, no footnote markers, no citations, no headings, no HTML and
  no Markdown tables. The chapters carry the citations; your prose is framing
  around them and must not look like it is citing anything.
- Plain prose. Light Markdown emphasis (*italic*, **bold**) is allowed."""

OUTLINE_SYSTEM = compose_block(
    """You are the editor of a book assembled from research reports, one report
per chapter. You plan the book; you do not rewrite the chapters, which will be
printed exactly as they are.

Decide:
1. ORDER — the reading order that builds understanding best: foundations
   before applications, general before specific, earlier periods before later
   ones where the subject is historical. Keep the user's order when there is
   no clear reason to change it.
2. PARTS — group consecutive chapters into parts ONLY when there are at least
   four chapters and real thematic seams. Otherwise return no parts.
3. BRIDGES — for every chapter after the first in your order, one short
   paragraph (40 to 90 words) that leads the reader from what came before into
   this chapter: what it adds, how it relates. A bridge refers only to
   material in the chapters.
4. INTRODUCTION BRIEF — 60 to 120 words: what the book covers, why the
   chapters belong together, and how to read it.
5. CONCLUSION BRIEF — 40 to 100 words: the threads a conclusion should draw
   together, including disagreements between chapters.
6. GLOSSARY TERMS — up to 25 specialist terms a newcomer would need, each one
   used in the chapter material. None if the book needs none.""",
    GROUNDING_RULES,
    ENGLISH_OUTPUT_CONTRACT,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    """OUTPUT: return ONLY a JSON object, no prose before or after it:
{
  "order": [<chapter numbers, every chapter exactly once>],
  "parts": [{"title": "<part title>", "chapters": [<chapter numbers, consecutive in your order>]}],
  "bridges": [{"chapter": <chapter number>, "text": "<one paragraph>"}],
  "introduction_brief": "<text>",
  "conclusion_brief": "<text>",
  "glossary_terms": ["<term>", ...]
}
Chapter numbers are the numbers given in the input. "parts" may be [].""",
)

PROSE_SYSTEM = compose_block(
    """You are the editor of a book assembled from research reports, one report
per chapter. The plan for the book is fixed (below). Write the book's framing
prose; the chapters themselves will be printed exactly as they are.

Write:
1. INTRODUCTION — two to four paragraphs, at most 400 words: what the book
   covers, why these chapters belong together, and what the reader will be
   able to do or understand after it.
2. BRIDGES — for each chapter listed in the plan's bridges, one paragraph of
   40 to 90 words leading the reader into that chapter. Improve on the plan's
   draft where you can; keep its chapter number in the marker. Chapter numbers
   in this input are reading positions (1 is read first).
3. CONCLUSION — two to four paragraphs, at most 400 words, drawing together
   the threads across chapters, including where they disagree or leave
   questions open. No new information.
4. GLOSSARY — one entry per term in the plan that the chapters actually use,
   plus any you find essential (25 at most). Each definition is one or two
   sentences, at most 40 words, built ONLY from what the chapter material says
   about the term. If the chapters use a term without explaining it, leave
   the term out; never complete a definition from general knowledge.""",
    GROUNDING_RULES,
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    VISUAL_ANNOTATION_CONTRACT,
    """OUTPUT: plain text in exactly these marked sections, in this order, and
nothing before the first marker. Each marker is alone on its line.

=== INTRODUCTION ===
<paragraphs separated by a blank line>
=== BRIDGE <chapter number> ===
<one paragraph>
(one BRIDGE section per bridge in the plan)
=== CONCLUSION ===
<paragraphs separated by a blank line>
=== GLOSSARY ===
<term> :: <definition>
(one entry per line)""",
)

# Why marked sections and not JSON for the prose: on the first live run
# (2026-10-19) claude-sonnet-5 twice returned JSON a parser could not read,
# once with paragraph breaks inside strings and once with unescaped quotation
# marks. Prose is full of both; the outline, which is short structured data,
# stays JSON.


def outline_user_prompt(book_title: str, digests: list[dict]) -> str:
    """``digests``: ``{number, title, words, headings, excerpt}`` per chapter
    in the user's order."""
    blocks = [f'BOOK TITLE: "{book_title}"', f"CHAPTERS: {len(digests)}", ""]
    for d in digests:
        headings = "; ".join(d["headings"]) or "(none)"
        blocks += [
            f"===== CHAPTER {d['number']}: {d['title']} ({d['words']} words) =====",
            f"Sections: {headings}",
            "Opening material:",
            d["excerpt"] or "(no text)",
            "",
        ]
    return "\n".join(blocks).strip()


def prose_user_prompt(book_title: str, plan: dict, digests: list[dict]) -> str:
    """``plan``: the validated outline; ``digests`` carry longer excerpts,
    listed in the plan's reading order."""
    import json

    blocks = [
        f'BOOK TITLE: "{book_title}"',
        "PLAN (fixed):",
        json.dumps(plan, ensure_ascii=False, indent=2),
        "",
        "CHAPTER MATERIAL, in reading order:",
        "",
    ]
    for d in digests:
        headings = "; ".join(d["headings"]) or "(none)"
        blocks += [
            f"===== CHAPTER {d['number']}: {d['title']} ({d['words']} words) =====",
            f"Sections: {headings}",
            d["excerpt"] or "(no text)",
            "",
        ]
    return "\n".join(blocks).strip()

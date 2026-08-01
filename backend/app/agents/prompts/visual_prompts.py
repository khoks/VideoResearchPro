"""Prompts for the visual-understanding agent — R1 / S-1.18.1.

Two stages, two very different jobs:

* `SELECT_MOMENTS_PROMPT` reads a timestamped transcript and decides WHERE
  something visual matters. It never sees an image. Its whole job is to spend
  a scarce budget well — every moment it picks costs a vision call, and every
  moment it misses is invisible forever.
* `DESCRIBE_FRAME_PROMPT` looks at one captured still alongside the words
  spoken around it, and answers the only question that justifies the call:
  *what does the picture add that the words do not?*
"""
from __future__ import annotations

from app.agents.prompts.shared import ENGLISH_OUTPUT_CONTRACT, compose_block

SELECT_MOMENTS_PROMPT = """You are selecting moments in a video where the PICTURE carries information the words do not.

VIDEO: {video_title}
CHANNEL: {channel_name}
DURATION: {duration_label}

TRANSCRIPT (timestamped):
{transcript}

YOUR TASK
Pick at most {max_frames} timestamps where a still frame would add real information. Fewer is fine. Zero is a legitimate answer for a video that is purely someone talking.

WHAT TO LOOK FOR
Deictic language is the strongest signal — the speaker pointing at something you cannot see:
- "as you can see here", "look at this", "this graph shows", "over on the left", "notice how", "right there"
- reading values aloud that must be coming from somewhere: "so that's 47% versus 12%"
- narrating an action: "so I click into settings and", "now watch what happens"
Also worth capturing:
- demonstrations of a physical object, device, or material
- slides, charts, diagrams, tables, code, or dashboards being discussed
- screen shares, software walkthroughs, UI being navigated
- before/after comparisons, results being revealed
- anything the speaker explicitly directs attention to

WHAT NOT TO PICK
- talking heads, intros, outros, sponsor reads, sign-offs
- moments where the words are already complete on their own
- b-roll and stock footage that decorate rather than inform
- several timestamps inside the same continuous demonstration of the SAME
  thing — pick the one moment where it is most fully shown
- a moment purely because it sounds interesting; the test is visual, not verbal

TIMING
Choose the timestamp where the thing is most likely to be FULLY on screen.
Speakers usually say "as you can see" a beat BEFORE or WHILE the visual is up, rarely after — so land on or just after the cue, never before it.
Keep your picks at least {min_gap} seconds apart.

OUTPUT
Return ONLY a JSON array, no prose, no code fence:
[
  {{"timestamp_seconds": 132, "reason": "speaker says 'this chart shows' and starts reading figures aloud", "expected_content": "a chart of quarterly revenue"}}
]
`reason` cites what in the transcript made you pick it. `expected_content` is your guess at what will be on screen — it is a hint for the describer, and being wrong is fine.
Return [] if nothing qualifies. Do not pad to reach {max_frames}."""


DESCRIBE_FRAME_PROMPT = """You are looking at ONE still frame from a video, together with what was being said at that moment.

VIDEO: {video_title}
TIMESTAMP: {timestamp_label}
WHY THIS MOMENT WAS SELECTED: {selection_reason}
EXPECTED (a guess, may be wrong): {expected_content}

WHAT WAS BEING SAID AROUND THIS MOMENT:
{transcript_window}

YOUR TASK
Describe what is ON SCREEN, with one question governing everything you write: **what does this picture add that the words do not?**

RULES
- Describe only what you can actually see. Never infer content from the transcript — the whole point of this step is to add independent evidence, and a description reconstructed from the words is worse than useless because it looks like corroboration.
- Read out the specifics: axis labels, units, legend entries, numbers, headings, visible code, UI labels, on-screen text. These are the payload. "A bar chart" is nearly worthless; "a bar chart of revenue by quarter, Q1 $2.1M rising to Q4 $5.8M" is the reason this call was made.
- If text is too small or blurred to read with confidence, say so explicitly rather than guessing. A wrong number stated confidently becomes a false claim in a report that nothing downstream can catch.
- Do not transcribe or paraphrase the speech. It is already in the transcript.
- Do not editorialise about the video or the speaker.
- If the frame shows nothing informative — a talking head, a logo, a transition, a black frame, a slide already fully described by the words — set `informative` to false and say briefly why. This is a normal and useful outcome; do not manufacture significance to justify the capture.
- Calibration check before you answer: if your own description contains a phrase like "there is no readable text", "no chart or code is visible", or "no specific data is shown", then the frame is NOT informative — set the flag to false. Describing the absence of content is not adding content. A frame whose only payload is "someone is presenting" costs a reader attention and gives nothing back.
- 2-4 sentences when informative. Dense, specific, no preamble.

{english_contract}

OUTPUT
Return ONLY a JSON object, no prose, no code fence:
{{"informative": true, "description": "...", "reads_as": "chart|slide|screen|object|diagram|code|text|scene|person|other", "legibility": "clear|partial|unreadable"}}"""


def describe_frame_prompt(
    *,
    video_title: str,
    timestamp_label: str,
    selection_reason: str,
    expected_content: str,
    transcript_window: str,
) -> str:
    return DESCRIBE_FRAME_PROMPT.format(
        video_title=video_title,
        timestamp_label=timestamp_label,
        selection_reason=selection_reason or "(not recorded)",
        expected_content=expected_content or "(none)",
        transcript_window=transcript_window or "(no transcript available)",
        english_contract=compose_block(ENGLISH_OUTPUT_CONTRACT),
    )

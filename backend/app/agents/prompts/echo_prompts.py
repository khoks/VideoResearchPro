"""Prompts for Echo share processing (S-3.7.2).

``SHARE_OCR_PROMPT`` is transcription, not a deliverable: like Whisper's
``transcribe`` task it keeps the text in its original script and language.
The English-output contract (D-066) applies later, to the reports and answers
that read this text, not to the copy of what an image says.
"""
from __future__ import annotations

# Returned verbatim by the model when an image holds no readable text.
NO_TEXT_SENTINEL = "NO_TEXT"

SHARE_OCR_PROMPT = f"""You are reading an image the user saved to their personal archive. Copy out the text visible in it, exactly as written.

Rules:
- Transcribe. Do not describe, summarise, explain or translate.
- Keep every piece of text in its original script and language: Devanagari stays Devanagari, and mixed Hindi-English stays mixed.
- Keep the reading order and the line breaks. Separate distinct blocks (a post and its replies, a caption, a headline) with a blank line.
- Keep names, handles, dates and numbers as shown. Leave out interface chrome that carries no content, such as status-bar icons and buttons labelled "Like", "Reply" or "Share".
- Write [illegible] for a word you cannot read rather than guessing it.
- If the image contains no readable text, reply with exactly {NO_TEXT_SENTINEL}
- Reply with the text only: no preamble, no quotation marks, no commentary."""

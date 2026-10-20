# Book cohesion pass: blind judging (S-6.1.3)

**Status:** complete (2026-10-19). Protocol fixed before any edition was generated or judged; results appended below it. Outcome: `none` stays the default ([D-093](../decisions.md#d-093--book-cohesion-pass-ships-opt-in-none-stays-the-default-after-two-blind-rounds-2026-10-19)).

## Question

Does the cohesion pass (`cohesion=full`: an `author_book_outline` call and an `author_book_prose` call that add an introduction, bridges, parts, a conclusion and a glossary around unchanged chapters) make a better book than the deterministic concatenation (`cohesion=none`), without adding unsupported claims? The plan ([l2-author-studio.md](../plans/l2-author-studio.md)) makes `full` the default only if this holds.

## Material

Three books from real research runs in the development library (one tenant), with Q&A included as the UI does by default:

| Book | Chapters (runs) |
|---|---|
| 1 | matplotlib and seaborn data visualisation tutorials; machine learning explained in Hinglish |
| 2 | Indian startup founder podcast (Hinglish); personal finance and career advice in Hinglish |
| 3 | all four of the above |

Each book is generated twice from the same database copy: `none` and `full`, with the registry defaults (`author_book_outline` = openai gpt-5.5 medium, `author_book_prose` = anthropic claude-sonnet-5 medium). Generation is by `backend/scripts/book_cohesion_trial.py`; usage and cost come from each output's `usage_json`.

## Judging

`backend/scripts/judge_pair.py --rubric book`, the E-1.14 method (D-055): each judge sees both editions under labels A and B assigned by an independent coin flip, judges cohesion, orientation and accuracy of framing (every framing statement must be supported by the chapters), lists unsupported claims and misframings with quotes, and states an overall preference. No corpus is passed: the chapters are in both editions and are the only ground truth for the framing.

Judges, three families: `openai:gpt-5.5:medium`, `anthropic:claude-opus-5:medium`, `google:gemini-3.1-pro-preview:medium`. The prose model is Anthropic; Opus is a different model from Sonnet but the same family, so its verdict is reported separately as well.

## Decision rule (fixed in advance)

`full` becomes the default for new books if **all** of these hold:

1. Across the 9 verdicts (3 books × 3 judges), at least 6 prefer `full`, and on no book does a majority of judges prefer `none`.
2. The two non-Anthropic judges alone also prefer `full` in at least 4 of their 6 verdicts (guards against same-family preference).
3. Unsupported claims plus misframings attributed to `full`, summed over all judges, average at most 1 per book (at most 3 in total), after reading each one to discard any that quote chapter text rather than framing.

Otherwise `none` stays the default and `light` / `full` stay opt-in. `light` is not judged.

Cost per book is recorded from `usage_json` whatever the outcome.

## Results

### Round 1 (prompts as first written)

**Deviation from the protocol:** `gemini-3.1-pro-preview` had used its daily quota (250 requests per model per day, shared with other sessions on the same key; reset in about seven hours), so `google:gemini-3.6-flash:medium` judged instead. Recorded before its verdicts were read.

**Two defects found in generation before judging**, both fixed and covered by tests:
- The prose model put literal newlines and then unescaped quotation marks inside JSON strings, so the parser rejected its answer twice. The prose call now answers in marked plain-text sections; JSON is still read as a fallback.
- When the outline reordered the chapters (book 3), the prose cited the user's original chapter numbers ("printed in the order 4, 2, 1, 3"), which do not match the printed headings. Found in the round 1 verdicts and fixed for round 2: the prose call now sees chapters numbered in reading order, and both prompts refer to chapters by title.

| Book | Judge | Prefers | Cohesion full / none | Orientation full / none | Accuracy of framing full / none | Flags on full |
|---|---|---|---|---|---|---|
| 1 | gpt-5.5 | full | 8 / 3 | 9 / 5 | 7 / 10 | 10 |
| 1 | claude-opus-5 | full | 7 / 3 | 8 / 3 | 9 / 10 | 2 |
| 1 | gemini-3.6-flash | full | 8 / 3 | 9 / 2 | 10 / 10 | 0 |
| 2 | gpt-5.5 | full | 8 / 4 | 9 / 5 | 8 / 10 | 3 |
| 2 | claude-opus-5 | full | 7 / 3 | 8 / 3 | 9 / 10 | 2 |
| 2 | gemini-3.6-flash | full | 9 / 3 | 9 / 2 | 10 / 10 | 0 |
| 3 | gpt-5.5 | full | 7 / 2 | 8 / 4 | 8 / 10 | 4 |
| 3 | claude-opus-5 | full | 7 / 3 | 8 / 3 | 8 / 10 | 4 |
| 3 | gemini-3.6-flash | full | 8 / 2 | 8 / 1 | 8 / 10 | 2 |

"Flags" are unsupported claims plus misframings attributed to the full edition. All quote framing text, none quote chapter text, so none is discarded under rule 3.

- Rule 1: 9 of 9 prefer `full`. **Met.**
- Rule 2: the non-Anthropic judges prefer `full` in 6 of 6. **Met.**
- Rule 3: 27 flags, against at most 3. **Not met.**

**Round 1 outcome: `none` stays the default.**

What the flags are, read one by one (not part of the rule): some are real, some are the judge's error.
- **Real:** framing about the world outside the chapters ("what is often sold as a single data skill"); remarks about how the book was made ("ordered as the chapters were conceived"); glossary definitions completed from general knowledge (seaborn's `clustermap` "combining a heatmap with hierarchical clustering", which the chapter never says); the wrong chapter numbers above; and the edition disclosure line itself, which the judges could not know was true.
- **Judge error:** some flagged statements are in the chapters, for example the publication span 2018-11-22 to 2026-09-28 and "genuinely awkward in raw matplotlib".

Cost per book (from `usage_json`, registry defaults, prices as of 2026-10-19):

| Book | Chapters | Outline in / out tokens | Prose in / out tokens | Cost |
|---|---|---|---|---|
| 1 | 2 | 3,130 / 1,003 | 9,978 / 2,631 | $0.092 |
| 2 | 2 | 3,247 / 1,031 | 9,941 / 3,022 | $0.097 |
| 3 | 4 | 4,738 / 1,738 | 16,726 / 3,094 | $0.140 |

### Round 2 protocol (fixed before round 2 was generated)

The prompts change to target the real flags. Both prompts now forbid statements about the world outside the chapters and about how the book was made, and they refer to chapters by title. The prose call sees reading-order numbers, and glossary definitions are built only from what the chapters say, with a term left out when the chapters do not explain it. The chapters and the `none` editions are unchanged; only the `full` editions are regenerated.

Judges: `openai:gpt-5.5:medium`, `anthropic:claude-opus-5:medium`, `google:gemini-3.6-flash:medium` (the Pro quota is still exhausted). The decision rule is unchanged, including rule 3's strict count. If round 2 meets all three rules, `full` becomes the default. Otherwise `none` stays the default, with `light` and `full` as opt-in. There is no round 3.

### Round 2 (revised prompts)

The full editions were regenerated with the revised prompts. Book 3 now has two parts, and no framing cites a chapter number.

| Book | Judge | Prefers | Cohesion full / none | Orientation full / none | Accuracy of framing full / none | Flags on full |
|---|---|---|---|---|---|---|
| 1 | gpt-5.5 | full | 8 / 2 | 8 / 4 | 7 / 10 | 12 |
| 1 | claude-opus-5 | full | 7 / 3 | 8 / 3 | 9 / 10 | 2 |
| 1 | gemini-3.6-flash | full | 9 / 3 | 9 / 2 | 10 / 10 | 0 |
| 2 | gpt-5.5 | full | 8 / 4 | 9 / 6 | 8 / 10 | 4 |
| 2 | claude-opus-5 | full | 7 / 3 | 8 / 3 | 9 / 10 | 1 |
| 2 | gemini-3.6-flash | full | 10 / 3 | 10 / 1 | 10 / 10 | 0 |
| 3 | gpt-5.5 | full | 8 / 3 | 9 / 5 | 8 / 10 | 5 |
| 3 | claude-opus-5 | full | 7 / 3 | 8 / 3 | 8 / 10 | 3 |
| 3 | gemini-3.6-flash | full | 9 / 2 | 9 / 1 | 10 / 10 | 0 |

- Rule 1: 9 of 9 prefer `full`. **Met.**
- Rule 2: the non-Anthropic judges prefer `full` in 6 of 6. **Met.**
- Rule 3: 27 flags, against at most 3. **Not met.** gpt-5.5 listed most of its sentences under both headings (book 1: 6 sentences, 12 flags), and the count follows the rule as written.

**Round 2 outcome: `none` stays the default.** Recorded as [D-093](../decisions.md#d-093--book-cohesion-pass-ships-opt-in-none-stays-the-default-after-two-blind-rounds-2026-10-19).

What the round 2 flags are (not part of the rule):
- The edition disclosure line, again.
- Claims about the world outside the chapters still slip through ("usually taught apart but rarely reflected on together").
- Interpretive readings across chapters ("they trace a plausible arc from inspecting data visually to formalising it into a model"). Judges disagree on whether that is framing or misrepresentation: gemini-3.6-flash flagged none of them.
- Characterisations of one chapter that a judge reads as overstated ("dated to their origin", "a single spectacular outcome").

Cost per book in round 2: $0.111, $0.098 and $0.169 (books 1, 2, 3). A live book generated through the UI and the worker cost $0.10 against a $0.12 estimate.

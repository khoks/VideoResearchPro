# Book cohesion pass: blind judging (S-6.1.3)

**Status:** protocol fixed before any edition was generated or judged (2026-10-19). Results are appended below the protocol; the protocol is not edited after the run.

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

_(appended after the run)_

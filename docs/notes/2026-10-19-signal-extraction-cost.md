---
status: measurement
story: S-3.3.2
date: 2026-10-19
---

# Signal extraction: cost and yield on synthetic writers (S-3.3.2)

The parent brief asked for extraction "on the economy tier, batched, with costs measured". This note records the measurement. Raw numbers: [2026-10-19-signal-extraction-cost.json](2026-10-19-signal-extraction-cost.json). Script: `backend/scripts/measure_signal_extraction.py`.

## Method

- **Writers.** Three synthetic writers from `backend/tests/fixtures/echo_voice/personas.json`; none of it is anyone's real words:
  - Asha writes short, questioning English.
  - Bharat writes long, formal English with parentheses and semicolons.
  - Chetan writes casual romanised Hinglish with emoji.
- **Inputs per writer.** 24 notes and 10 questions.
- **Why not real data.** The dev database holds no notes and 4 questions, so there was nothing real to measure.
- **Database.** A fresh scratch SQLite file per writer, never the dev database.
- **Model.** `openai:gpt-5.6-luna:off`, the registry's default for `echo_extract_signals`.
- **Runs.**
  - The **backlog run** reads everything the writer has.
  - Six held-out texts are then added as notes, and the **incremental run** reads only those.
  - Two repeats.
- **Cost.** Computed from the provider's reported token counts and `model_pricing.py` (Luna at $0.20 in and $1.20 out per million).

## Results

| Writer | Repeat | Inputs | Words | Backlog tokens in / out | Backlog cost | Backlog time | Signals created | Examples dropped | Incremental cost (+6) | Incremental merged / new | Live signals |
|---|---|---|---|---|---|---|---|---|---|---|---|
| asha | 1 | 34 | 404 | 1,230 / 1,121 | $0.0016 | 18.1 s | 11 | 0 | $0.0010 | 10 / 0 | 11 |
| bharat | 1 | 34 | 792 | 1,685 / 1,515 | $0.0022 | 10.9 s | 14 | 0 | $0.0015 | 13 / 0 | 14 |
| chetan | 1 | 34 | 425 | 1,476 / 1,286 | $0.0018 | 10.0 s | 16 | 0 | $0.0015 | 15 / 0 | 15 |
| asha | 2 | 34 | 404 | 1,230 / 1,171 | $0.0017 | 8.2 s | 14 | 0 | $0.0011 | 12 / 0 | 14 |
| bharat | 2 | 34 | 792 | 1,685 / 1,307 | $0.0019 | 11.1 s | 14 | 0 | $0.0010 | 11 / 0 | 14 |
| chetan | 2 | 34 | 425 | 1,476 / 1,070 | $0.0016 | 9.0 s | 17 | 0 | $0.0014 | 14 / 0 | 16 |

- **Backlog cost:** $0.0053 per 100 inputs, or $0.0331 per 10,000 words.
- **Incremental cost:** $0.0206 per 100 inputs. Per input this is higher than the backlog because each call carries the list of known signals, and the model lists again the ones the new text supports. That re-listing is how a signal's weight grows.
- **Scale.** The epic's acceptance case (20 notes and 50 questions) is one batch, about $0.004.
- **Reliability.** No call failed. Examples dropped by the exact-quote check: 0 in this run. The run before the two fixes below dropped 1 of about 200 examples.
- **Latency.** 8 to 18 s per backlog batch and 5 to 8 s per incremental batch. A run is a background task, so latency only decides when signals appear.

## What the first run found, and the code changed

1. **Bharat was given "Asks questions often", but his notes contain no questions.** Stylometry had counted his questions to the Q&A, which are always questions. Cadence now reads prose only (notes and shares).
2. **Chetan's personality signals were duplicated by language.** The model labelled the same Hinglish passages `mixed` on one run and `hi-Latn` on the next, and the merge key includes the language. Two changes:
   - A **style** signal now takes its language from the passages its examples quote, as `language_of` reads them. This is deterministic.
   - A **personality** signal has no language, because a belief is the same whatever language it is said in.

   After the change, every incremental run merged into existing rows (merged / new above) and created no duplicates.

## Limits

- Synthetic writers only. The quality of what was learned is not graded here; S-3.3.4's harness asks whether drafts that use the signals sound more like the writer.
- One model. Cost scales with the registry entry; a mid-tier model would cost about four times as much.

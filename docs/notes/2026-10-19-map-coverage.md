# Map-stage source coverage: the batch-size defect (2026-10-19)

**Status:** measurement protocol, fixed before the measurement ran. Results are appended below.

## What R1 run 6 exposed

Run 6 of the R1 protocol ([2026-10-18-r1-visual-measurement.md](2026-10-18-r1-visual-measurement.md)) lost on substance. Both judges named the same cause: the annotated report never engages two of the ten channels. The persisted intermediates (S-1.14.6) show the loss happens at the **map** stage, before the visual annotations could matter:

| Run / arm | Batch | Chunks | Items | Output tokens | Items per chunk |
|---|---|---|---|---|---|
| 5 ON | 0 | 400 | 92 | 14,091 | 0.23 |
| 5 ON | 1 | 117 | 62 | 11,189 | 0.53 |
| 5 OFF | 0 | 383 | 106 | 20,665 | 0.28 |
| 5 OFF | 1 | 27 | 37 | 5,053 | 1.37 |
| 6 ON | 0 | 400 | 101 | 15,093 | 0.25 |
| 6 ON | 1 | 117 | 77 | 12,477 | 0.66 |
| 6 OFF | 0 | 383 | 140 | 20,891 | 0.37 |
| 6 OFF | 1 | 27 | 43 | 5,570 | 1.59 |

The map model (`report_map_chunks` = gpt-5.6-luna, reasoning off) has a 48K-token completion budget per 120K-token batch (`_MAP_EXTRACTION_RATIO` 0.40, `_QUALITY_BATCH_CAP` 120K). It writes 14K to 21K and stops. The budget is never binding, so S-1.14.8 and S-1.14.13's assumption no longer holds: raising the ratio cannot buy coverage. Item yield per call is roughly fixed, which means:

- A source's share of the report depends on which batch it lands in, a fivefold to sixfold density difference in this job.
- Sources late in a large batch can get **zero** items. Absent Data and Onur Baltaci (videos 8 and 9 of 11) got none in run 5 OFF, run 5 ON and run 6 ON, and 9 and 8 in run 6 OFF.

This affects every report, not just R1. On the 200-video reference corpus (about 12 batches of about 17 sources each), the same mechanism would silently drop sources in every batch.

## Experiment

Re-run only the map stage (`scripts/measure_map_coverage.py`) on job `419e691d`'s replayed chunks (both arms, gpt-5.5 descriptions in ON, as in run 6). The only change is the patched `_QUALITY_BATCH_CAP`: **120K (control), 60K, 30K, 15K**. One process per (arm, cap).

Metrics per (arm, cap):
- **zero-item sources:** sources with at least 10 chunks and no items;
- **floor ratio:** the lowest per-source items-per-chunk divided by the median;
- **density CV;**
- total items, batches and seconds.

## Decision rule (fixed before the run)

1. Choose the **largest** cap at which, in **both** arms, no eligible source has zero items **and** the floor ratio is at least **0.4**. The largest qualifying cap is preferred because it means the fewest calls.
2. If the chosen cap's floor ratio is within 0.1 of the threshold in either arm, repeat that config once. It must pass again.
3. If no cap qualifies, a per-source coverage guarantee is required (re-map any eligible source that a batch left empty) and gets measured the same way.
4. The fix is then measured end to end. A new R1 run (run 7) is pre-registered separately and judged against the same four rules as run 6.

## Results

### Experiment 1: invalid below 120K, but it found a second defect

| Arm | Cap | Batches | Items | Zero-item sources | Floor ratio |
|---|---|---|---|---|---|
| ON | 120K | 2 | 276 | 0 | 0.25 |
| ON | 60K | 3 | 241 | 0 | 0.385 |
| ON | 30K | 6 | 249 | 5 | 0 |
| ON | 15K | 11 | 71 | 9 | 0 |
| OFF | 120K | 2 | 115 | 1 | 0 |
| OFF | 60K | 3 | 268 | 0 | 0.044 |
| OFF | 30K | 5 | 217 | 2 | 0 |
| OFF | 15K | 9 | **0** | 10 | 0 |

Smaller caps did worse. That is an artefact, confirmed directly: one 50-chunk, 14,791-token batch at the default completion budget (40% of the cap, 5,916 tokens) stops with `finish_reason=length`. Its JSON does not parse, so the batch yields 0 items. With 32K the same batch stops on its own at 6,975 tokens with 64 items (1.28 per chunk).

**Defect 2: a truncated map response is silent loss.** `_invoke_batch` returns `{"raw": text}` on a parse failure and counts the batch as successful (`map_batches_failed` = 0). Reduce then passes the half-written JSON to the composer as one unattributed "fact". The 40% ratio only looked safe because, at the 120K cap, the model self-limits to 14K to 21K output tokens.

Rows below 120K therefore measure truncation, not batch size, and do not count for the decision rule. The 120K control rows stand.

### Run 6's attribution errors point at batching as well

The "0.13.2 visible on screen" error is cross-source. The span is from Simplilearn's video at 2:54, the speech is CodeWithMunnaX's at 2:57, and both sat in one 400-chunk batch. The wrong-script `original`s (a Hindi speaker quoted in Bengali) also come from batches that mix Hindi and Bengali sources. Mixing sources in a batch drives three measured failures: coverage, cross-source modality labels and wrong-script quotes.

### Experiment 2 (amended 2026-10-19, before it ran)

Fixed first, in code: truncation or a parse failure raises, so bisect-retry applies; the map completion budget becomes the batch cap itself, clamped to the model ceiling, and only generated tokens are billed. Configurations, both arms:
- `packed` at 120K (control, fixed budget), 60K and 30K: today's batching, sources packed in order;
- `source` at 30K: each batch holds exactly one source, and a source larger than the cap is split into several batches of its own.

Extra metrics, from the persisted map items:
- cross-source `shown`/`both` labels (an item whose OWN source has no span within its moment ±60 s);
- `original`s dropped for wrong script;
- map seconds at concurrency 4.

The decision rule is unchanged (largest qualifying config, both arms: no zero-item eligible source, floor ratio ≥ 0.4), with one tie-break fixed now. If `source` qualifies, it wins over a qualifying `packed` cap whenever it also has fewer cross-source labels and fewer wrong-script drops, because those are correctness defects, not coverage.

### Experiment 2 (truncation fixed; concurrency 4)

| Config | Arm | Calls | Items | Zero-item sources | Floor ratio | Worst-source density | Unsupported shown labels | Wrong-script quotes | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| packed 120K | ON | 2 | 135 | 1 | 0.000 | 0.00 | 2 | 2 | 54 |
| packed 120K | OFF | 2 | 158 | 0 | 0.143 | 0.09 | 0 | 0 | 95 |
| packed 60K | ON | 3 | 278 | 0 | 0.446 | 0.31 | 1 | 1 | 88 |
| packed 60K | OFF | 3 | 234 | 0 | 0.412 | 0.30 | 0 | 0 | 93 |
| packed 60K (repeat) | ON | 3 | 288 | 0 | **0.388** | 0.29 | 2 | 0 | 96 |
| packed 60K (repeat) | OFF | 3 | 298 | 0 | **0.344** | 0.36 | 0 | 1 | 106 |
| packed 30K | ON | 6 | 510 | 0 | 0.589 | 0.61 | 6 | **16** | 125 |
| packed 30K | OFF | 5 | 427 | 0 | 0.289 | 0.40 | 0 | 0 | 141 |
| source 30K | ON | 13 | 653 | 0 | 0.518 | 0.77 | 6 | **0** | 144 |
| source 30K | OFF | 13 | 579 | 0 | 0.384 | 0.78 | 0 | 0 | 161 |

**By the pre-registered rule, nothing qualifies.**
- Packed 60K passed once (0.446 and 0.412). Within 0.1 of the threshold, it was repeated as rule 2 requires, and failed (0.388 and 0.344).
- Source 30K missed on OFF (0.384).
- Rule 3's literal guarantee (re-map any eligible source left empty) changes nothing at any cap of 60K or below, because none of them leaves a source empty.

**The floor-ratio threshold was mis-specified.** It assumed per-source density would be even under fair batching, and it is not. In source mode no source competes with another for a call's output, yet the floor sources are the two long non-English lectures:
- CodeWithMunnaX: 120 chunks, Bengali, 0.78 items per chunk;
- DeepLoop Circle: 112 chunks, Hindi, 0.85 items per chunk.

Short English tutorials sit at 2 to 4. That spread is content density (long lectures repeat themselves; dense tutorials do not), not starvation. A ratio against the median penalises it whatever the batching. Starvation shows instead in the **worst-source density**: 0.00 to 0.09 for packed 120K (sources cut off), about 0.3 for packed 60K, 0.4 to 0.6 for packed 30K, 0.77 to 0.78 for source.

**Decision (post hoc, labelled as such; [D-090](../decisions.md)):** default to `source` batching at a 30K cap.
- *Starvation:* no source shares a call with another, so none is starved. Worst-source density 0.77 against 0.00 for the old default.
- *Wrong-script quotes:* zero. Packing Hindi and Bengali sources together produced 16 at a 30K cap and 2 at 120K. Source batching removes the cause the R5 check (#294) only filters.
- *Cross-source modality labels:* the run-6 "0.13.2 on screen" error cannot occur when one call sees one video's spans.
- *Costs:* about 13 calls instead of 2 (about 150 s at concurrency 4, against 55 to 95 s), and about 4.5 times as many items for compose to absorb.

Whether that volume improves or hurts the finished report is the open question. Run 7 answers it, and `REPORT_MAP_BATCHING=packed` stays one setting away.

**Not settled by this experiment:** unsupported `shown`/`both` labels (an item whose own source shows nothing within ±60 s) persist at about 1% of items in every config, including source mode. That is within-source mislabelling, so batching cannot fix it.

## Run 7: pre-registered (2026-10-19, before it runs)

Same job and descriptions as run 6, regenerated on the code with source batching at 30K. It makes two comparisons from one replay:

1. **R1 (ON vs OFF):** the same four rules as run 6, unchanged.
2. **Batching (run-7 OFF vs run-6 OFF, both without annotations):** a blind three-family judge pair on substance. The source-batched report must be preferred by at least two of three families, and its confirmed fabrications must not exceed the packed report's. If it fails, the default goes back to `packed`. Gemini 3.1 Pro is the third family; there are no substitutes.

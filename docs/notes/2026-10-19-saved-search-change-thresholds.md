# Saved-search change detection — threshold calibration protocol (S-8.3.3)

**Status:** pre-registered 2026-10-19, committed and merged before any overlap or distance was computed from the app's Q&A history. Results are appended below the rule, never edited into it.

## Question

A saved search (S-8.3.2) re-asks a pinned library question on a schedule. The plan ([m3-saved-searches-alerts](../plans/m3-saved-searches-alerts.md)) marks a run **changed** when either deterministic signal crosses its threshold, and calls a cheap judge only when the two disagree:

- **J**, the Jaccard overlap between the run's cited document set and the previous run's. Below the threshold → changed.
- **D**, the cosine distance (1 − cosine similarity) between the run's answer and the previous answer, embedded with the library's own `paraphrase-multilingual-MiniLM-L12-v2` (`embedding_service.encode`). Above the threshold → changed.

An answer hash cannot do this job, because the answering model is not deterministic: almost every re-ask would read as changed. No product publishes its algorithm and no published cosine value for "the same answer" exists, so both thresholds are set from the app's own history by the rule below, which is fixed before any value is seen.

## Data

- A **read-only copy** of the dev database. Nothing the running backend uses is written.
- **Population:** every row of `library_qa_exchanges` and `qa_exchanges` (job Q&A), all tenants.
- **Re-ask pairs (U).** Two exchanges are paired when they belong to the same tenant and the same context, and their questions are equal after normalisation. Same context means the same job for job Q&A, or the library for library Q&A. Normalisation casefolds, collapses whitespace and strips trailing `?!.` and spaces. Each exchange is paired with the next identical one in time, so a question asked n times gives n − 1 pairs.
- **Unchanged-corpus filter.** A library pair is kept only if no `document_visibility` row for that tenant has a `created_at` between the two exchanges. A job pair is always kept, because a finished run's approved set does not change.
- **Negative control (N).** Each U pair's first exchange is also paired with one other exchange of the same tenant and context with a different normalised question, drawn with `random.Random(833)`. N pairs are skipped where no such exchange exists.
- **J on both empty.** When neither answer cites anything, J = 1.0.

## Decision rule (fixed now)

1. **Minimum sample: |U| ≥ 20.** Below that, the history does not hold enough re-asks to calibrate. The detector then ships with the **priors** J < 0.50 and D > 0.15. This is recorded as *calibration pending* in the S-8.3.3 PR and in a follow-up task, to re-run this protocol once |U| ≥ 20. Nothing is tuned by eye in between.
2. **D threshold** is the 95th percentile of D over U, rounded **up** to the next 0.01. A re-ask over an unchanged library then trips the embedding signal alone at most about 5% of the time.
3. **J threshold** is the 5th percentile of J over U, rounded **down** to the next 0.05. The citation signal alone then trips at most about 5% of the time. If that percentile is 1.0, because re-asks always cite the same set, the threshold is 0.95.
4. **Sanity check on D.** On N, at least 80% of pairs must have D above the chosen threshold. If not, the embedding signal cannot tell a different answer from model noise. D still ships at the rule's value, but the judge is then called on every run where J did not trip. That is recorded with the numbers.
5. **Reported, not decided on:**
   - the disagreement rate on U, meaning how often exactly one signal trips, which is the share of runs that would call the judge
   - the both-signal false-alarm rate on U
   - |U|, |N| and the split between library and job pairs

## What is published

Only aggregates: the counts, percentiles, chosen thresholds and rates above. No question or answer text is published, because the repository is public.

## Known limits

- **Re-asks are a proxy.** A same-question pair asked minutes apart is the closest thing in the history to "a saved search re-run over an unchanged library", but people re-ask when the first answer disappointed, so U may be noisier than real saved-search runs. That bias makes the thresholds conservative: they notify less.
- **One embedder and one language mix.** The thresholds are for MiniLM and this library's mostly English answers. A different embedder, or a corpus answered mostly in another language, needs this protocol re-run.
- **This only calibrates "unchanged".** Whether a crossed threshold means a change worth a notification is the judge's call where the signals disagree, and the click data's (`notifications.read_at`) after that.

---

## Results (2026-10-19, appended after the rule was merged as #323)

Run with `backend/scripts/calibrate_saved_search_thresholds.py` on a copy of the dev database. Aggregates are in [`2026-10-19-saved-search-change-thresholds-results.json`](2026-10-19-saved-search-change-thresholds-results.json).

| Measure | Value |
|---|---|
| Q&A exchanges in the history (library and job) | 4 |
| Re-ask pairs over an unchanged corpus, \|U\| | 2 (job 2, library 0) |
| Negative-control pairs, \|N\| | 2 |

**Decision (rule 1): calibration pending.** |U| is below 20, so no percentile was computed. The detector ships with the priors **J < 0.50** and **D > 0.15** (`SAVED_SEARCH_JACCARD_THRESHOLD`, `SAVED_SEARCH_EMBEDDING_THRESHOLD`). The protocol is re-run unchanged once the history holds 20 re-ask pairs; saved-search runs themselves produce such pairs, filed as T-8.3.3.7.

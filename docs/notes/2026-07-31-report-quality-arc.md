---
status: session record — chronology and rationale, kept for provenance
date: 2026-07-31
covers: D-054 → D-062, E-1.13, E-1.14
---

# The report-quality arc: from "2 channels out of 92" to a measured tier decision

A single session that started as "expose model settings to the user" and ended
by rebuilding the report pipeline, re-tiering the whole LLM stack, and settling
a model-upgrade question on measurement rather than intuition.

This note is the **provenance record**: what the user asked for, what was
found, what was decided, and — importantly — what turned out to be wrong along
the way. The canonical decisions live in [decisions.md](../decisions.md); the
work items in [initiatives.md](../initiatives.md). This is the thread that
connects them.

---

## The user's asks, in order

1. **Expose per-function model settings to users**, with a cost calculator
   benchmarked on the real 200-video AI-topic job, latest pricing across
   OpenAI/Anthropic; investigate why gpt-5.6 showed no reasoning tokens; add
   Gemini research now that a Google key exists. → E-1.13, D-054
2. **"I placed the paid tier google gemini api key now"** → D-054 amendment II
3. **Replicate the entire pipeline with Fable 5 at max thinking** on the same
   200-video corpus, blind-judge against the app defaults, and report how much
   intelligence the cheaper defaults lose. Use the Claude Code subscription,
   not the API key. → E-1.14, D-055
4. **"I would go with your recommendation"** on fixing the funnel first, plus:
   *"the final report also needs some work since its size should be compatible
   with the amount of info and gravitas found in the knowledge extraction of
   videos"* → D-056
5. **"lets rerun the job, and then also look at the selection quality and
   S-1.14.6"** — plus the GPT-5.6 Luna price cut, with the Artificial Analysis
   chart. → D-057, D-058, S-1.14.6
6. **"for a large corpus of a job like AI topic, aren't the qualitative claims
   of 130 still not enough?"** — the question that exposed our own extraction
   ceiling. → D-060
7. **"proceed on S-1.14.13"** → D-059
8. **"after you are done... is there still a gap between the app default
   setting results vs the premium model results, now that we have the full
   picture? Did we change our app defaults to close the gap?"** → D-061
9. **"Lets finish the remaining work and then see if report-compose deserves
   model tier upgrade"** → S-1.14.14, D-062

Two of these questions (#6 and #8) changed the work materially. Neither was a
feature request — both were the user pushing on whether a number was actually
good enough, and both times it wasn't.

---

## What was actually wrong

The original 200-video report was **not** under-modelled. It was starved.

| Stage | Cap | Consequence |
|---|---|---|
| map | `max_tokens=3000` per ~116K-token batch | ≤5.9% of extractable content emitted |
| reduce | `max_tokens=6000` applied **every** pairwise round | 91% of items and 46% of videos lost |
| compose | one call for the entire corpus | 3,848 words, 2 channels cited |

The shipped report cited **2 distinct channels out of 92** and **4 videos out
of 200** while its own executive summary claimed to synthesize 137. A
fidelity audit found **60 of 60** sampled facts from two batches absent from
it — a 100% loss rate on those batches.

Root cause was an interaction, not a single bug: E-1.12 raised batch size to
~116K tokens to fit model windows, but the registry still described that call
as `p95_input=32,000` and the output cap never moved. **The context-window fix
made the loss worse** by pushing more information through an unchanged
aperture.

---

## The corrections — including my own

Several beliefs held during this session turned out to be wrong. Recording
them because the wrong turns are the reusable part:

- **"Reduce deduplicates."** A control pass found **zero** duplicates in map
  output — no exact, substring, or Jaccard≥0.90 matches. The LLM
  merge-and-dedupe could only ever destroy content. Reduce is now
  deterministic and lossless. (D-056)
- **"0.20 extraction ratio is a safety margin."** It was a ceiling: 288K
  tokens against the max-effort control's 609K, so even a perfect model could
  emit less than half of what the corpus supports. The same defect D-056 set
  out to remove, re-introduced one layer up. Invisible while nano was the
  volume model because nano never reached its own allowance. (D-060)
- **"Filter sub-5-minute videos."** Measuring showed it cost **6 of 29**
  preferred channels their only candidates for ~6% more corpus minutes.
  Preferred channels are now exempt: an explicit "include this creator"
  outranks an inferred "prefer substantive". (D-059)
- **"Filter non-English titles."** Rejected outright — it contradicts the
  product's deliberate multilingual design. (D-059)
- **"Opus's extra length is padding."** Tested and refuted. Both blind judges
  were instructed to suspect it and count claims per unit length; both found
  opus **denser** (3.42 vs 2.42 propositions per 100 words). (D-062)
- **A judge's attribution verdict was partly a measurement artifact** — the
  plain-text conversion strips `href`, so working citations looked bare.
  Verified independently: all 1,489 anchors carried correct URLs, and the
  control's anchors were *also* 100% bare timestamps. The real defect was
  narrower than reported. (D-061)

Two live production bugs surfaced only because the pipeline was exercised
end-to-end:

- **Reasoning models return content *blocks*, not a string** — but only once
  the model actually thinks, so the shape flips per request. Every call site
  read `.content` directly, which would have written a stringified Python list
  into the report and broken every JSON-parsing site — silently, and
  specifically on the hardest prompts. Latent since D-053 moved those sites to
  sonnet-5; no report had run in between. (D-056)
- **Every timestamp citation in every report was a dead link** (`href="&t=123"`)
  — the map prompt asked each item for a `video_url` that the chunk header
  never supplied. (D-056)

---

## The measured arc

Same 200-video corpus (1,057,331 transcript words) throughout.

| Variant | Words | Videos linked | Citations | Dead links |
|---|---|---|---|---|
| Shipped 2026-07-22 | 5,610 | **0** | 143 | **143** |
| + funnel fix (D-056) | 25,692 | 125 | 1,058 | 0 |
| + Luna @0.40 (D-057/60) | 30,864 | 185 | 1,489 | 0 |
| + prompt fixes (S-1.14.14) | **37,380** | **188** | **1,540** | 0 |
| Max-effort control | 26,631 | 200 | 946 | 0 |

Blind judging, three independent lenses:

| Round | Production | Control | Gap |
|---|---|---|---|
| D-055 (original) | 3.50 | 8.50 | **severe** |
| D-061 (after funnel + Luna) | 6.94 | 8.72 | moderate |
| D-062 (after prompt fixes) | **7.22** | 8.67 | moderate |

Attribution went 6 → 9, **overtaking the control's 7**. Coverage moved from
moderate to minor. **Synthesis never moved: 6.33 in both rounds** — which is
precisely what justified the tier upgrade, and nothing else did.

---

## Why the ordering mattered

The tier upgrade was made **last**, and that is the transferable lesson.

| Change | Bought | Cost |
|---|---|---|
| Funnel fix | 0 → 125 videos, dead → working links | free |
| Volume tier → Luna | extraction 1,451 → 3,233 items | ~$0 |
| Extraction ceiling 0.20 → 0.40 | removed our own cap | +$0.34 |
| Prompt fixes | attribution 6 → 9 | free |
| **Tier upgrade → opus-5** | **synthesis 6 → 9** | **+$4.55** |

Had the tier upgrade come first, it would have been paid for and the report
would still have cited 2 channels. Every free fix was exhausted before the
expensive one was even measured — so the premium buys only what nothing else
could.

Benchmark cost across the arc: **$4.36 → $12.20** per 200-video job. The
increase is real and intended: reports cost more because they no longer
discard the corpus.

---

## Method notes worth keeping

- **Measure model limits, don't assume them.** Both context windows and output
  ceilings were obtained by sending a deliberately oversized request and
  parsing the API's own 400. Rejected requests are unbilled, so re-measuring
  after any model refresh is free.
- **Blind everything.** Orientation was hidden from every judge via a
  coin-flipped mapping file. On the tier test, judges were explicitly told to
  suspect the longer text of padding — which is why the refutation carries
  weight.
- **Pre-register the decision rule.** The rule that would justify a tier
  upgrade (synthesis stuck at ~6 rather than moving to ~8) was recorded before
  the results were seen.
- **Persist what you want to measure.** Selection quality was unmeasurable for
  two rounds purely because the rejected candidate pool was never stored.
  Persisting it (S-1.14.6) turned "audit the picks" into "re-rank and A/B",
  and immediately exposed that 14 of 18 missing preferred channels had
  candidates sitting in the rejects.
- **Don't judge a truncated document.** Production outgrew the 180,000-char
  judging cap and was assessed on a partial text. Filed as S-1.14.15.

---

## Left open deliberately

- **S-1.14.15** — the executive summary still mis-dates the corpus, leaks
  pipeline metadata into prose, and contradicts its own video count. Kept out
  of the tier-decision PR so that measurement stays unconfounded.
- **S-1.14.7** — surface the measured per-use-case deltas in
  `/account/ai-models`, turning the override knob from raw config into guided
  choice.
- **S-1.13.6** — Responses-API path for guaranteed `max` reasoning on
  `search_rank_and_curate`.
